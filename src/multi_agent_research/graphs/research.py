"""Lead QA tool loop and synchronous parallel-worker batches."""

import asyncio
import json
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..runtime import BudgetExceeded, Runtime
from ..schemas import (
    AgentState,
    WorkerResult,
    memory_read,
    memory_write,
    merge_results,
    run_blocking_subagent,
    submit_answer,
)
from ..tools.connection_drop import select_dropped
from ..verification import verify_boundary
from .worker import run_worker

TOOLS = [memory_read, memory_write, run_blocking_subagent, submit_answer]


def build_research(
    runtime: Runtime, checkpointer: BaseCheckpointSaver | None,
) -> CompiledStateGraph:
    cfg = runtime.config

    def finish_node(result):
        # Only explicit oracle events stop a completed node or joined worker batch.
        if (cfg.full_restart and runtime.attempt_number == 1 and runtime.injected_faults):
            return {**result, "status": "interrupted", "stop_reason": "fault_injected"}
        return result

    async def lead(state):
        if state.get("turns", 0) >= cfg.max_lead_turns:
            return finish_node({"status": "budget_exhausted", "stop_reason": "lead_turn_limit"})
        try:
            response = await runtime.call_model("lead", "lead", state["messages"], TOOLS)
            return finish_node({
                "messages": state["messages"] + [response], "turns": state.get("turns", 0) + 1,
            })
        except BudgetExceeded as exc:
            return finish_node({"status": "budget_exhausted", "stop_reason": str(exc)})

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
        plan_diagnostic = None
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
                runtime.event(
                    "answer.submitted", "lead", {"answer": answer},
                    runtime.observed["lead"].copy(),
                )
                return finish_node({
                    "answer": answer, "status": "completed", "stop_reason": "submit_answer",
                })

        delegated = [(i, c) for i, c in enumerate(calls) if c["name"] == "run_blocking_subagent"]
        if delegated:
            batch = batches + 1
            lead_dependencies = runtime.observed.get("lead", []).copy()
            if cfg.always_verify:
                plan_diagnostic = await verify_boundary(
                    runtime, "lead", "lead_plan", runtime.model_inputs.get("lead", []),
                    {"content": state["messages"][-1].content, "tool_calls": calls},
                    parents=lead_dependencies,
                )
                lead_dependencies.append(plan_diagnostic["event_id"])
            dropped, timed_out = [], []
            if (runtime.faults_enabled and runtime.memory.ref and batch <= cfg.max_batches):
                executable = min(len(delegated), cfg.max_workers_per_batch)
                dropped = select_dropped(cfg.connection_drop, batch, executable)
                timed_out = select_dropped(cfg.result_timeout, batch, executable)
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
                    if position in dropped:
                        runtime.event(
                            "connection.dropped", "lead",
                            {
                                "assignment_id": agent,
                                "document_id": args.document_id,
                                "position": position + 1,
                                "drop_number": dropped.index(position) + 1,
                                "assignment": args.prompt,
                            },
                            [start], batch_id=batch, assignment_id=agent,
                        )
                        raise ConnectionError(
                            "Connection to worker lost; assignment was not delivered"
                        )
                    runtime.observed[agent] = [start]
                    result = await run_worker(
                        runtime, agent, args.prompt, checkpointer, document_id=args.document_id,
                    )
                    parents = [runtime.observed[agent][-1]]
                    if position in timed_out:
                        deadline = cfg.result_timeout.timeout_seconds
                        elapsed = asyncio.get_running_loop().time() - started
                        injected = runtime.event(
                            "result.timed_out", "lead",
                            {
                                "assignment_id": agent,
                                "document_id": args.document_id,
                                "position": position + 1,
                                "timeout_number": timed_out.index(position) + 1,
                                "timeout_seconds": deadline,
                                "late": elapsed > deadline,
                                "worker_status": result.status,
                                "original_result_ref": runtime.artifacts.put(
                                    runtime.log.redact(result.model_dump())
                                ),
                            },
                            parents, batch_id=batch, assignment_id=agent,
                        )
                        parents.append(injected)
                        await asyncio.sleep(max(
                            deadline - (asyncio.get_running_loop().time() - started), 0,
                        ))
                        result = WorkerResult(
                            assignment_id=agent, status="failed", stop_reason="TimeoutError: ",
                        )
                    # Verify exactly what will be delivered, never the withheld artifact.
                    delivery = result.model_dump()
                    if cfg.always_verify:
                        diagnostic = await verify_boundary(
                            runtime, agent, "worker_result", runtime.model_inputs.get(agent, []),
                            delivery, parents=parents,
                        )
                        delivery = {**delivery, "verification": diagnostic}
                        parents.append(diagnostic["event_id"])
                    delivery_parents[index] = parents
                    return delivery

                # Delegation is bounded by the worker timeout, not the shorter tool timeout.
                started = asyncio.get_running_loop().time()
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
        if plan_diagnostic is not None:
            # One batch-level diagnostic, after all matching tool responses.
            messages.append(HumanMessage(content=json.dumps({
                "batch_id": batch, "plan_verification": plan_diagnostic,
            })))
        return finish_node({"messages": messages, "results": results, "batches": batches})

    graph = StateGraph(AgentState)
    graph.add_node("lead", lead)
    graph.add_node("lead_tools", tools)

    graph.add_edge(START, "lead")
    graph.add_conditional_edges("lead", lambda s: END if s.get("status") else "lead_tools")
    graph.add_conditional_edges("lead_tools", lambda s: END if s.get("status") else "lead")
    return graph.compile(checkpointer=checkpointer)
