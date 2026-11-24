import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from .. import prompts
from ..runtime import BudgetExceeded
from ..schemas import AgentState, WorkerResult, complete_task, read_document

TOOLS = [read_document, complete_task]


def build_worker(runtime, agent, checkpointer, *, document_id: str):
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
            return {"messages": state["messages"] + [answer],
                    "turns": state.get("turns", 0) + 1,
                    "pending_tools": answer.tool_calls, "tool_index": 0}
        except BudgetExceeded as exc:
            return finish(state, "budget_exhausted", str(exc), document_ids=state.get("documents", []))

    async def tools(state):
        calls = state.get("pending_tools", [])
        index = state.get("tool_index", 0)
        messages, documents = list(state["messages"]), list(state.get("documents", []))
        if not calls:
            messages.append(
                HumanMessage(content="Submit findings with complete_task, including document_ids.")
            )
            return {"messages": messages}
        used = state.get("tool_calls", 0)
        if used >= cfg.max_worker_tool_calls:
            messages.extend(ToolMessage(content=json.dumps({"error": "worker_tool_limit"}),
                                        tool_call_id=call["id"]) for call in calls[index:])
            update = {"messages": messages, "tool_index": len(calls)}
            if index == 0:
                update.update(finish(state, "budget_exhausted", "worker_tool_limit",
                                     document_ids=documents))
            return update

        call = calls[index]

        async def handler():
            if call["name"] == "read_document":
                args = read_document.model_validate(call["args"])
                if args.document_id != document_id:
                    raise PermissionError("Document is not assigned to this worker")
                return await runtime.read_document(args.document_id, args.offset)
            if call["name"] == "complete_task":
                if len(calls) != 1:
                    raise ValueError("complete_task must be the only call")
                args = complete_task.model_validate(call["args"])
                if not set(args.document_ids) <= set(documents):
                    raise ValueError("Reference document IDs successfully read in this assignment")
                return {"completed": args.model_dump()}
            raise ValueError("Unknown worker tool")

        output = await runtime.call_tool(agent, call, handler)
        update = {"tool_calls": used + 1, "tool_index": index + 1}
        if isinstance(output, dict) and "completed" in output:
            args = output["completed"]
            return {**update, **finish(
                state, "completed", "complete_task", findings=args["findings"],
                document_ids=args["document_ids"], uncertainties=args["uncertainties"],
            )}
        if isinstance(output, dict) and "document_id" in output:
            documents.append(output["document_id"])
        messages.append(ToolMessage(content=json.dumps(output), tool_call_id=call["id"]))
        return {**update, "messages": messages, "documents": sorted(set(documents))}

    descriptor = {"kind": "worker", "document_id": document_id}
    graph = StateGraph(AgentState)
    graph.add_node("worker", runtime.recovery.node(model_turn, checkpointer, descriptor))
    graph.add_node("tools", runtime.recovery.node(tools, checkpointer, descriptor))
    graph.add_edge(START, "worker")
    graph.add_conditional_edges("worker", lambda s: END if s.get("result") else "tools")
    graph.add_conditional_edges("tools", lambda s: END if s.get("result") else (
        "tools" if s.get("tool_index", 0) < len(s.get("pending_tools", [])) else "worker"
    ))
    return graph.compile(checkpointer=checkpointer)


async def run_worker(runtime, agent, prompt, checkpointer, *, document_id: str):
    document = runtime.documents.documents.get(document_id)
    if document is None:
        raise ValueError("Assigned document is outside this question's catalog")
    started = asyncio.get_running_loop().time()
    runtime.event(
        "worker.started", agent, {"assignment": prompt, "document_id": document_id},
        runtime.observed.get(agent, []).copy(),
    )
    graph = build_worker(runtime, agent, checkpointer, document_id=document_id)
    state = None
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
                            "assignment": prompt, "available_documents": [document.catalog_entry()],
                        })),
                    ],
                    "documents": [],
                    "turns": 0,
                },
                {
                    "configurable": {"thread_id": f"{runtime.run_id}:{agent}", "checkpoint_ns": ""},
                    "recursion_limit": (2 * runtime.config.max_worker_turns
                                        + runtime.config.max_worker_tool_calls + 10),
                },
                durability="sync",
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
