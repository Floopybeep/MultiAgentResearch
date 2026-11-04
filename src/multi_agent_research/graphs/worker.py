import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from .. import prompts
from ..runtime import BudgetExceeded
from ..schemas import AgentState, WorkerResult, complete_task, read_document

TOOLS = [read_document, complete_task]


def build_worker(runtime, agent, checkpointer):
    cfg = runtime.config

    def finish(state, status, reason, **kwargs):
        return {
            "result": WorkerResult(
                assignment_id=agent, status=status, stop_reason=reason, **kwargs
            ).model_dump()
        }

    async def model_turn(state):
        if state.get("turns", 0) >= cfg.max_worker_turns:
            return finish(
                state, "budget_exhausted", "worker_turn_limit", document_ids=state.get("documents", [])
            )
        try:
            answer = await runtime.call_model("worker", agent, state["messages"], TOOLS)
            return {"messages": state["messages"] + [answer], "turns": state.get("turns", 0) + 1}
        except BudgetExceeded as exc:
            return finish(state, "budget_exhausted", str(exc), document_ids=state.get("documents", []))

    async def tools(state):
        answer = state["messages"][-1]
        calls = answer.tool_calls
        messages, documents = list(state["messages"]), list(state.get("documents", []))
        if not calls:
            messages.append(
                HumanMessage(content="Submit findings with complete_task, including document_ids.")
            )
            return {"messages": messages}
        remaining = cfg.max_worker_tool_calls - state.get("tool_calls", 0)
        if remaining <= 0:
            return finish(state, "budget_exhausted", "worker_tool_limit", document_ids=documents)
        allowed = calls[:remaining]

        async def execute(call):
            async def handler():
                if call["name"] == "read_document":
                    args = read_document.model_validate(call["args"])
                    return runtime.read_document(args.document_id, args.offset, agent=agent)
                if call["name"] == "complete_task":
                    if len(calls) != 1:
                        raise ValueError("complete_task must be the only call")
                    args = complete_task.model_validate(call["args"])
                    if not set(args.document_ids) <= set(documents):
                        raise ValueError("Reference document IDs successfully read in this assignment")
                    return {"completed": args.model_dump()}
                raise ValueError("Unknown worker tool")

            return await runtime.call_tool(agent, call, handler)

        outputs = await asyncio.gather(*(execute(c) for c in allowed))
        for call, output in zip(allowed, outputs):
            if isinstance(output, dict) and "completed" in output:
                args = output["completed"]
                return finish(
                    state,
                    "completed",
                    "complete_task",
                    findings=args["findings"],
                    document_ids=args["document_ids"],
                    uncertainties=args["uncertainties"],
                )
            if isinstance(output, dict) and "document_id" in output:
                documents.append(output["document_id"])
            messages.append(ToolMessage(content=json.dumps(output), tool_call_id=call["id"]))
        for call in calls[remaining:]:
            messages.append(
                ToolMessage(content='{"error":"worker_tool_limit"}', tool_call_id=call["id"])
            )
        return {
            "messages": messages,
            "documents": sorted(set(documents)),
            "tool_calls": state.get("tool_calls", 0) + len(allowed),
        }

    graph = StateGraph(AgentState)
    graph.add_node("worker", model_turn)
    graph.add_node("tools", tools)
    graph.add_edge(START, "worker")
    graph.add_conditional_edges("worker", lambda s: END if s.get("result") else "tools")
    graph.add_conditional_edges("tools", lambda s: END if s.get("result") else "worker")
    return graph.compile(checkpointer=checkpointer)


async def run_worker(runtime, agent, prompt, checkpointer):
    started = asyncio.get_running_loop().time()
    runtime.event(
        "worker.started", agent, {"assignment": prompt}, runtime.observed.get(agent, []).copy()
    )
    graph = build_worker(runtime, agent, checkpointer)
    try:
        state = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "messages": [
                        SystemMessage(
                            content=prompts.render(
                                prompts.load("worker", runtime.config.worker_prompt),
                                runtime.prompt_context,
                            )
                            + f"\nLimits: {runtime.config.max_worker_turns} model turns, "
                            f"{runtime.config.max_worker_tool_calls} tool calls."
                        ),
                        HumanMessage(content=json.dumps({
                            "assignment": prompt, "available_documents": runtime.documents.catalog(),
                        })),
                    ],
                    "documents": [],
                    "turns": 0,
                },
                {
                    "configurable": {"thread_id": f"{runtime.run_id}:{agent}"},
                    "recursion_limit": 2 * runtime.config.max_worker_turns + 5,
                },
            ),
            runtime.config.worker_timeout_seconds,
        )
        result = WorkerResult.model_validate(state["result"])
    except Exception as exc:
        result = WorkerResult(
            assignment_id=agent,
            status="failed",
            stop_reason=f"{type(exc).__name__}: {runtime.log.redact(str(exc))}",
        )
    runtime.event(
        "worker.finished", agent, result.model_dump(), runtime.observed[agent].copy(),
        duration_seconds=asyncio.get_running_loop().time() - started,
    )
    return result
