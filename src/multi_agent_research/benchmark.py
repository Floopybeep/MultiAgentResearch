"""Sequential FRAMES execution with per-question results and batch summaries."""

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from .frames import DEFAULT_CORPUS, load_frames, prepare_documents, select_examples
from .observability.events import Redactor
from .observability.usage import sum_usage
from .runner import run_qa
from .viewer_export import atomic_write

logger = logging.getLogger(__name__)


def summarize(results):
    usage = [r["usage"] for r in results if "usage" in r]
    grades = [r["grade"] for r in results if r.get("grade")]
    return {
        "questions": len(results),
        "completed": sum(r.get("status") == "completed" for r in results),
        "correct": sum(g.get("correct") is True for g in grades),
        "incorrect": sum(g.get("correct") is False for g in grades),
        "ungraded": len(results) - sum(g.get("correct") is not None for g in grades),
        "input_tokens": sum(u["input_tokens"] for u in usage),
        "cached_input_tokens": (
            sum(u["cached_input_tokens"] for u in usage)
            if all(u["cached_input_tokens"] is not None for u in usage) else None
        ),
        "output_tokens": sum(u["output_tokens"] for u in usage),
        "total_tokens": sum(u["input_tokens"] + u["output_tokens"] for u in usage),
        "model_calls": sum(u["model_calls"] for u in usage),
        "unreported_calls": sum(u.get("unreported_calls", 0) for u in usage),
        "usage_complete": all(u.get("usage_complete", True) for u in usage),
        "estimated_cost_usd": (
            sum(u["estimated_cost_usd"] for u in usage)
            if usage and all(u["estimated_cost_usd"] is not None for u in usage) else None
        ),
        "solve_duration_seconds": sum(r.get("solve_duration_seconds", 0) for r in results),
        "grading_duration_seconds": sum(
            (a.get("grade") or {}).get("duration_seconds", 0)
            for r in results for a in r.get("attempts", [r])
        ),
        "elapsed_seconds": sum(r.get("elapsed_seconds", 0) for r in results),
        "verifier_usage": sum_usage(
            r["usage_by_role"]["verifier"] for r in results if "usage_by_role" in r
        ),
    }


async def run_frames(config, model, *, corpus_dir=DEFAULT_CORPUS, size=10, seed=42,
                     question_ids=None):
    examples, provenance, document_index = load_frames(corpus_dir)
    selected = select_examples(examples, size, seed, question_ids)
    timestamp = datetime.now(timezone.utc).strftime("%y%m%d_%H%M%S")
    batch_id = f"{timestamp}_{uuid4().hex}"
    path = config.output_dir / "batches" / f"{batch_id}.json"
    manifest = {
        "batch_id": batch_id, "dataset": provenance, "seed": seed,
        "question_ids": [e.question_id for e in selected], "results": [],
        "config": config.model_dump(mode="json"), "status": "running",
    }
    # Apply event redaction to the stored batch configuration and results.
    redact = Redactor().redact

    def save():
        manifest["summary"] = summarize(manifest["results"])
        atomic_write(path, json.dumps(redact(manifest), indent=2))

    started = time.monotonic()
    save()
    for index, example in enumerate(selected, 1):
        logger.info("[%d/%d] Question %s: starting (%d documents).",
                    index, len(selected), example.question_id, len(example.document_ids))
        preparation_started = time.monotonic()
        try:
            documents = prepare_documents(example, corpus_dir, document_index)
        except Exception as exc:
            logger.info("Question %s: document preparation failed (%s).",
                        example.question_id, type(exc).__name__)
            manifest["results"].append({
                "question_id": example.question_id, "status": "preparation_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "preparation_duration_seconds": time.monotonic() - preparation_started,
            })
            save()
            continue
        preparation_seconds = time.monotonic() - preparation_started
        result = await run_qa(
            example.question, config, model, documents, reference_answer=example.answer,
            metadata={
                "batch_id": batch_id, "question_id": example.question_id,
                "dataset": provenance, "reasoning_types": example.reasoning_types,
                "original_wikipedia_urls": example.original_wikipedia_urls,
            },
        )
        result["question_id"] = example.question_id
        result["preparation_duration_seconds"] = preparation_seconds
        manifest["results"].append(result)
        save()
        logger.info("[%d/%d] Question %s: %s (%.1fs).",
                    index, len(selected), example.question_id,
                    result["status"], result["duration_seconds"])
    manifest.update(status="finished", duration_seconds=time.monotonic() - started)
    save()
    return {"batch_path": str(path), **redact(manifest)}
