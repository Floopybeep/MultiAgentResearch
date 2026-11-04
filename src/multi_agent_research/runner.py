"""QA attempts, oracle-triggered full restart and combined accounting."""

import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from copy import deepcopy
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from . import prompts
from .config import RunConfig
from .grading import grade_answer
from .graphs.research import build_research
from .models.adapter import ModelAdapter
from .observability.usage import sum_usage
from .runtime import Runtime
from .storage.checkpoints import checkpoint_store
from .tools.documents import OracleDocuments

logger = logging.getLogger(__name__)


def _build_clean_restart_config(base_config: RunConfig) -> RunConfig:
    """Copy the saved experimental baseline without normalizing any resource limits."""
    clean = base_config.model_copy(deep=True)
    for name in ("document_injection", "connection_drop", "result_timeout", "tool_failure"):
        getattr(clean, name).enabled = False
    return clean


async def _run_attempt(
    runtime: Runtime, question: str, reference_answer: str | None,
    metadata: dict[str, Any] | None, attempt_number: int, previous_run_id: str | None,
) -> dict[str, Any]:
    config = runtime.config
    started = time.monotonic()
    prompt_hashes = prompts.hashes(config, include_verifier=config.always_verify)
    runtime.db.record("prompts", prompt_hashes)
    runtime.event("run.started", "lead", {
        "task_type": "frames_qa", "query": question, "metadata": metadata or {},
        "prompt_hashes": prompt_hashes, "attempt_number": attempt_number,
        "previous_run_id": previous_run_id, "strategy": config.strategy,
        "faults_enabled": runtime.faults_enabled,
    })
    snapshots = runtime.snapshot_documents()
    async with AsyncExitStack() as stack:
        # Each restart attempt owns a new, empty checkpointer, not a resumed checkpoint.
        saver = InMemorySaver() if config.full_restart else await stack.enter_async_context(
            checkpoint_store(runtime.root / "checkpoints.sqlite")
        )
        invocation_config = {
            "configurable": {"thread_id": runtime.run_id},
            "recursion_limit": 2 * config.max_lead_turns + 6,
        }
        initial_state = {
            "messages": [
                SystemMessage(
                    content=prompts.render(
                        prompts.load("lead", config.lead_prompt), runtime.prompt_context,
                    )
                    + f"\nLimits: {config.max_lead_turns} lead turns, "
                    f"{config.max_batches} batches, "
                    f"{config.max_workers_per_batch} workers per batch. "
                    f"Spawn at least {config.minimum_worker} workers in each delegation batch."
                ),
                HumanMessage(content=json.dumps({
                    "question": question, "available_documents": runtime.documents.catalog(),
                })),
            ],
            "results": {}, "batches": 0, "turns": 0,
        }
        reset_audit = {
            "previous_run_id": previous_run_id,
            "previous_runtime_closed": previous_run_id is not None,
            "thread_id": runtime.run_id, "checkpointer_type": type(saver).__name__,
            "empty_checkpointer": await saver.aget_tuple(invocation_config) is None,
            "initial_plan_ref": runtime.memory.ref,
            "initial_message_count": len(initial_state["messages"]),
            "initial_worker_results": len(initial_state["results"]),
            "initial_lead_turns": initial_state["turns"],
            "initial_batches": initial_state["batches"],
            "initial_model_inputs": len(runtime.model_inputs),
            "initial_verifications": len(runtime.verifications),
            "initial_model_calls": runtime.usage.calls,
            "initial_document_injection_count": runtime.document_injection_count,
            "initial_tool_failure_count": runtime.tool_failure_state.failures,
            "initial_tool_failure_attempts": len(runtime.tool_failure_state.attempts),
            "initial_denied_pages": len(runtime.tool_failure_state.denied),
            "initial_injected_faults": len(runtime.injected_faults),
            "faults_enabled": runtime.faults_enabled,
        }
        runtime.event("attempt.started", "system", reset_audit)
        graph = build_research(runtime, saver)
        try:
            # Fault events never cancel calls. The graph stops at a completed node/batch.
            # Ordinary configured deadlines still apply and produce native failures.
            state = await asyncio.wait_for(
                graph.ainvoke(initial_state, invocation_config), config.run_timeout_seconds,
            )
        except TimeoutError:
            state = {"status": "budget_exhausted", "stop_reason": "run_timeout"}
        except Exception as exc:
            state = {
                "status": "failed",
                "stop_reason": f"{type(exc).__name__}: {runtime.log.redact(str(exc))}",
            }
        if state.get("status") == "interrupted":
            runtime.event("attempt.interrupted", "system", {
                "reason": "fault_injected", "injected_faults": runtime.injected_faults.copy(),
                "active_calls_cancelled": False,
            }, [ids[-1] for ids in runtime.observed.values() if ids])
        snapshot = await graph.aget_state(invocation_config)
        if snapshot.values:
            state = {**snapshot.values, **state}
        checkpoint_id = (
            snapshot.config.get("configurable", {}).get("checkpoint_id")
            if snapshot.config else None
        )
    solve_seconds = time.monotonic() - started
    runtime.event("solve.finished", "system", {
        "status": state.get("status", "failed"), "duration_seconds": solve_seconds,
        "answer": state.get("answer"), "stop_reason": state.get("stop_reason"),
    }, [ids[-1] for ids in runtime.observed.values() if ids])
    grade = None
    will_restart = config.full_restart and attempt_number == 1 and bool(runtime.injected_faults)
    if reference_answer is not None and not will_restart:
        if state.get("answer"):
            grade = await grade_answer(runtime, question, reference_answer, state["answer"])
        else:
            grade = {
                "method": "not_answered", "correct": False, "format_valid": False,
                "exact_match": False, "extracted_answer": None,
                "duration_seconds": 0, "usage": runtime.usage_by_role["judge"].as_dict(),
            }
            runtime.event("grade.finished", "judge", grade)
    elapsed = time.monotonic() - started
    result = dict(
        run_id=runtime.run_id, output_dir=str(runtime.root), task_type="frames_qa",
        attempt_number=attempt_number, strategy=config.strategy,
        config=config.model_dump(mode="json"),
        faults_enabled=runtime.faults_enabled,
        fault_injected=bool(runtime.injected_faults),
        injected_faults=runtime.injected_faults.copy(),
        document_injection_count=runtime.document_injection_count, state_reset=reset_audit,
        reference_answer=reference_answer, question=question, metadata=metadata or {},
        status=state.get("status", "failed"), stop_reason=state.get("stop_reason"),
        answer=state.get("answer"), grade=grade, correct=grade.get("correct") if grade else None,
        worker_results=state.get("results", {}), verifications=runtime.verifications,
        usage=runtime.usage.as_dict(),
        usage_by_role={k: v.as_dict() for k, v in runtime.usage_by_role.items()},
        solve_duration_seconds=solve_seconds, duration_seconds=elapsed, elapsed_seconds=elapsed,
        checkpoint_id=checkpoint_id,
    )
    if state.get("answer"):
        path = runtime.root / "answer.txt"
        path.write_text(runtime.log.redact(state["answer"]), encoding="utf-8")
        result["answer_path"] = str(path)
    (runtime.root / "documents.json").write_text(
        json.dumps(runtime.log.redact(snapshots), indent=2), encoding="utf-8"
    )
    return runtime.log.redact(result)


