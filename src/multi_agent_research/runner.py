"""One QA run: solve, grade and write the final files."""

import asyncio
import json
import logging
import shutil
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from . import prompts, strategies
from .config import RunConfig
from .grading import grade_answer
from .graphs.research import build_research
from .models.adapter import ModelAdapter
from .observability.usage import sum_usage
from .recovery import open_branch
from .runtime import Runtime
from .storage.checkpoints import checkpoint_store
from .tools.documents import OracleDocuments
from .verification import recorded_verifications

logger = logging.getLogger(__name__)


async def _solve(
    runtime: Runtime, question: str, metadata: dict[str, Any] | None, attempt_number: int,
    point: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Lead graph from a fresh state, or from recovery `point`, to its final state."""
    config = runtime.config
    started = time.monotonic()
    if point is None:
        prompt_hashes = prompts.hashes(config, include_verifier=config.recovery == "always_verify")
        runtime.db.record("prompts", prompt_hashes)
        runtime.event("run.started", "lead", {
            "task_type": "frames_qa", "query": question, "metadata": metadata or {},
            "prompt_hashes": prompt_hashes, "attempt_number": attempt_number,
            "faults_enabled": runtime.faults_enabled,
        })
        snapshots = runtime.snapshot_documents()
    else:  # the copied log already started the run and listed the documents
        snapshots = json.loads((runtime.root / "documents.json").read_text(encoding="utf-8"))
    async with AsyncExitStack() as stack:
        saver = await stack.enter_async_context(
            checkpoint_store(runtime.root / "checkpoints.sqlite")
        )
        invocation_config = {
            "configurable": {"thread_id": runtime.run_id},
            # One step per tool plus routing/model steps; turn limits still apply.
            "recursion_limit": (config.lead.max_output_tokens + 4) * config.max_lead_turns + 10,
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
        if point is not None:  # continue the copied Lead thread from the point's checkpoint
            initial_state, invocation_config = None, point["graph_config"]
        graph = build_research(runtime, saver)
        try:
            state = await asyncio.wait_for(
                graph.ainvoke(initial_state, invocation_config, durability="sync"),
                config.run_timeout_seconds,
            )
        except TimeoutError:
            state = {"status": "budget_exhausted", "stop_reason": "run_timeout"}
        except Exception as exc:
            state = {
                "status": "failed",
                "stop_reason": f"{type(exc).__name__}: {runtime.log.redact(str(exc))}",
            }
        thread = {"configurable": {"thread_id": invocation_config["configurable"]["thread_id"]}}
        snapshot = await graph.aget_state(thread)  # latest, not the resumed point
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
    return {"state": state, "checkpoint_id": checkpoint_id, "snapshots": snapshots,
            "started": started, "solve_seconds": solve_seconds,
            "recovered_from": point["recovery_point_id"] if point else None}


async def _finish_attempt(
    runtime: Runtime, attempt_number: int, question: str, reference_answer: str | None,
    metadata: dict[str, Any] | None, solved: dict[str, Any], *, graded: bool,
) -> dict[str, Any]:
    """Grade the attempt if `graded` (not when it will be restarted), and write its files."""
    config = runtime.config
    state = solved["state"]
    grade = None
    if reference_answer is not None and graded:
        if state.get("answer"):
            grade = await grade_answer(runtime, question, reference_answer, state["answer"])
        else:
            grade = {
                "method": "not_answered", "correct": False, "format_valid": False,
                "exact_match": False, "extracted_answer": None,
                "duration_seconds": 0, "usage": runtime.usage_by_role["judge"].as_dict(),
            }
            runtime.event("grade.finished", "judge", grade)
    elapsed = time.monotonic() - solved["started"]
    result = dict(
        run_id=runtime.run_id, output_dir=str(runtime.root), task_type="frames_qa",
        attempt_number=attempt_number, strategy=config.recovery,
        faults_enabled=runtime.faults_enabled, fault_injected=bool(runtime.faults.fired),
        config=config.model_dump(mode="json"),
        reference_answer=reference_answer, question=question, metadata=metadata or {},
        status=state.get("status", "failed"), stop_reason=state.get("stop_reason"),
        answer=state.get("answer"), grade=grade, correct=grade.get("correct") if grade else None,
        worker_results=state.get("results", {}),
        verifications=recorded_verifications(runtime),
        usage=runtime.usage.as_dict(),
        usage_by_role={k: v.as_dict() for k, v in runtime.usage_by_role.items()},
        solve_duration_seconds=solved["solve_seconds"], duration_seconds=elapsed,
        elapsed_seconds=elapsed, checkpoint_id=solved["checkpoint_id"],
        recovered_from=solved["recovered_from"],
    )
    if state.get("answer"):
        path = runtime.root / "answer.txt"
        path.write_text(runtime.log.redact(state["answer"]), encoding="utf-8")
        result["answer_path"] = str(path)
    (runtime.root / "documents.json").write_text(
        json.dumps(runtime.log.redact(solved["snapshots"]), indent=2), encoding="utf-8"
    )
    return runtime.log.redact(result)


def _question_result(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """The question result: the selected (last) attempt, every attempt's summary, and usage
    and time summed over all attempts."""
    final = attempts[-1]
    return {
        **final,
        "attempts": [{k: v for k, v in a.items() if k not in (
            "config", "question", "reference_answer", "metadata", "worker_results",
        )} for a in attempts],
        "selected_attempt": final["attempt_number"],
        "restarted": len(attempts) > 1,
        "usage": sum_usage(a["usage"] for a in attempts),
        "usage_by_role": {role: sum_usage(a["usage_by_role"][role] for a in attempts)
                          for role in final["usage_by_role"]},
        **{key: sum(a[key] for a in attempts)
           for key in ("solve_duration_seconds", "duration_seconds", "elapsed_seconds")},
    }


async def run_qa(
    question: str, config: RunConfig, model: ModelAdapter, documents: OracleDocuments,
    *, reference_answer: str | None = None, metadata: dict[str, Any] | None = None,
    question_root: Path | None = None,
) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("Question cannot be empty")
    attempts = []
    rollback = None  # selective: (recovery point ID, reusable Worker results)
    while True:
        number = len(attempts) + 1
        root = question_root / f"attempt-{number}" if question_root else None
        viewer_root = config.output_dir if question_root else None
        point = None
        if rollback is None:
            runtime = Runtime(config, model, documents, root=root, viewer_root=viewer_root)
        else:
            source = Path(attempts[0]["output_dir"])
            runtime, point, _ = open_branch(source, rollback[0], model=model, output_dir=root,
                                            viewer_root=viewer_root)
            shutil.copy(source / "documents.json", runtime.root)
            runtime.reuse = rollback[1]
        # Faults are injected in the first attempt only; a restart reruns the same config
        # with a fresh token budget.
        runtime.faults_enabled = number == 1
        try:
            solved = await _solve(runtime, question, metadata, number, point)
            # Restart after any fault, however the attempt ended; `interrupted` only stops
            # a faulted attempt early.
            restart = config.recovery in strategies.RESTARTS and bool(strategies.sites(runtime))
            rollback = (strategies.rollback(runtime)
                        if restart and config.recovery == "selective" else None)
            attempt = await _finish_attempt(
                runtime, number, question, reference_answer, metadata, solved, graded=not restart,
            )
            attempts.append(attempt)
            result = attempt if restart else _question_result(attempts)
            runtime.event("run.finished", "system", result,
                          [ids[-1] for ids in runtime.observed.values() if ids])
            runtime.db.record("run", result)
            (runtime.root / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        finally:
            runtime.close()
        if not restart:
            logger.info("Run finished (%s).", result["status"])
            return result
        logger.info("Fault injected; %s with faults off (attempt %d).",
                    f"replaying from {rollback[0]}" if rollback else "restarting", number + 1)
