"""Lead QA tool loop and synchronous parallel-worker batches."""

import asyncio
import json
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..faults.base import Call
from ..runtime import BudgetExceeded, Runtime
from ..schemas import (
    AgentState,
    memory_read,
    memory_write,
    merge_results,
    run_blocking_subagent,
    submit_answer,
)
from .worker import run_worker

TOOLS = [memory_read, memory_write, run_blocking_subagent, submit_answer]


def build_research(
    runtime: Runtime, checkpointer: BaseCheckpointSaver | None,
) -> CompiledStateGraph:
    cfg = runtime.config

    async def lead(state):
        if state.get("turns", 0) >= cfg.max_lead_turns:
            return {"status": "budget_exhausted", "stop_reason": "lead_turn_limit"}
        try:
            response = await runtime.call_model("lead", "lead", state["messages"], TOOLS)
            return {
                "messages": state["messages"] + [response], "turns": state.get("turns", 0) + 1,
                "pending_tools": response.tool_calls, "tool_index": 0, "tool_outputs": {},
            }
        except BudgetExceeded as exc:
            return {"status": "budget_exhausted", "stop_reason": str(exc)}

    async def local_tool(state):
        calls = state.get("pending_tools", [])
        local = [(i, c) for i, c in enumerate(calls) if c["name"] != "run_blocking_subagent"]
        cursor = state.get("tool_index", 0)
        if cursor >= len(local):
            return {}
        index, call = local[cursor]
        results = state.get("results", {})

        async def handler():
            if call["name"] == "memory_write":
                args = memory_write.model_validate(call["args"])
                return runtime.memory.write(args.plan)
            if call["name"] == "memory_read":
                memory_read.model_validate(call["args"])
                return runtime.memory.read()
            if call["name"] == "submit_answer":
                if len(calls) != 1:
                    raise ValueError("Call submit_answer in its own turn")
                if not any(r["status"] == "completed" for r in results.values()):
                    raise ValueError("At least one successful worker result is required")
                return {"completed": submit_answer.model_validate(call["args"]).model_dump()}
            raise ValueError("Unknown lead tool")

        output = await runtime.call_tool("lead", "lead", call, handler)
        if "completed" in output:
            answer = output["completed"]["answer"]
            runtime.event("answer.submitted", "lead", {"answer": answer},
                          runtime.observed["lead"].copy())
            return {"answer": answer, "status": "completed", "stop_reason": "submit_answer"}
        return {"tool_index": cursor + 1,
                "tool_outputs": {**state.get("tool_outputs", {}), str(index): output}}

    async def tools(state):
        calls = state.get("pending_tools", [])
        messages = list(state["messages"])
        results = state.get("results", {})
        batches = state.get("batches", 0)
        if not calls:
            return {"messages": messages + [HumanMessage(
                content="Use the provided tools; submit your final {answer} via submit_answer."
            )]}
        outputs = {int(index): value for index, value in state.get("tool_outputs", {}).items()}
        delegated = [(i, c) for i, c in enumerate(calls) if c["name"] == "run_blocking_subagent"]
        if delegated:
            batch = batches + 1
            lead_dependencies = runtime.observed.get("lead", []).copy()
            # All parallel delegations start from the same consistent batch state.
            # Index them before dispatching any worker or mutating shared runtime state.
            recovery_points = {}
            for index, call in delegated:
                recovery_points[index] = await runtime.recovery.before_call(
                    "lead", "tool", call["name"], call,
                )
            delivery_parents = {}

            async def dispatch(position: int, index: int, call: dict[str, Any]):
                async def handler() -> dict[str, Any]:
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
                    delegation = Call(agent, "lead", call["name"], {
                        "prompt": args.prompt, "document_id": args.document_id,
                        "batch": batch, "position": position,
                        "batch_size": min(len(delegated), cfg.max_workers_per_batch),
                    })
                    result = await runtime.faults.run(
                        "delegation", delegation, lambda c: run_worker(
                            runtime, agent, c.args["prompt"], checkpointer,
                            document_id=c.args["document_id"],
                        ),
                    )
                    delivery_parents[index] = [runtime.observed[agent][-1]]
                    return result.model_dump()

                # Delegation is bounded by the worker timeout, not the shorter tool timeout.
                started = asyncio.get_running_loop().time()
                start = runtime.event(
                    "delegation.request", "lead", call, lead_dependencies, batch_id=batch,
                    recovery_point_id=recovery_points[index]
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
                    duration_seconds=asyncio.get_running_loop().time() - started,
                )
                return index, value

            returned = await asyncio.gather(
                *(dispatch(p, i, c) for p, (i, c) in enumerate(delegated))
            )
            for index, value in returned:
                parents = delivery_parents.get(index, lead_dependencies).copy()
                outputs[index] = value
                if "assignment_id" in value:
                    runtime.event(
                        "worker.delivered", "lead", value, parents,
                        batch_id=batch, assignment_id=value["assignment_id"],
                    )
                    results = merge_results(results, {value["assignment_id"]: value})
            batches = batch
        for index, call in enumerate(calls):
            messages.append(
                ToolMessage(content=json.dumps(outputs[index]), tool_call_id=call["id"])
            )
        return {"messages": messages, "results": results, "batches": batches}

    graph = StateGraph(AgentState)
    descriptor = {"kind": "lead", "scope": "agent"}
    graph.add_node("lead", runtime.recovery.node(lead, checkpointer, descriptor))
    graph.add_node("lead_tools", runtime.recovery.node(local_tool, checkpointer, descriptor))
    graph.add_node("dispatch_batch", runtime.recovery.node(
        tools, checkpointer, {"kind": "lead", "scope": "delegation_batch"},
    ))

    def after_local(state):
        if state.get("status"):
            return END
        count = sum(c["name"] != "run_blocking_subagent" for c in state.get("pending_tools", []))
        return "lead_tools" if state.get("tool_index", 0) < count else "dispatch_batch"

    graph.add_edge(START, "lead")
    graph.add_conditional_edges("lead", lambda s: END if s.get("status") else "lead_tools")
    graph.add_conditional_edges("lead_tools", after_local)
    graph.add_conditional_edges("dispatch_batch", lambda s: END if s.get("status") else "lead")
    return graph.compile(checkpointer=checkpointer)