async def run_qa(
    question: str, config: RunConfig, model: ModelAdapter, documents: OracleDocuments,
    *, reference_answer: str | None = None, metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("Question cannot be empty")
    # Save the experimental baseline before any injector can mutate attempt settings.
    base_config = config.model_copy(deep=True)
    clean_config = _build_clean_restart_config(base_config)
    attempts = []
    wall_started = time.monotonic()
    for number in (1, 2):
        attempt_config = (base_config if number == 1 else clean_config).model_copy(deep=True)
        # Reuse only immutable inputs and the stateless transport, never graph state.
        runtime = Runtime(attempt_config, model, deepcopy(documents))
        runtime.attempt_number = number
        runtime.faults_enabled = number == 1
        previous_run_id = attempts[-1]["run_id"] if attempts else None
        logger.info("Attempt %d: starting (strategy=%s).", number, config.strategy)
        try:
            attempt = await _run_attempt(
                runtime, question, reference_answer, metadata, number, previous_run_id,
            )
            attempts.append(attempt)
            runtime.event("attempt.finished", "system", attempt,
                          [ids[-1] for ids in runtime.observed.values() if ids])
            should_restart = base_config.full_restart and number == 1 and attempt["fault_injected"]
            restarted = number == 2
            result = dict(attempt)
            # TODO: Derive propagation/adoption and wasted-work metrics from paired traces.
            combined_usage = sum_usage(a["usage"] for a in attempts)
            result.update(
                attempts=attempts.copy(), selected_attempt=number, restarted=restarted,
                base_config=base_config.model_dump(mode="json"),
                fault_injected=any(a["fault_injected"] for a in attempts),
                injected_faults=[fault for a in attempts for fault in a["injected_faults"]],
                restart_reason="fault_injected" if restarted or should_restart else None,
                clean_slate_reset=(
                    attempts[0]["run_id"] != attempt["run_id"]
                    and attempt["state_reset"]["empty_checkpointer"]
                    and attempt["state_reset"]["initial_plan_ref"] is None
                    and attempt["state_reset"]["checkpointer_type"] == "InMemorySaver"
                    and attempt["state_reset"]["previous_runtime_closed"]
                    and attempt["state_reset"]["initial_message_count"] == 2
                    and attempt["state_reset"]["initial_model_calls"] == 0
                    and attempt["state_reset"]["initial_worker_results"] == 0
                    and attempt["state_reset"]["initial_model_inputs"] == 0
                    and attempt["state_reset"]["initial_verifications"] == 0
                    and attempt["state_reset"]["initial_lead_turns"] == 0
                    and attempt["state_reset"]["initial_batches"] == 0
                    and attempt["state_reset"]["initial_document_injection_count"] == 0
                    and attempt["state_reset"]["initial_tool_failure_count"] == 0
                    and attempt["state_reset"]["initial_tool_failure_attempts"] == 0
                    and attempt["state_reset"]["initial_denied_pages"] == 0
                    and attempt["state_reset"]["initial_injected_faults"] == 0
                    and not attempt["faults_enabled"]
                    and not attempt["fault_injected"]
                ) if restarted else None,
                usage=combined_usage, usage_by_role=combined_usage["by_role"],
                solve_duration_seconds=sum(a["solve_duration_seconds"] for a in attempts),
                elapsed_seconds=sum(a["elapsed_seconds"] for a in attempts),
                wall_duration_seconds=time.monotonic() - wall_started,
            )
            result["duration_seconds"] = result["elapsed_seconds"]
            result["total_tokens"] = result["usage"]["total_tokens"]
            result["total_cost"] = result["usage"]["estimated_cost_usd"]
            if should_restart:
                runtime.event("recovery.restart", "system", {
                    "reason": "fault_injected", "injected_faults": attempt["injected_faults"],
                    "next_attempt": 2, "clean_config": clean_config.model_dump(mode="json"),
                }, runtime.observed.get("system", [])[-1:])
            runtime.event("run.finished", "system", result,
                          [ids[-1] for ids in runtime.observed.values() if ids])
            runtime.db.record("run", result)
            (runtime.root / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        finally:
            runtime.close()
            del runtime
        logger.info("Attempt %d: finished (%s).", number, attempt["status"])
        if not should_restart:
            break
    return result
