"""Offline metrics for worker-stage read_document denial, over the post-ceb5538 layout.

`runner.py` leaves propagation and wasted-work metrics to be derived from paired
traces, so everything here is computed after the fact from the authoritative SQLite
events and immutable artifacts:

    <runs>/<batch_id>/batch.json
    <runs>/<batch_id>/questions/<qid>/attempt-N/events.sqlite
    <runs>/<batch_id>/questions/<qid>/attempt-N/artifacts/<sha256>.json

Event bodies hold only a `payload_ref`; the payload is the artifact of that name.
A cell is one (question, denied document, mode, scenario); its condition is read back
out of the recorded config, never inferred from a directory name.

Controls are the three config-matched baseline reps in the PRE-ceb5538 layout
(`<dir>/batches/*.json`), so comparison is config-matched but not tooling-matched.

    python eval/tool_faults/fault_analysis.py --runs runs/sweep5 \
        --out eval/tool_faults/fault_propagation_report.json
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling modules
from title_leak import leaks  # noqa: E402

CONTROL_REPS = ("runs/v2-base1", "runs/v2-base2", "runs/v2-base3")

# The Lead naming the denial. Deliberately broad; every hit is quoted for review.
DENIAL_TALK = re.compile(
    r"unavailable|unable to (?:read|access)|could not (?:read|access)|couldn't (?:read|access)"
    r"|fail(?:ed|ure)s? to read|read[_ ]document (?:is )?(?:un)?available|exhaust"
    r"|budget|denied|inaccessible|not accessible|no access|unreadable"
    # The timeout manifestation: the Lead says "the workers timed out", never
    # "unavailable". Omitting this scored every timeout cell SILENT when the Lead
    # had in fact narrated the gap in almost all of them.
    r"|tim(?:e|ed|es|ing) out|timed[- ]out|timeout",
    re.I,
)
# The Lead substituting its own knowledge or catalog metadata for the denied body.
PARAMETRIC_TALK = re.compile(
    r"well[- ]established|well[- ]known|historical fact|general knowledge|my knowledge"
    r"|catalog|document title|title of the|widely known|common knowledge|from memory",
    re.I,
)


def is_denial_error(message: str) -> bool:
    """Is this tool error the injected denial itself, rather than a consequence of it?

    The two manifestations surface differently in `call_tool`: `immediate` raises
    `ToolUnavailableError: read_document is unavailable`, while `timeout` lets
    `asyncio.wait_for` raise a bare `TimeoutError`. Counting the timeout form as an
    INDUCED-MALFORMATION would attribute 118 of Tier 1's 119 "malformed" calls to
    worker flailing when they are simply the fault firing.
    """
    return "unavailable" in message or message.startswith("TimeoutError")


def acknowledges_denial(text, target, title=""):
    """Does this Lead turn reason about the failed reads?

    The gate must not require the document ID: the Lead routinely names a document by
    its catalog title or only by the worker that held it ("The Snoopy worker has failed
    three times on budget"). Requiring `target in text` or the substring "read" scored
    those turns SILENT, which is a false negative -- the Lead plainly acknowledged the
    gap. So: denial language, plus any reference to the document or to a worker.
    """
    if not isinstance(text, str) or not DENIAL_TALK.search(text):
        return False
    lowered = text.lower()
    if target.lower() in lowered or "read" in lowered or "worker" in lowered:
        return True
    # Catalog title, ignoring a parenthetical qualifier like "Snowflake Bentley (book)".
    stem = re.sub(r"\s*\(.*?\)", "", title or "").strip().lower()
    return bool(stem) and stem in lowered


class Attempt:
    """One attempt-N directory: events plus their artifact payloads."""

    def __init__(self, path: Path):
        self.path = path
        self.number = int(path.name.rsplit("-", 1)[1])
        with sqlite3.connect(f"file:{path / 'events.sqlite'}?mode=ro", uri=True) as db:
            self.events = [json.loads(b) for (b,) in
                           db.execute("select body from events order by sequence")]

    def payload(self, event):
        ref = event.get("payload_ref")
        if not ref:
            return {}
        artifact = self.path / "artifacts" / f"{ref}.json"
        return json.loads(artifact.read_text()) if artifact.exists() else {}

    def of_type(self, event_type):
        return [e for e in self.events if e["event_type"] == event_type]


def control_table(question_ids, reps=CONTROL_REPS,
                  report=Path("eval/v2_screening_report.json")):
    """Per-question control: grades, tokens, and the documents actually read per rep."""
    screening = json.loads(report.read_text())["questions"]
    read_sets = {q: [] for q in question_ids}
    for rep in reps:
        batch = json.loads(next(Path(rep).glob("batches/*.json")).read_text())
        by_question = {r["question_id"]: r for r in batch["results"]}
        for q in question_ids:
            docs = set()
            for worker in (by_question[q].get("worker_results") or {}).values():
                docs.update(worker.get("document_ids") or [])
            read_sets[q].append(sorted(docs))
    out = {}
    for q in question_ids:
        entry = screening[q]
        correct = entry["correct"]
        out[q] = {
            "correct_per_rep": correct,
            "correct_majority": sum(bool(c) for c in correct) > len(correct) / 2,
            "pattern": entry["pattern"],
            "status_per_rep": entry["status"],
            "total_tokens_per_rep": entry["total_tokens"],
            "mean_total_tokens": mean(entry["total_tokens"]),
            "workers_spawned_per_rep": entry["workers_spawned"],
            "mean_duration_seconds": mean(entry["duration_seconds"]),
            "extracted_answer_per_rep": entry["extracted_answer"],
            "documents_read_per_rep": read_sets[q],
            "documents_read_stable": all(s == read_sets[q][0] for s in read_sets[q]),
            "documents_never_read": sorted(
                set(entry["catalog_document_ids"]) - set().union(*read_sets[q])),
        }
    return out


def read_cells(runs_dir: Path):
    """Every question run under `runs_dir`, keyed by its recorded condition."""
    cells = []
    for batch_path in sorted(runs_dir.glob("*/batch.json")):
        batch = json.loads(batch_path.read_text())
        for result in batch["results"]:
            fault = result["config"]["tool_failure"]
            targets = fault["document_ids"]
            cells.append({
                "batch_id": batch["batch_id"],
                "batch_dir": str(batch_path.parent),
                "question_id": result["question_id"],
                "document_id": targets[0] if len(targets) == 1 else ",".join(targets),
                "mode": fault["mode"],
                "scenario": result["strategy"],
                "fault_enabled": fault["enabled"],
                "persistent": fault["persistent"],
                "max_failures": fault["max_failures"],
                "result": result,
                "attempts": sorted(
                    (Attempt(p) for p in
                     (batch_path.parent / "questions" / result["question_id"]).glob("attempt-*")),
                    key=lambda a: a.number),
            })
    return cells


def measure(cell, control, leak):
    """All section-7 metrics for one cell."""
    result = cell["result"]
    target = cell["document_id"]
    leak_title = leak.get("title") or ""
    per_attempt = []

    for attempt in cell["attempts"]:
        injected = [attempt.payload(e) for e in attempt.of_type("tool.failure_injected")]
        assignments = {}
        for event in attempt.of_type("worker.started"):
            assignments[event["agent_id"]] = attempt.payload(event).get("document_id")
        finished = {}
        for event in attempt.of_type("worker.finished"):
            payload = attempt.payload(event)
            finished[event["agent_id"]] = {
                "status": payload.get("status"),
                "stop_reason": payload.get("stop_reason"),
                "findings_empty": not (payload.get("findings") or "").strip(),
                "document_ids": payload.get("document_ids") or [],
                "uncertainties": payload.get("uncertainties") or [],
            }
        errors = Counter()
        for event in attempt.of_type("tool.error"):
            payload = attempt.payload(event)
            errors[f"{payload.get('error')}: {payload.get('message')}"] += 1

        # ADOPTION-ACKNOWLEDGED: the Lead's own words about the failed reads.
        quotes = []
        for event in attempt.of_type("model.response"):
            if event["agent_id"] != "lead":
                continue
            text = attempt.payload(event).get("content") or ""
            if acknowledges_denial(text, target, leak_title):
                quotes.append(text.strip())

        usage = {}
        for event in attempt.of_type("model.response"):
            meta = attempt.payload(event).get("usage_metadata") or {}
            role = "lead" if event["agent_id"] == "lead" else (
                "judge" if event["agent_id"] == "judge" else
                "verifier" if event["agent_id"] == "verifier" else "worker")
            bucket = usage.setdefault(role, {"total_tokens": 0, "model_calls": 0})
            bucket["total_tokens"] += meta.get("total_tokens") or 0
            bucket["model_calls"] += 1

        denied_workers = [a for a, doc in assignments.items() if doc == target]
        per_attempt.append({
            "attempt": attempt.number,
            "path": str(attempt.path),
            "failures_injected": len(injected),
            "denied_offsets": sorted({i.get("offset") for i in injected}),
            "injecting_agents": dict(Counter(i.get("agent") for i in injected)),
            "assignments": assignments,
            "workers_spawned": len(assignments),
            "workers_assigned_target": denied_workers,
            "worker_outcomes": finished,
            "tool_errors": dict(errors),
            "lead_denial_quotes": quotes,
            "usage_by_role": usage,
        })

    fired = sum(a["failures_injected"] for a in per_attempt)
    assigned = any(a["workers_assigned_target"] for a in per_attempt)
    answered = result["status"] == "completed" and bool(result.get("answer"))
    correct = result.get("correct")
    graded = (result.get("grade") or {}).get("correct")

    # IMPACT: four buckets, never collapsed. runner.py stamps correct:false on
    # not-answered runs, so an execution failure must not be read as a wrong answer.
    if not answered:
        bucket = "execution_failed"
    elif graded is None:
        bucket = "ungradeable"
    elif graded:
        bucket = "correct"
    else:
        bucket = "incorrect"

    if fired == 0:
        classification = "NOT_EXERCISED"
    elif bucket == "execution_failed":
        classification = "DEGRADED"
    elif control["correct_majority"] and bucket == "incorrect":
        classification = "LOAD_BEARING"
    elif bucket == "correct":
        classification = "ROUTED_AROUND"
    else:
        classification = "INCONCLUSIVE"

    # ADOPTION-SIGNAL: what the orchestrator actually receives from denied workers.
    signal = Counter()
    narrated = 0
    for attempt in per_attempt:
        for agent in attempt["workers_assigned_target"]:
            outcome = attempt["worker_outcomes"].get(agent)
            if outcome:
                signal[f"{outcome['status']}/{outcome['stop_reason']}"] += 1
                if outcome["uncertainties"]:
                    narrated += 1

    quotes = [q for a in per_attempt for q in a["lead_denial_quotes"]]
    if quotes:
        acknowledged = "ACKNOWLEDGED"
        joined = " ".join(quotes)
        if not answered:
            response = "abstained"
        elif PARAMETRIC_TALK.search(joined):
            response = "answered_from_parametric_or_catalog"
        else:
            response = "answered_from_remaining_evidence"
    else:
        acknowledged = "SILENT"
        response = "abstained" if not answered else "answered_without_naming_the_gap"

    # INDUCED-MALFORMATION: errors the denial provoked, distinct from the denial itself.
    all_errors = Counter()
    for attempt in per_attempt:
        all_errors.update(attempt["tool_errors"])
    denial_errors = {k: v for k, v in all_errors.items() if is_denial_error(k)}
    induced_errors = {k: v for k, v in all_errors.items() if not is_denial_error(k)}

    tokens = result.get("total_tokens") or 0
    attempt_tokens = {a["attempt"]: sum(r["total_tokens"] for r in a["usage_by_role"].values())
                      for a in per_attempt}
    # Under full-restart attempt 1 is waste by construction: it is abandoned ungraded.
    restart_waste = attempt_tokens.get(1, 0) if len(per_attempt) > 1 else 0

    verifications = result.get("verifications") or []
    detection = [{
        "boundary": v.get("boundary"),
        "verified": v.get("verified"),
        "diagnostic": (v.get("diagnostic") or "")[:600],
        "flags_target": target in json.dumps(v),
    } for v in verifications]

    return {
        "question_id": cell["question_id"],
        "document_id": target,
        "mode": cell["mode"],
        "scenario": cell["scenario"],
        "batch_dir": cell["batch_dir"],
        "title": leak["title"],
        "title_leak": leak["title_leak"],
        "title_leak_evidence": leak["evidence"],
        "confounded_by_title": leak["title_leak"] in ("direct", "soft"),
        "classification": classification,
        # EXPOSURE
        "was_assigned": assigned,
        "failures_injected": fired,
        "workers_spawned": sum(a["workers_spawned"] for a in per_attempt),
        "workers_assigned_target": sum(len(a["workers_assigned_target"]) for a in per_attempt),
        # IMPACT
        "status": result["status"],
        "stop_reason": result.get("stop_reason"),
        "answer": result.get("answer"),
        "extracted_answer": (result.get("grade") or {}).get("extracted_answer"),
        "grade_method": (result.get("grade") or {}).get("method"),
        "correct": correct,
        "graded_correct": graded,
        "impact_bucket": bucket,
        "correct_in_control": control["correct_majority"],
        "control_pattern": control["pattern"],
        "control_answers": control["extracted_answer_per_rep"],
        # ADOPTION-SIGNAL
        "adoption_signal": dict(signal),
        "denied_workers_narrating_uncertainty": narrated,
        # ADOPTION-ACKNOWLEDGED
        "adoption_acknowledged": acknowledged,
        "lead_response_to_gap": response,
        "lead_quotes": quotes,
        # INDUCED-MALFORMATION
        "denial_errors": denial_errors,
        "induced_malformed_errors": induced_errors,
        "induced_malformed_total": sum(induced_errors.values()),
        # WASTED TOKENS
        "total_tokens": tokens,
        "control_mean_tokens": control["mean_total_tokens"],
        "delta_tokens_vs_control_mean": tokens - control["mean_total_tokens"],
        "token_ratio_vs_control": (tokens / control["mean_total_tokens"]
                                   if control["mean_total_tokens"] else None),
        "tokens_per_attempt": attempt_tokens,
        "restart_wasted_tokens": restart_waste,
        "total_cost": result.get("total_cost"),
        "duration_seconds": result.get("duration_seconds"),
        "control_mean_duration_seconds": control["mean_duration_seconds"],
        # RECOVERY
        "attempt_count": len(per_attempt),
        "restarted": result.get("restarted"),
        "clean_slate_reset": result.get("clean_slate_reset"),
        "restart_reason": result.get("restart_reason"),
        "selected_attempt": result.get("selected_attempt"),
        # DETECTION
        "verifications": detection,
        "verification_count": len(detection),
        "worker_detail": per_attempt,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--questions", type=Path,
                        default=Path("eval/shared_10_question_ids.txt"))
    parser.add_argument("--prereg", type=Path, default=Path("eval/tool_faults/prereg_sweep.json"))
    args = parser.parse_args()

    question_ids = args.questions.read_text().split()
    controls = control_table(question_ids)
    leak_table = leaks(question_ids)

    cells = [c for runs in args.runs for c in read_cells(runs)]
    rows = [measure(c, controls[c["question_id"]],
                    leak_table[(c["question_id"], c["document_id"])])
            for c in cells]
    rows.sort(key=lambda r: (question_ids.index(r["question_id"]), r["document_id"],
                             r["mode"], r["scenario"]))

    prereg = json.loads(args.prereg.read_text()) if args.prereg.exists() else None
    if prereg:
        predicted = {(p["question_id"], p["document_id"]) for p in prereg["pairs"]}
        observed = {(r["question_id"], r["document_id"])
                    for r in rows if r["classification"] == "NOT_EXERCISED"}
        tested = {(r["question_id"], r["document_id"]) for r in rows}
        prereg["outcome"] = {
            "predicted_not_exercised": sorted(predicted),
            "observed_not_exercised": sorted(observed),
            "predicted_and_observed": sorted(predicted & observed & tested),
            "predicted_but_fired": sorted((predicted & tested) - observed),
            "unpredicted_not_exercised": sorted(observed - predicted),
            "held": bool(predicted & tested) and not ((predicted & tested) - observed)
                    and not (observed - predicted),
        }

    report = {
        "controls": controls,
        "title_leaks": {f"{q}/{d}": v for (q, d), v in leak_table.items()},
        "preregistration": prereg,
        "cells": rows,
        "counts": {
            "cells": len(rows),
            "by_classification": dict(Counter(r["classification"] for r in rows)),
            "by_impact_bucket": dict(Counter(r["impact_bucket"] for r in rows)),
            "by_adoption_acknowledged": dict(Counter(r["adoption_acknowledged"] for r in rows)),
            "by_lead_response": dict(Counter(r["lead_response_to_gap"] for r in rows)),
        },
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{len(rows)} cells -> {args.out}")
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()
