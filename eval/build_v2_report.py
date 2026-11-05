#!/usr/bin/env python3
"""Screen the v2 baseline reps and derive the shared 10-question subset.

Offline: reads batch manifests, per-run SQLite event logs and stored artifacts.
Makes no API calls.

Worker counts and documents-read come from the event log rather than from a
worker's self-reported document_ids, because a worker can misreport what it
read. `worker.started` carries the assigned document_id under the
one-document-per-worker architecture, which is what makes redundant assignment
of a single document measurable.

Usage:
    python eval/build_v2_report.py runs/v2-base1 runs/v2-base2 runs/v2-base3 \
        --out eval/v2_screening_report.json --ids-out eval/shared_10_question_ids.txt
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from multi_agent_research.frames import load_frames, select_examples  # noqa: E402

META = {"event_id", "run_id", "attempt_id", "agent_id", "event_type",
        "timestamp", "payload_ref", "parent_event_ids"}


def manifest_of(target: Path) -> dict:
    if target.is_file():
        return json.loads(target.read_text())
    found = sorted((target / "batches").glob("*.json"))
    if not found:
        raise SystemExit(f"no batch manifest under {target}")
    if len(found) > 1:
        raise SystemExit(f"{target} holds {len(found)} manifests; pass one explicitly")
    return json.loads(found[0].read_text())


def run_dirs(target: Path) -> dict[str, Path]:
    """Map run_id -> run directory for every run under an output dir."""
    out = {}
    for child in target.iterdir():
        if child.is_dir() and (child / "events.sqlite").exists():
            out[child.name.split("_", 2)[-1]] = child
    return out


def events_of(run_dir: Path) -> list[dict]:
    db = run_dir / "events.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        bodies = [json.loads(b) for (b,) in con.execute("select body from events")]
    finally:
        con.close()
    return bodies


def payload_of(run_dir: Path, event: dict):
    ref = event.get("payload_ref")
    if not ref:
        return None
    path = run_dir / "artifacts" / f"{ref}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def topology(run_dir: Path) -> dict:
    """Workers spawned, their assigned documents, and documents actually read."""
    workers, assigned, read_ok, read_fail = [], {}, set(), 0
    for event in events_of(run_dir):
        kind = event.get("event_type")
        if kind == "worker.started":
            agent = event["agent_id"]
            workers.append(agent)
            body = payload_of(run_dir, event) or {}
            if isinstance(body, dict) and body.get("document_id"):
                assigned[agent] = body["document_id"]
        elif kind == "tool.result":
            body = payload_of(run_dir, event)
            if isinstance(body, dict) and "document_id" in body and "text" in body:
                read_ok.add(body["document_id"])
        elif kind == "tool.error":
            read_fail += 1

    counts = Counter(assigned.values())
    return {
        "workers_spawned": len(workers),
        "worker_agents": workers,
        "assigned_documents": assigned,
        "assigned_documents_recorded": bool(assigned),
        "distinct_documents_assigned": len(counts),
        "redundant_document_assignments": {d: n for d, n in counts.items() if n > 1},
        "distinct_documents_read": len(read_ok),
        "documents_read": sorted(read_ok),
        "tool_errors": read_fail,
    }


def health_of(target: Path) -> dict:
    """Per-rep endpoint health: error counts and the slowest model call.

    Reported so the effect of running reps concurrently stays visible: a rep's
    peak call duration is a property of the contention it ran under, not of the
    questions alone.
    """
    errors, timeouts, peak, peak_agent, peak_q = 0, 0, 0.0, None, None
    per_question = []
    if not target.is_dir():
        return {}
    for child in sorted(target.iterdir()):
        if not (child / "events.sqlite").exists():
            continue
        qid = None
        try:
            qid = json.loads((child / "run.json").read_text())["metadata"]["question_id"]
        except (OSError, KeyError, json.JSONDecodeError):
            pass
        q_err, q_peak = 0, 0.0
        for event in events_of(child):
            kind = event.get("event_type")
            if kind in ("model.error", "model.timeout"):
                q_err += 1
                if kind == "model.timeout":
                    timeouts += 1
            elif kind == "model.response":
                value = event.get("duration_seconds") or 0.0
                q_peak = max(q_peak, value)
                if value > peak:
                    peak, peak_agent, peak_q = value, event.get("agent_id"), qid
        errors += q_err
        per_question.append({"question_id": qid, "errors": q_err,
                             "max_model_response_seconds": round(q_peak, 2)})
    clean = [r for r in per_question if r["errors"] == 0]
    return {
        "model_error_events": errors,
        "model_timeout_events": timeouts,
        "max_model_response_seconds": round(peak, 2),
        "max_model_response_agent": peak_agent,
        "max_model_response_question": peak_q,
        "questions_with_errors": [r["question_id"] for r in per_question if r["errors"]],
        "max_among_error_free_questions": (
            round(max((r["max_model_response_seconds"] for r in clean), default=0.0), 2)
        ),
        "per_question": per_question,
    }


def load_rep(target: Path, label: str) -> dict:
    man = manifest_of(target)
    dirs = run_dirs(target) if target.is_dir() else {}
    questions = {}
    for result in man["results"]:
        qid = str(result["question_id"])
        grade = result.get("grade") or {}
        usage = result.get("usage") or {}
        entry = {
            "status": result.get("status"),
            "stop_reason": result.get("stop_reason"),
            "correct": grade.get("correct"),
            "method": grade.get("method"),
            "extracted_answer": grade.get("extracted_answer"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": (
                (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
                if usage else None
            ),
            "total_cost": result.get("total_cost"),
            "duration_seconds": result.get("duration_seconds"),
            "worker_results_reported": len(result.get("worker_results") or {}),
        }
        run_dir = dirs.get(result.get("run_id"))
        entry["run_dir"] = str(run_dir) if run_dir else None
        entry.update(topology(run_dir) if run_dir else {
            "workers_spawned": entry["worker_results_reported"],
            "assigned_documents_recorded": False,
            "distinct_documents_read": None,
            "redundant_document_assignments": {},
        })
        questions[qid] = entry
    return {
        "label": label, "target": str(target), "status": man.get("status"),
        "wall_seconds": man.get("duration_seconds"),
        "summary": man.get("summary"), "questions": questions,
        "health": health_of(target) if target.is_dir() else {},
    }


def pattern(values: list) -> str:
    return "".join("T" if v is True else "F" if v is False else "?" for v in values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reps", nargs="+", type=Path)
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--ids", type=Path, default=Path("eval/baseline_50_question_ids.txt"))
    parser.add_argument("--out", type=Path, default=Path("eval/v2_screening_report.json"))
    parser.add_argument("--ids-out", type=Path, default=Path("eval/shared_10_question_ids.txt"))
    parser.add_argument("--select", type=int, default=10)
    parser.add_argument("--prior", nargs="*", type=Path, default=[],
                        help="Old baseline dirs for the worker-count comparison")
    parser.add_argument("--evidence", type=Path, default=Path("eval/answer_evidence_50.json"),
                        help="Output of eval/locate_answer_evidence.py, for the cross-tab")
    parser.add_argument("--max-run-tokens", type=int, default=600000,
                        help="Run token budget, for the reported headroom flag")
    parser.add_argument("--inflation-factor", type=float, default=3.0,
                        help="Assumed token inflation under a fault, for the flag only")
    parser.add_argument("--max-document-chars", type=int, default=24000,
                        help="Page size, to report which page an offset falls in")
    args = parser.parse_args()

    evidence = {}
    if args.evidence and args.evidence.exists():
        evidence = {
            str(q["question_id"]): q
            for q in json.loads(args.evidence.read_text())["questions"]
        }

    ids = args.ids.read_text().split()
    examples, provenance, _ = load_frames(args.corpus_dir)
    catalog = {e.question_id: e for e in select_examples(examples, question_ids=ids)}

    reps = [load_rep(t, f"v2-rep{i}") for i, t in enumerate(args.reps, 1)]
    priors = [load_rep(t, t.name) for t in args.prior]

    rows = {}
    for qid in ids:
        per = [r["questions"].get(qid) for r in reps]
        example = catalog[qid]
        rows[qid] = {
            "question_id": qid,
            "catalog_document_count": len(example.document_ids),
            "catalog_document_ids": list(example.document_ids),
            "reference_answer": example.answer,
            "correct": [p["correct"] if p else None for p in per],
            "pattern": pattern([p["correct"] if p else None for p in per]),
            "status": [p["status"] if p else None for p in per],
            "stop_reason": [p["stop_reason"] if p else None for p in per],
            "grade_method": [p["method"] if p else None for p in per],
            "extracted_answer": [p["extracted_answer"] if p else None for p in per],
            "workers_spawned": [p["workers_spawned"] if p else None for p in per],
            "distinct_documents_read": [
                p["distinct_documents_read"] if p else None for p in per
            ],
            "redundant_document_assignments": [
                p.get("redundant_document_assignments") or {} if p else {} for p in per
            ],
            "total_tokens": [p["total_tokens"] if p else None for p in per],
            "total_cost": [p["total_cost"] if p else None for p in per],
            "duration_seconds": [p["duration_seconds"] if p else None for p in per],
            "tool_errors": [p.get("tool_errors") if p else None for p in per],
        }
        # Reported only. The judge shares the run token budget (grading.py:55 calls
        # runtime.call_model), so a token-hungry question can starve its own grading
        # and return correct:null. Any fault inflates usage, so thin headroom makes a
        # question fragile under ANY teammate's fault. This flag excludes nothing.
        seen_tokens = [t for t in rows[qid]["total_tokens"] if t is not None]
        peak = max(seen_tokens) if seen_tokens else None
        rows[qid]["max_total_tokens"] = peak
        rows[qid]["projected_tokens_under_fault"] = (
            int(peak * args.inflation_factor) if peak is not None else None
        )
        rows[qid]["token_headroom_at_risk"] = (
            peak is not None and peak * args.inflation_factor > args.max_run_tokens
        )

    # ---------------- Section 6: attrition ----------------
    funnel = []
    pool = list(ids)                       # noqa: F841 - kept for clarity
    step1 = [q for q in ids if all(s == "completed" for s in rows[q]["status"])]
    funnel.append({"step": 1, "criterion": "status == completed in all reps",
                   "surviving": len(step1), "dropped": len(ids) - len(step1),
                   "dropped_ids": [q for q in ids if q not in step1]})
    step2 = [q for q in step1 if all(c is True for c in rows[q]["correct"])]
    funnel.append({"step": 2, "criterion": "correct == true in all reps",
                   "surviving": len(step2), "dropped": len(step1) - len(step2),
                   "dropped_ids": [q for q in step1 if q not in step2]})
    step3 = [q for q in step2 if len(set(rows[q]["workers_spawned"])) == 1]
    funnel.append({"step": 3, "criterion": "worker count identical across reps",
                   "surviving": len(step3), "dropped": len(step2) - len(step3),
                   "dropped_ids": [q for q in step2 if q not in step3]})

    # Evidence classes are used only to describe the subset after it is fixed.
    CLASSES = ["localized", "derived", "weak_match", "ambiguous", "not_found"]

    def klass(qid: str) -> str:
        return (evidence.get(qid) or {}).get("classification", "unclassified")

    relaxed = False
    candidates = list(step3)
    if len(step3) < args.select:
        relaxed = True
        extra = [q for q in step2 if q not in step3]
        extra.sort(key=lambda q: max(rows[q]["workers_spawned"]) - min(rows[q]["workers_spawned"]))
        candidates = step3 + extra
        funnel.append({
            "step": "3-relaxed",
            "criterion": "step 3 relaxed: admitted worker-count-variant questions",
            "surviving": len(candidates),
            "admitted_with_variance": [
                {"question_id": q, "workers_spawned": rows[q]["workers_spawned"]}
                for q in extra[: max(0, args.select - len(step3))]
            ],
        })

    # ---- Step 4: proportional document-count representation; step 5: ID tiebreak ----
    # Quotas mirror the 50-question catalog-size distribution via the largest-remainder
    # (Hare quota) method. Ties in the remainder, and the pick within a size group, both
    # break on ascending numeric question ID, so the subset is reproducible.
    TIEBREAK = "ascending numeric question_id"

    population = Counter(rows[q]["catalog_document_count"] for q in ids)
    # Exact rationals, not floats: 17*10/50 is 3.3999... in binary, which would let
    # floating-point noise decide a tie that the documented rule says breaks on size.
    exact = {
        size: Fraction(count * args.select, len(ids))
        for size, count in population.items()
    }
    quota = {size: value.numerator // value.denominator for size, value in exact.items()}
    remaining = args.select - sum(quota.values())
    # Largest remainder; genuine ties break on ascending catalog size for determinism.
    order = sorted(exact, key=lambda s: (-(exact[s] - quota[s]), s))
    for size in order[:remaining]:
        quota[size] += 1

    available: dict[int, list[str]] = defaultdict(list)
    for q in candidates:
        available[rows[q]["catalog_document_count"]].append(q)
    for size in available:
        available[size].sort(key=int)

    chosen: list[str] = []
    for size in sorted(quota):
        take = min(quota[size], len(available[size]))
        chosen += available[size][:take]
        available[size] = available[size][take:]

    deficit = args.select - len(chosen)
    reallocated: list[str] = []
    if deficit > 0:
        # Sizes with survivors left, in the same largest-remainder order.
        surplus = [s for s in order if available.get(s)]
        while deficit > 0 and any(available.get(s) for s in surplus):
            progressed = False
            for size in surplus:
                if deficit <= 0:
                    break
                if available.get(size):
                    pick = available[size].pop(0)
                    chosen.append(pick)
                    reallocated.append(pick)
                    deficit -= 1
                    progressed = True
            if not progressed:
                break
    chosen.sort(key=int)

    achieved = Counter(rows[q]["catalog_document_count"] for q in chosen)
    representation = {
        "method": "largest remainder (Hare quota) over the 50-question distribution",
        "tiebreak": TIEBREAK,
        "population_distribution": dict(sorted(population.items())),
        "population_share": {
            s: round(c / len(ids), 4) for s, c in sorted(population.items())
        },
        "exact_quota_fractions": {
            s: f"{exact[s].numerator}/{exact[s].denominator}" for s in sorted(exact)
        },
        "target_quota": dict(sorted(quota.items())),
        "achieved": dict(sorted(achieved.items())),
        "survivors_available": {
            s: len([q for q in candidates if rows[q]["catalog_document_count"] == s])
            for s in sorted(population)
        },
        "skew": {
            s: achieved.get(s, 0) - quota.get(s, 0)
            for s in sorted(population) if achieved.get(s, 0) != quota.get(s, 0)
        },
        "reallocated_due_to_shortfall": reallocated,
    }

    # ---------------- Section 8: targeting table ----------------
    targeting = []
    for qid in chosen:
        record = evidence.get(qid) or {}
        ev = record.get("evidence") or {}
        entry = {
            "question_id": qid,
            "classification": record.get("classification", "unclassified"),
            "reference_answer": rows[qid]["reference_answer"],
            "catalog_document_ids": rows[qid]["catalog_document_ids"],
            "catalog_document_count": rows[qid]["catalog_document_count"],
            "bearer_document_id": record.get("answer_bearing_document"),
            "matched_literal": ev.get("literal"),
            "literal_specific": ev.get("specific"),
            "caveat": ev.get("caveat"),
            "offsets": ev.get("offsets"),
            "pages": (
                sorted({o // args.max_document_chars for o in ev["offsets"]})
                if ev.get("offsets") else None
            ),
            "page_size": args.max_document_chars,
        }
        if record.get("classification") == "derived":
            entry["derivation"] = ev.get("operation")
            entry["operands"] = ev.get("operands")
            entry["cross_document"] = ev.get("cross_document")
        targeting.append(entry)

    # --- Diagnostic only, computed after the subset is fixed: it must not feed back ---
    cross_tab = {
        "purpose": ("Post-hoc diagnostic. Evidence classification played no part in "
                    "selection; this only describes how targetable the chosen set "
                    "happens to be."),
        "rows": ["stable (passed criteria 1-3)", "not stable"],
        "columns": CLASSES, "table": {}, "totals": {},
    }
    if evidence:
        stable_set = set(step3)
        for label, members in (("stable (passed criteria 1-3)", stable_set),
                               ("not stable", set(ids) - stable_set)):
            counts = Counter(klass(q) for q in members)
            cross_tab["table"][label] = {c: counts.get(c, 0) for c in CLASSES}
            cross_tab["table"][label]["total"] = len(members)
        cross_tab["totals"] = {
            c: sum(cross_tab["table"][r].get(c, 0) for r in cross_tab["table"])
            for c in CLASSES
        }
        cross_tab["stable_by_class"] = {
            c: [q for q in step3 if klass(q) == c] for c in CLASSES
        }
        cross_tab["selected_by_class"] = {
            c: [q for q in chosen if klass(q) == c] for c in CLASSES
        }

    # ---- Four-bucket accuracy. Ungradeable is not incorrect, so it leaves the
    # gradeable denominator rather than counting against accuracy. ----
    def bucket(entry) -> str:
        if entry is None or entry.get("status") is None:
            return "missing"
        if entry["status"] != "completed":
            return "execution_failed"
        if entry["correct"] is True:
            return "correct"
        if entry["correct"] is False:
            return "incorrect"
        return "ungradeable"

    accuracy = []
    for index, rep in enumerate(reps):
        tally = Counter(bucket(rep["questions"].get(q)) for q in ids)
        attempted = len(ids)
        gradeable = (attempted - tally["execution_failed"] - tally["ungradeable"]
                     - tally["missing"])
        accuracy.append({
            "rep": rep["label"],
            "correct": tally["correct"],
            "incorrect": tally["incorrect"],
            "execution_failed": tally["execution_failed"],
            "ungradeable": tally["ungradeable"],
            # Nonzero only if a rep is incomplete; the four buckets must otherwise
            # reconcile to the attempted denominator.
            "missing": tally["missing"],
            "buckets_sum": (tally["correct"] + tally["incorrect"]
                            + tally["execution_failed"] + tally["ungradeable"]),
            "reconciles": (tally["correct"] + tally["incorrect"]
                           + tally["execution_failed"] + tally["ungradeable"]
                           + tally["missing"]) == len(ids),
            "rep_complete": tally["missing"] == 0,
            "attempted_denominator": attempted,
            "gradeable_denominator": gradeable,
            "accuracy_of_attempted": (
                f"{tally['correct']}/{attempted}" if attempted else None),
            "accuracy_of_attempted_pct": (
                round(100 * tally["correct"] / attempted, 1) if attempted else None),
            "accuracy_of_gradeable": (
                f"{tally['correct']}/{gradeable}" if gradeable else None),
            "accuracy_of_gradeable_pct": (
                round(100 * tally["correct"] / gradeable, 1) if gradeable else None),
            "ungradeable_ids": [
                q for q in ids if bucket(rep["questions"].get(q)) == "ungradeable"],
            "execution_failed_ids": [
                q for q in ids if bucket(rep["questions"].get(q)) == "execution_failed"],
            "wall_seconds": rep["wall_seconds"],
            "estimated_cost_usd": (rep["summary"] or {}).get("estimated_cost_usd"),
            "health": rep.get("health", {}),
        })

    headroom = {
        "rule": (f"flagged when max observed total tokens x {args.inflation_factor:g} "
                 f"> max_run_tokens ({args.max_run_tokens:,})"),
        "rationale": ("The judge shares the run token budget (grading.py:55 routes it "
                      "through runtime.call_model), so a token-hungry question can "
                      "starve its own grading and return correct:null, which is "
                      "indistinguishable from a fault-induced wrong answer. Reported "
                      "only; nothing is excluded on these grounds."),
        "flagged": [
            {
                "question_id": q,
                "max_total_tokens": rows[q]["max_total_tokens"],
                "projected_under_fault": rows[q]["projected_tokens_under_fault"],
                "per_rep_total_tokens": rows[q]["total_tokens"],
                "pattern": rows[q]["pattern"],
                "status": rows[q]["status"],
            }
            for q in ids if rows[q]["token_headroom_at_risk"]
        ],
        "ranked_by_peak_tokens": [
            {"question_id": q, "max_total_tokens": rows[q]["max_total_tokens"],
             "pattern": rows[q]["pattern"]}
            for q in sorted(
                (q for q in ids if rows[q]["max_total_tokens"] is not None),
                key=lambda q: -rows[q]["max_total_tokens"])[:8]
        ],
    }

    # ---- Execution failures, kept distinct from merely-incorrect answers ----
    # Doc-heavy: a catalog larger than max_workers_per_batch needs more than one
    # delegation batch under one-document-per-worker, so it consumes Lead turns
    # fastest. That is what makes lead_turn_limit and run_token_budget separable.
    DOC_HEAVY_THRESHOLD = 4
    failures, incorrect_only = [], []
    for qid in ids:
        row = rows[qid]
        heavy = row["catalog_document_count"] > DOC_HEAVY_THRESHOLD
        for index, status in enumerate(row["status"]):
            if status is not None and status != "completed":
                failures.append({
                    "question_id": qid,
                    "rep": reps[index]["label"],
                    "status": status,
                    "stop_reason": row["stop_reason"][index],
                    "catalog_document_count": row["catalog_document_count"],
                    "doc_heavy": heavy,
                    "workers_spawned": row["workers_spawned"][index],
                    "distinct_documents_read": row["distinct_documents_read"][index],
                    "total_tokens": row["total_tokens"][index],
                })
            elif status == "completed" and row["correct"][index] is not True:
                incorrect_only.append({
                    "question_id": qid, "rep": reps[index]["label"],
                    "correct": row["correct"][index],
                    "grade_method": row["grade_method"][index],
                    "catalog_document_count": row["catalog_document_count"],
                    "doc_heavy": heavy,
                })

    failure_report = {
        "definition": ("An execution failure is status != completed. A completed run "
                       "with a wrong answer is not a failure and is listed separately."),
        "doc_heavy_threshold": (f"catalog_document_count > {DOC_HEAVY_THRESHOLD} "
                                f"(= max_workers_per_batch, so >1 batch is forced)"),
        "count": len(failures),
        "by_stop_reason": dict(sorted(Counter(
            f["stop_reason"] for f in failures).items())),
        "by_stop_reason_doc_heavy": dict(sorted(Counter(
            f["stop_reason"] for f in failures if f["doc_heavy"]).items())),
        "doc_heavy_share": (
            f"{sum(1 for f in failures if f['doc_heavy'])}/{len(failures)}"
            if failures else "0/0"
        ),
        "failures": failures,
        "completed_but_incorrect_count": len(incorrect_only),
        "completed_but_incorrect": incorrect_only,
    }

    # ---------------- Section 7.1: worker-count effect ----------------
    comparison = []
    if priors:
        for qid in ids:
            new = rows[qid]["workers_spawned"]
            old = [p["questions"].get(qid, {}).get("workers_spawned") for p in priors]
            comparison.append({
                "question_id": qid,
                "catalog_document_count": rows[qid]["catalog_document_count"],
                "prior_workers": old,
                "v2_workers": new,
                "changed": set(x for x in old if x is not None) != set(
                    x for x in new if x is not None),
                "v2_redundant": [
                    d for r in rows[qid]["redundant_document_assignments"] for d in r
                ],
            })

    report = {
        "provenance": {
            "dataset": provenance,
            "reps": [{"label": r["label"], "target": r["target"], "status": r["status"],
                      "wall_seconds": r["wall_seconds"], "summary": r["summary"]}
                     for r in reps],
            "question_ids": ids,
            "minimum_worker": 2,
            "note": ("Screening is performed at minimum_worker: 2, which the team has "
                     "agreed to use on all branches; upstream main still carries 3."),
        },
        "questions": rows,
        "accuracy": accuracy,
        "token_headroom": headroom,
        "attrition": funnel,
        "selection": {
            "selected": chosen,
            "count": len(chosen),
            "relaxed_step3": relaxed,
            "criteria": [
                "status == completed in all 3 reps",
                "correct == true in all 3 reps",
                "worker count identical across all 3 reps",
                "proportional catalog-document-count representation",
                f"deterministic tiebreak: {TIEBREAK}",
            ],
            "fault_agnostic": ("Answer-evidence localization played no part in "
                               "selection."),
            "representation": representation,
        },
        "concurrency_caveat": {
            "scheduling": ("Reps were not run strictly sequentially: rep 2 was launched "
                           "while rep 1 was still finishing, and rep 3 while rep 2 was "
                           "still finishing. At most two reps ran at once."),
            "effect_on_guard": ("A rep's peak model.response duration reflects the "
                                "contention it ran under. Peaks per rep are recorded "
                                "under accuracy[].health so this is visible."),
            "q694": ("Q694 failed in rep 1 with stop_reason=lead_turn_limit and in "
                     "rep 2 with ModelCallTimeout (lead, limit 60s). These are NOT a "
                     "single clean architectural finding. Q694 has the largest catalog "
                     "in the set, so it spawns the most workers and its Lead prompt "
                     "carries the most worker reports, making its Lead calls the "
                     "slowest regardless of load. The 60s crossing in rep 2 is partly "
                     "an artifact of the decision to parallelize reps, not evidence "
                     "that the architecture alone exceeds the call timeout."),
            "scope_checked": ("In rep 2 every model.error and every call above 45s was "
                              "confined to Q694's run; all other questions showed no "
                              "errors and no call above 29.59s. Nothing affecting "
                              "selection was touched, and Q694 fails criterion 1 in "
                              "rep 1 independently."),
        },
        "execution_failures": failure_report,
        "stability_by_evidence": cross_tab,
        "targeting": targeting,
        "worker_count_comparison": comparison,
    }

    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    # ---------------- readable summary ----------------
    print("=== per-question results across reps ===")
    header = (f"{'Q':>5} {'docs':>4} {'pat':>4} {'workers':>12} {'docsread':>12} "
              f"{'tokens':>24} {'peak':>8} {'3x>budget':>10} status")
    print(header)
    print("-" * len(header))
    for qid in ids:
        r = rows[qid]
        print(f"{qid:>5} {r['catalog_document_count']:>4} {r['pattern']:>4} "
              f"{str(r['workers_spawned']):>12} {str(r['distinct_documents_read']):>12} "
              f"{str(r['total_tokens']):>24} "
              f"{(r['max_total_tokens'] or 0):>8,} "
              f"{('FLAG' if r['token_headroom_at_risk'] else ''):>10} "
              f"{','.join(str(s) for s in r['status'])}")
    print()
    print("=== attrition ===")
    for step in funnel:
        print(f"  step {step['step']}: {step['criterion']}")
        print(f"     surviving={step['surviving']}"
              + (f" dropped={step['dropped']}" if "dropped" in step else ""))
        if step.get("dropped_ids"):
            print(f"     dropped_ids={step['dropped_ids']}")
    print()
    print("=== accuracy with explicit denominators (4 buckets) ===")
    head = (f"  {'rep':<10} {'corr':>5} {'incorr':>7} {'exec-fail':>10} "
            f"{'ungrade':>8} {'sum':>5} {'of attempted':>14} {'of gradeable':>14}")
    print(head)
    print("  " + "-" * (len(head) - 2))
    for a in accuracy:
        attempted = f"{a['accuracy_of_attempted']} ({a['accuracy_of_attempted_pct']}%)"
        gradeable = f"{a['accuracy_of_gradeable']} ({a['accuracy_of_gradeable_pct']}%)"
        print(f"  {a['rep']:<10} {a['correct']:>5} {a['incorrect']:>7} "
              f"{a['execution_failed']:>10} {a['ungradeable']:>8} {a['buckets_sum']:>5} "
              f"{attempted:>14} {gradeable:>14}"
              + ("" if a["rep_complete"]
                 else f"   INCOMPLETE: {a['missing']} question(s) missing"))
    print()
    print("  endpoint health per rep (concurrency effect visible here):")
    for a in accuracy:
        h = a.get("health") or {}
        if h:
            print(f"    {a['rep']:<10} model.error={h.get('model_error_events', 0):<3} "
                  f"timeouts={h.get('model_timeout_events', 0):<3} "
                  f"max_call={h.get('max_model_response_seconds', 0):>6.2f}s "
                  f"(agent={h.get('max_model_response_agent')}, "
                  f"Q{h.get('max_model_response_question')})  "
                  f"max_among_error_free_questions="
                  f"{h.get('max_among_error_free_questions', 0):>6.2f}s")
            if h.get("questions_with_errors"):
                print(f"               questions with errors: "
                      f"{h['questions_with_errors']}")
    print()
    for a in accuracy:
        if a["ungradeable_ids"] or a["execution_failed_ids"]:
            print(f"  {a['rep']}: ungradeable={a['ungradeable_ids']} "
                  f"exec_failed={a['execution_failed_ids']}")
    print("  Ungradeable is NOT incorrect: it leaves the gradeable denominator.")

    print()
    print("=== token headroom (REPORTED ONLY - nothing excluded) ===")
    print(f"  {headroom['rule']}")
    if headroom["flagged"]:
        print(f"  {len(headroom['flagged'])} question(s) flagged:")
        for f in headroom["flagged"]:
            print(f"    Q{f['question_id']:<5} peak={f['max_total_tokens']:>8,} "
                  f"projected={f['projected_under_fault']:>9,} "
                  f"pattern={f['pattern']} status={f['status']}")
    else:
        print("  none flagged")
    print("  highest peak-token questions:")
    for r_ in headroom["ranked_by_peak_tokens"]:
        print(f"    Q{r_['question_id']:<5} {r_['max_total_tokens']:>8,}  "
              f"pattern={r_['pattern']}")

    print()
    print("=== execution failures (status != completed) ===")
    print(f"  {failure_report['doc_heavy_threshold']}")
    if failures:
        print(f"  {len(failures)} failure(s); doc-heavy share "
              f"{failure_report['doc_heavy_share']}")
        print(f"  by stop_reason: {failure_report['by_stop_reason']}")
        if failure_report["by_stop_reason_doc_heavy"]:
            print(f"  by stop_reason, doc-heavy only: "
                  f"{failure_report['by_stop_reason_doc_heavy']}")
        head = (f"  {'Q':>5} {'rep':<10} {'docs':>4} {'heavy':>5} {'status':<18} "
                f"{'stop_reason':<22} {'workers':>7} {'tokens':>9}")
        print(head)
        print("  " + "-" * (len(head) - 2))
        for f in failures:
            print(f"  {f['question_id']:>5} {f['rep']:<10} "
                  f"{f['catalog_document_count']:>4} {str(f['doc_heavy']):>5} "
                  f"{str(f['status']):<18} {str(f['stop_reason']):<22} "
                  f"{str(f['workers_spawned']):>7} {str(f['total_tokens']):>9}")
    else:
        print("  none")
    print(f"  completed but incorrect (NOT failures): "
          f"{failure_report['completed_but_incorrect_count']}")

    print()
    print("=== step 4: proportional representation by catalog document count ===")
    rep = representation
    print(f"  method: {rep['method']}")
    print(f"  tiebreak: {rep['tiebreak']}")
    head = f"  {'docs':>5} {'in 50':>7} {'share':>8} {'quota':>7} {'avail':>7} {'chosen':>7}"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for size in sorted(rep["population_distribution"]):
        print(f"  {size:>5} {rep['population_distribution'][size]:>7} "
              f"{rep['population_share'][size]:>8.2%} {rep['target_quota'].get(size, 0):>7} "
              f"{rep['survivors_available'].get(size, 0):>7} "
              f"{rep['achieved'].get(size, 0):>7}")
    if rep["skew"]:
        print(f"  SKEW vs quota (stability preferred over proportionality): {rep['skew']}")
        if rep["reallocated_due_to_shortfall"]:
            print(f"  reallocated into surplus sizes: "
                  f"{rep['reallocated_due_to_shortfall']}")
    else:
        print("  no skew: achieved distribution matches the proportional quota")

    print()
    print(f"=== selected {len(chosen)} (fault-agnostic) ===")
    print("  ids:", " ".join(chosen))
    print("  catalog-size spread:", rep["achieved"])
    if relaxed:
        print("  NOTE: step 3 was relaxed; see attrition entry '3-relaxed'")

    if cross_tab.get("table"):
        print()
        print("=== DIAGNOSTIC (post-hoc): stability x evidence class ===")
        print("  Evidence classification did NOT influence selection.")
        head = f"  {'':<30}" + "".join(f"{c:>12}" for c in CLASSES) + f"{'total':>8}"
        print(head)
        print("  " + "-" * (len(head) - 2))
        for label in cross_tab["rows"]:
            cell = cross_tab["table"][label]
            print(f"  {label:<30}" + "".join(f"{cell.get(c, 0):>12}" for c in CLASSES)
                  + f"{cell.get('total', 0):>8}")
        print("  " + "-" * (len(head) - 2))
        print(f"  {'column totals':<30}"
              + "".join(f"{cross_tab['totals'].get(c, 0):>12}" for c in CLASSES)
              + f"{len(ids):>8}")
        print()
        print("  evidence classes among the chosen 10:")
        for c in CLASSES:
            members = cross_tab["selected_by_class"].get(c) or []
            print(f"    {c:<12} {len(members):>2}  {members}")

    if targeting:
        print()
        print("=== section 8: targeting table ===")
        head = (f"{'Q':>5} {'class':<11} {'bearer':<10} {'pages':<8} "
                f"{'offsets':<20} {'literal':<34} catalog")
        print(head)
        print("-" * len(head))
        for t in targeting:
            lit = t["matched_literal"] or (t.get("derivation") or "-")
            print(f"{t['question_id']:>5} {t['classification']:<11} "
                  f"{str(t['bearer_document_id'] or '-'):<10} "
                  f"{str(t['pages'] if t['pages'] is not None else '-'):<8} "
                  f"{str(t['offsets'][:3] if t['offsets'] else '-'):<20} "
                  f"{lit[:33]:<34} {','.join(t['catalog_document_ids'])}")

    if chosen:
        args.ids_out.write_text(" ".join(chosen) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}\nwrote {args.ids_out}")
    else:
        print(f"\nwrote {args.out}\nNO ids written: nothing survived selection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
