"""One QA run: solve, grade and write the final files."""

import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from . import prompts
from .config import RunConfig
from .grading import grade_answer
from .graphs.research import build_research
from .models.adapter import ModelAdapter
from .runtime import Runtime
from .storage.checkpoints import checkpoint_store
from .tools.documents import OracleDocuments

logger = logging.getLogger(__name__)


async def _solve(
    runtime: Runtime, question: str, reference_answer: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    config = runtime.config
    started = time.monotonic()
    prompt_hashes = prompts.hashes(config)
    runtime.db.record("prompts", prompt_hashes)
    runtime.event("run.started", "lead", {
        "task_type": "frames_qa", "query": question, "metadata": metadata or {},
        "prompt_hashes": prompt_hashes,
    })
    snapshots = runtime.snapshot_documents()
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
    if reference_answer is not None:
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
        config=config.model_dump(mode="json"),
        reference_answer=reference_answer, question=question, metadata=metadata or {},
        status=state.get("status", "failed"), stop_reason=state.get("stop_reason"),
        answer=state.get("answer"), grade=grade, correct=grade.get("correct") if grade else None,
        worker_results=state.get("results", {}),
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
    question_root: Path | None = None,
) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("Question cannot be empty")
    runtime = Runtime(
        config, model, documents,
        root=question_root / "attempt-1" if question_root else None,
        viewer_root=config.output_dir if question_root else None,
    )
    try:
        result = await _solve(runtime, question, reference_answer, metadata)
        runtime.event("run.finished", "system", result,
                      [ids[-1] for ids in runtime.observed.values() if ids])
        runtime.db.record("run", result)
        (runtime.root / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        runtime.close()
    logger.info("Run finished (%s).", result["status"])
    return result
