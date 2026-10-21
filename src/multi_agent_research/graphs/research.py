"""Lead tool loop, synchronous parallel-worker batches, and citation handoff."""

import asyncio
import json

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from ..runtime import BudgetExceeded
from ..schemas import (
    AgentState,
    complete_task,
    memory_read,
    memory_write,
    merge_results,
    run_blocking_subagent,
)
from .citations import cite
from .worker import run_worker

TOOLS = [memory_read, memory_write, run_blocking_subagent, complete_task]


def build_research(runtime, checkpointer):
    cfg = runtime.config

    async def lead(state):
        if state.get("turns", 0) >= cfg.max_lead_turns:
            return {"status": "budget_exhausted", "stop_reason": "lead_turn_limit"}
        try:
            response = await runtime.call_model("lead", "lead", state["messages"], TOOLS)
            return {"messages": state["messages"] + [response], "turns": state.get("turns", 0) + 1}
        except BudgetExceeded as exc:
            return {"status": "budget_exhausted", "stop_reason": str(exc)}

    async def tools(state):
        calls = state["messages"][-1].tool_calls
        messages = list(state["messages"])
        results = state.get("results", {})
        batches = state.get("batches", 0)
        if not calls:
            return {
                "messages": messages
                + [
                    HumanMessage(
                        content="Use the provided tools; submit your draft via complete_task."
                    )
                ]
            }
        outputs = {}
        # Memory updates precede dispatch. Completion cannot share a turn with other tools.
        for index, call in enumerate(calls):
            if call["name"] == "run_blocking_subagent":
                continue

            async def handler(call=call):
                if call["name"] == "memory_write":
                    args = memory_write.model_validate(call["args"])
                    return runtime.memory.write(args.plan)
                if call["name"] == "memory_read":
                    memory_read.model_validate(call["args"])
                    return runtime.memory.read()
                if call["name"] == "complete_task":
                    if len(calls) != 1:
                        raise ValueError("complete_task must be the only tool call")
                    if not any(r["status"] == "completed" for r in results.values()):
                        raise ValueError("At least one successful worker result is required")
                    return {"completed": complete_task.model_validate(call["args"]).model_dump()}
                raise ValueError("Unknown lead tool")

            outputs[index] = await runtime.call_tool("lead", call, handler)
            if "completed" in outputs[index]:
                draft = outputs[index]["completed"]["report"]
                runtime.db.record(
                    "draft", {"artifact_ref": runtime.artifacts.put({"draft": draft})}
                )
                return {"draft": draft}

        delegated = [(i, c) for i, c in enumerate(calls) if c["name"] == "run_blocking_subagent"]
        if delegated:
            batch = batches + 1
            lead_dependencies = runtime.observed.get("lead", []).copy()

            async def dispatch(position, index, call):
                async def handler():
                    if not runtime.memory.ref:
                        raise ValueError("Save a research plan before delegation")
                    if batch > cfg.max_batches:
                        raise ValueError(
                            "Research batch limit exhausted; synthesize available evidence"
                        )
                    if position >= cfg.max_workers_per_batch:
                        raise ValueError(
                            "Worker concurrency limit; this assignment was not executed"
                        )
                    args = run_blocking_subagent.model_validate(call["args"])
                    agent = f"batch{batch}-worker{position + 1}"
                    runtime.observed[agent] = [start]
                    result = await run_worker(runtime, agent, args.prompt, checkpointer)
                    # Explicit worker-to-lead dependency, without sharing private worker context.
                    runtime.event(
                        "worker.delivered",
                        "lead",
                        result.model_dump(),
                        [runtime.observed[agent][-1]],
                        batch_id=batch,
                        assignment_id=agent,
                    )
                    return result.model_dump()

                # Delegation is bounded by the worker timeout, not the shorter tool timeout.
                start = runtime.event(
                    "delegation.request", "lead", call, lead_dependencies, batch_id=batch
                )
                try:
                    value = await handler()
                except Exception as exc:
                    value = {"error": type(exc).__name__, "message": str(exc)}
                runtime.event(
                    "delegation.result",
                    "lead",
                    value,
                    [start],
                    batch_id=batch,
                    tool_call_id=call["id"],
                )
                return index, value

            returned = await asyncio.gather(
                *(dispatch(p, i, c) for p, (i, c) in enumerate(delegated))
            )
            for index, value in returned:
                outputs[index] = value
                if "assignment_id" in value:
                    results = merge_results(results, {value["assignment_id"]: value})
            batches = batch
        for index, call in enumerate(calls):
            messages.append(
                ToolMessage(content=json.dumps(outputs[index]), tool_call_id=call["id"])
            )
        return {"messages": messages, "results": results, "batches": batches}

    graph = StateGraph(AgentState)
    graph.add_node("lead", lead)
    graph.add_node("lead_tools", tools)

    async def citation(state):
        return await cite(runtime, state)

    graph.add_node("citation", citation)
    graph.add_edge(START, "lead")
    graph.add_conditional_edges("lead", lambda s: END if s.get("status") else "lead_tools")
    graph.add_conditional_edges("lead_tools", lambda s: "citation" if s.get("draft") else "lead")
    graph.add_edge("citation", END)
    return graph.compile(checkpointer=checkpointer)
