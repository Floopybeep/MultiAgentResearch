"""Lead QA tool loop and synchronous parallel-worker batches."""

import asyncio
import json
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..faults.pipeline import PipelineFaultInjector
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
    injector = PipelineFaultInjector(cfg.pipeline_fault)

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
                        content="Use the provided tools; submit your final {answer} via submit_answer."
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
                if call["name"] == "submit_answer":
                    if len(calls) != 1:
                        raise ValueError("Call submit_answer in its own turn")
                    if not any(r["status"] == "completed" for r in results.values()):
                        raise ValueError("At least one successful worker result is required")
                    return {"completed": submit_answer.model_validate(call["args"]).model_dump()}
                raise ValueError("Unknown lead tool")

            outputs[index] = await runtime.call_tool("lead", call, handler)
            if "completed" in outputs[index]:
                answer = outputs[index]["completed"]["answer"]
                runtime.event("answer.submitted", "lead", {"answer": answer}, runtime.observed["lead"].copy())
                return {"answer": answer, "status": "completed", "stop_reason": "submit_answer"}

        delegated = [(i, c) for i, c in enumerate(calls) if c["name"] == "run_blocking_subagent"]
        if delegated:
            batch = batches + 1
            lead_dependencies = runtime.observed.get("lead", []).copy()

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
                    decision = injector.decide(agent)
                    fault_parent = injector.log_decision(runtime, agent, batch, start, decision)
                    if decision["selected"] and cfg.pipeline_fault.fault_type == "dispatch_failure":
                        value, event = injector.inject(runtime, agent, batch, fault_parent,
                                                       worker_executed=False)
                        delivery_parents[:] = [event]
                        return value
                    result = await run_worker(runtime, agent, args.prompt, checkpointer)
                    delivery_parent = runtime.observed[agent][-1]
                    value = result.model_dump()
                    if (decision["selected"] and result.status == "completed"
                            and cfg.pipeline_fault.fault_type != "dispatch_failure"):
                        value, delivery_parent = injector.inject(
                            runtime, agent, batch, delivery_parent, worker_executed=True,
                            original=value, decision_event=fault_parent,
                        )
                    runtime.event(
                        "worker.delivered", "lead", value,
                        [delivery_parent], batch_id=batch, assignment_id=agent,
                    )
                    delivery_parents[:] = [runtime.observed["lead"][-1]]
                    return value

                # Delegation is bounded by the worker timeout, not the shorter tool timeout.
                started = asyncio.get_running_loop().time()
                start = runtime.event(
                    "delegation.request", "lead", call, lead_dependencies, batch_id=batch
                )
                delivery_parents = [start]
                try:
                    value = await handler()
                except Exception as exc:
                    value = {"error": type(exc).__name__, "message": str(exc)}
                runtime.event(
                    "delegation.result",
                    "lead",
                    value,
                    delivery_parents,
                    batch_id=batch,
                    tool_call_id=call["id"],
                    duration_seconds=asyncio.get_running_loop().time() - started,
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

    graph.add_edge(START, "lead")
    graph.add_conditional_edges("lead", lambda s: END if s.get("status") else "lead_tools")
    graph.add_conditional_edges("lead_tools", lambda s: END if s.get("status") else "lead")
    return graph.compile(checkpointer=checkpointer)
