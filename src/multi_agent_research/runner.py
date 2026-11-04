"""One fresh QA attempt with local documents and an optional post-solve grade."""

import asyncio
import json
import time
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


async def run_qa(
    question: str, config: RunConfig, model: ModelAdapter, documents: OracleDocuments,
    *, reference_answer: str | None = None, metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # TODO: Input question/config/model/documents; add oracle-triggered restart and
    # always-verify dispatch. Output linked attempts, outcome and combined usage/time.
    if not question.strip():
        raise ValueError("Question cannot be empty")
    runtime = Runtime(
        config, model, documents,
        question_key=str((metadata or {}).get("question_id", question)),
    )
    started = time.monotonic()
    try:
        runtime.db.record("prompts", prompts.hashes(config))
        runtime.event("run.started", "lead", {
            "task_type": "frames_qa", "query": question, "metadata": metadata or {},
            "prompt_hashes": prompts.hashes(config),
        })
        snapshots = runtime.snapshot_documents()
        async with checkpoint_store(runtime.root / "checkpoints.sqlite") as saver:
            graph = build_research(runtime, saver)
            invocation_config = {
                "configurable": {"thread_id": runtime.run_id},
                "recursion_limit": 2 * config.max_lead_turns + 6,
            }
            try:
                state = await asyncio.wait_for(
                    graph.ainvoke({
                        "messages": [
                            SystemMessage(
                                content=prompts.render(
                                    prompts.load("lead", config.lead_prompt),
                                    runtime.prompt_context,
                                )
                                + f"\nLimits: {config.max_lead_turns} lead turns, "
                                f"{config.max_batches} batches, "
                                f"{config.max_workers_per_batch} workers per batch. "
                                f"Spawn at least {config.minimum_worker} workers in each delegation batch."
                            ),
                            HumanMessage(content=json.dumps({
                                "question": question, "available_documents": documents.catalog(),
                            })),
                        ],
                        "results": {}, "batches": 0, "turns": 0,
                    }, invocation_config),
                    config.run_timeout_seconds,
                )
            except Exception as exc:
                state = {
                    "status": "failed",
                    "stop_reason": f"{type(exc).__name__}: {runtime.log.redact(str(exc))}",
                }
                if isinstance(exc, TimeoutError):
                    state = {"status": "budget_exhausted", "stop_reason": "run_timeout"}
            snapshot = await graph.aget_state(invocation_config)
            # Retain completed work if the next node failed or the run timed out.
            if snapshot.values:
                state = {**snapshot.values, **state}
            checkpoint_id = (
                snapshot.config.get("configurable", {}).get("checkpoint_id")
                if snapshot.config else None
            )
        solve_seconds = time.monotonic() - started
        runtime.event("solve.finished", "system", {
            "status": state.get("status", "failed"), "duration_seconds": solve_seconds,
            "answer": state.get("answer"),
        }, [ids[-1] for ids in runtime.observed.values() if ids])
        grade = None
        if reference_answer is not None:
            # Record unanswered tasks with method='not_answered'.
            if state.get("answer"):
                grade = await grade_answer(runtime, question, reference_answer, state["answer"])
            else:
                grade = {
                    "method": "not_answered", "correct": False, "format_valid": False,
                    "exact_match": False, "extracted_answer": None,
                    "duration_seconds": 0, "usage": runtime.usage_by_role["judge"].as_dict(),
                }
                runtime.event("grade.finished", "judge", grade)
        # TODO: Input events, Worker deliveries and grade; add affected stages,
        # exposure/adoption/answer impact and wasted tokens/time to the result dict.
        result = dict(
            run_id=runtime.run_id, output_dir=str(runtime.root), task_type="frames_qa",
            reference_answer=reference_answer,
            question=question, metadata=metadata or {}, status=state.get("status", "failed"),
            stop_reason=state.get("stop_reason"), answer=state.get("answer"), grade=grade,
            worker_results=state.get("results", {}), usage=runtime.usage.as_dict(),
            usage_by_role={k: v.as_dict() for k, v in runtime.usage_by_role.items()},
            solve_duration_seconds=solve_seconds, duration_seconds=time.monotonic() - started,
            checkpoint_id=checkpoint_id,
        )
        if state.get("answer"):
            path = runtime.root / "answer.txt"
            path.write_text(runtime.log.redact(state["answer"]), encoding="utf-8")
            result["answer_path"] = str(path)
        result = runtime.log.redact(result)
        (runtime.root / "documents.json").write_text(
            json.dumps(runtime.log.redact(snapshots), indent=2), encoding="utf-8"
        )
        runtime.event(
            "run.finished", "system", result, [ids[-1] for ids in runtime.observed.values() if ids]
        )
        runtime.db.record("run", result)
        (runtime.root / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        runtime.close()
