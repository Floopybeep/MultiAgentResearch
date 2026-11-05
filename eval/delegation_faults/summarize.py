"""Summarize delegation-fault recovery experiments (connection_drop, result_timeout).

Reads the batch manifests written by `mar` (``<output-dir>/batches/*.json``) and each
attempt's ``events.sqlite``. Every result is labelled by its fault (from the recorded
base config) and recovery strategy (baseline = no recovery, full-restart, always-verify),
so the output directories can be named freely. See eval/delegation_faults/README.md.

Usage:
    uv run python eval/delegation_faults/summarize.py runs/exp/drop_* runs/exp/timeout_* \
        --reference-report eval/v2_screening_report.json \
        --csv runs/exp/summary.csv --md runs/exp/summary.md

Comparisons (`--compare-to`):
    no-recovery (default)  each recovery run vs the same fault's no-recovery run on the
                           same question
    clean                  each fault run vs the clean reference

Clean reference (shown as context with no-recovery comparisons):
    --reference-report FILE  per-question mean of the clean repetitions in a screening
                             report (eval/v2_screening_report.json: 3 per question)
    --reference DIR          the clean baseline runs in one output directory
Without either, clean baseline runs among the directories are used; the script stops if
a question has more than one.

Prints a per-condition table and a per-question breakdown, and optionally writes one row
per question run to a CSV and both tables to a Markdown file. Absolute values are always
reported alongside the deltas.
"""

import argparse
import csv
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

FAULTS = ("connection_drop", "result_timeout")
FAULT_EVENTS = {"connection.dropped": "connection_drop", "result.timed_out": "result_timeout"}
STRATEGIES = ("baseline", "full-restart", "always-verify")


def fault_of(config):
    """Name the enabled delegation fault; 'clean' when none is enabled."""
    enabled = [name for name in FAULTS if (config.get(name) or {}).get("enabled")]
    others = [
        name for name in ("document_injection", "tool_failure")
        if (config.get(name) or {}).get("enabled")
    ]
    if others:
        return "other:" + "+".join(enabled + others)
    return enabled[0] if enabled else "clean"


def load_manifests(directories):
    results = []
    for directory in directories:
        for path in sorted(Path(directory).glob("batches/*.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for result in manifest.get("results", []):
                if "attempts" in result or "status" in result:
                    results.append((Path(directory), result))
    return results


def resolve_run_dir(root, output_dir):
    """Recorded paths are absolute on the machine that ran them; fall back to the name."""
    path = Path(output_dir)
    if (path / "events.sqlite").is_file():
        return path
    candidate = root / path.name
    return candidate if (candidate / "events.sqlite").is_file() else None


def read_events(run_dir):
    if run_dir is None:
        return [], lambda ref: {}
    db = sqlite3.connect(f"file:{run_dir / 'events.sqlite'}?mode=ro", uri=True)
    try:
        events = [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]
    finally:
        db.close()

    def payload(ref):
        try:
            return json.loads((run_dir / "artifacts" / f"{ref}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    return events, payload


def agent_tokens(events, payload, agent):
    total = 0
    for event in events:
        if event["event_type"] == "model.response" and event["agent_id"] == agent:
            usage = payload(event["payload_ref"]).get("usage_metadata") or {}
            total += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return total


def attempt_metrics(root, attempt):
    """Per-attempt trace metrics taken from events, not from model-visible text."""
    events, payload = read_events(resolve_run_dir(root, attempt.get("output_dir", "")))
    batches = defaultdict(int)
    for event in events:
        if event["event_type"] == "delegation.request":
            batches[event.get("batch_id")] += 1
    injected = [e for e in events if e["event_type"] in FAULT_EVENTS]
    statuses = defaultdict(int)
    for event in events:
        if event["event_type"] == "worker.finished":
            statuses[payload(event["payload_ref"]).get("status", "?")] += 1
    # Tokens a withheld Worker spent before its result was lost (result_timeout only).
    wasted_worker_tokens = sum(
        agent_tokens(events, payload, e["assignment_id"])
        for e in injected if e["event_type"] == "result.timed_out"
    )
    withheld_status = defaultdict(int)
    for event in injected:
        if event["event_type"] == "result.timed_out":
            withheld_status[payload(event["payload_ref"]).get("worker_status", "?")] += 1
    return {
        "trace_found": bool(events),
        "batches": len(batches),
        "dispatched": sum(batches.values()),
        "dispatched_batch1": batches.get(1, 0),
        "injected": len(injected),
        "workers_completed": statuses.get("completed", 0),
        "workers_budget_exhausted": statuses.get("budget_exhausted", 0),
        "workers_failed": statuses.get("failed", 0),
        "wasted_worker_tokens": wasted_worker_tokens,
        "withheld_completed": withheld_status.get("completed", 0),
        "withheld_not_completed": sum(
            n for status, n in withheld_status.items() if status != "completed"
        ),
    }


def summarize_result(root, result):
    attempts = result.get("attempts") or [result]
    config = result.get("base_config") or result.get("config") or {}
    first = attempt_metrics(root, attempts[0])
    final = attempt_metrics(root, attempts[-1]) if len(attempts) > 1 else first
    verifications = [v for a in attempts for v in a.get("verifications", [])]
    usage = result.get("usage") or {}
    verifier = (result.get("usage_by_role") or {}).get("verifier") or {}
    grade = result.get("grade") or {}
    restarted = bool(result.get("restarted"))
    return {
        "question_id": result.get("question_id"),
        "fault": fault_of(config),
        "strategy": result.get("strategy", "baseline"),
        "status": result.get("status"),
        "answered": bool(result.get("answer")),
        "correct": grade.get("correct"),
        "attempts": len(attempts),
        "restarted": restarted,
        "injected": first["injected"],
        "dispatched_batch1": first["dispatched_batch1"],
        "redelegated_after_fault": first["injected"] > 0 and first["batches"] > 1,
        "batches_total": first["batches"] + (final["batches"] if restarted else 0),
        "workers_completed": final["workers_completed"],
        "workers_budget_exhausted": final["workers_budget_exhausted"],
        "workers_failed": final["workers_failed"],
        "withheld_completed": first["withheld_completed"],
        "withheld_not_completed": first["withheld_not_completed"],
        "total_tokens": usage.get("total_tokens"),
        "cost_usd": usage.get("estimated_cost_usd"),
        "elapsed_seconds": round(result.get("elapsed_seconds") or 0, 1),
        "wall_seconds": round(result.get("wall_duration_seconds") or 0, 1),
        "wasted_attempt_tokens": (
            (attempts[0].get("usage") or {}).get("total_tokens") if restarted else 0
        ),
        "wasted_attempt_seconds": (
            round(attempts[0].get("elapsed_seconds") or 0, 1) if restarted else 0
        ),
        "wasted_worker_tokens": first["wasted_worker_tokens"],
        # A restart discards the whole first attempt, which already includes any withheld
        # Worker tokens; without a restart only the withheld Workers' tokens are wasted.
        "wasted_tokens": (
            (attempts[0].get("usage") or {}).get("total_tokens") if restarted
            else first["wasted_worker_tokens"]
        ),
        "verifications": len(verifications),
        "verifier_flagged": sum(v.get("verified") is False for v in verifications),
        "verifier_errors": sum(v.get("error") is not None for v in verifications),
        "verifier_tokens": verifier.get("total_tokens", 0),
        "trace_found": first["trace_found"],
    }


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def fmt(value, digits=1):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def condition_table(rows, reference_label):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["fault"], row["strategy"])].append(row)

    def order(key):
        fault, strategy = key
        fault_rank = (["clean", *FAULTS].index(fault) if fault in ("clean", *FAULTS) else 9)
        strategy_rank = STRATEGIES.index(strategy) if strategy in STRATEGIES else 9
        return fault_rank, strategy_rank

    header = [
        "fault", "strategy", "n", "correct", "answered", "restarted", "injected/run",
        "redelegated", "tokens", f"Δtok vs {reference_label}", f"tok vs {reference_label}",
        "seconds", f"sec vs {reference_label}", "wasted tok", "verifier tok", "flagged",
        "verif err",
    ]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for key in sorted(groups, key=order):
        group = groups[key]

        def ratio(field, ref_field):
            pairs = [(r[field], r[ref_field]) for r in group
                     if r.get(ref_field) and r[field] is not None]
            return sum(a for a, _ in pairs) / sum(b for _, b in pairs) if pairs else None

        tok_ratio = ratio("total_tokens", "ref_tokens")
        sec_ratio = ratio("elapsed_seconds", "ref_seconds")
        delta = mean(r.get("delta_tokens") for r in group)
        lines.append("| " + " | ".join([
            key[0], key[1], str(len(group)),
            f"{sum(r['correct'] is True for r in group)}/{len(group)}",
            f"{sum(r['answered'] for r in group)}/{len(group)}",
            str(sum(r["restarted"] for r in group)),
            fmt(mean(r["injected"] for r in group)),
            str(sum(r["redelegated_after_fault"] for r in group)),
            fmt(mean(r["total_tokens"] for r in group), 0),
            f"{delta:+.0f}" if delta is not None else "-",
            f"x{tok_ratio:.2f}" if tok_ratio else "-",
            fmt(mean(r["elapsed_seconds"] for r in group)),
            f"x{sec_ratio:.2f}" if sec_ratio else "-",
            fmt(mean(r["wasted_tokens"] or 0 for r in group), 0),
            fmt(mean(r["verifier_tokens"] for r in group), 0),
            str(sum(r["verifier_flagged"] for r in group)),
            str(sum(r["verifier_errors"] for r in group)),
        ]) + " |")
    return "\n".join(lines)


SHORT = {
    ("clean", "baseline"): "clean", ("clean", "always-verify"): "clean+V",
    ("connection_drop", "baseline"): "drop", ("connection_drop", "full-restart"): "drop+R",
    ("connection_drop", "always-verify"): "drop+V",
    ("result_timeout", "baseline"): "timeout", ("result_timeout", "full-restart"): "timeout+R",
    ("result_timeout", "always-verify"): "timeout+V",
}


def condition_key(row):
    fault, strategy = row["fault"], row["strategy"]
    fault_rank = ["clean", *FAULTS].index(fault) if fault in ("clean", *FAULTS) else 9
    strategy_rank = STRATEGIES.index(strategy) if strategy in STRATEGIES else 9
    return fault_rank, strategy_rank, fault, strategy


def question_table(rows):
    """One row per question; each cell is 'correct tokens seconds' for one condition.

    Repeated runs of the same question and condition are listed in run order.
    """
    conditions = sorted({condition_key(r) for r in rows})
    labels = [SHORT.get((c[2], c[3]), f"{c[2]}/{c[3]}") for c in conditions]
    cells = defaultdict(list)
    for row in rows:
        mark = {True: "✓", False: "✗"}.get(row["correct"], "?")
        if not row["answered"]:
            mark = "∅"
        tokens = row["total_tokens"]
        text = f"{mark} {tokens / 1000:.1f}k {row['elapsed_seconds']:.0f}s" if tokens else mark
        notes = []
        if row["injected"]:
            notes.append(f"inj{row['injected']}")
        if row["restarted"]:
            notes.append("R")
        if row["redelegated_after_fault"]:
            notes.append("re")
        if row["verifier_flagged"]:
            notes.append(f"flag{row['verifier_flagged']}")
        if notes:
            text += " (" + ",".join(notes) + ")"
        cells[(row["question_id"], condition_key(row))].append(text)

    def qorder(qid):
        return (0, int(qid)) if str(qid).isdigit() else (1, str(qid))

    questions = sorted({r["question_id"] for r in rows}, key=qorder)
    lines = [
        "| question | " + " | ".join(labels) + " |",
        "|" + "---|" * (len(labels) + 1),
    ]
    for qid in questions:
        lines.append("| " + " | ".join(
            [str(qid)] + ["<br>".join(cells.get((qid, c), ["-"])) for c in conditions]
        ) + " |")
    return "\n".join(lines)


def reference_rows(rows, reference_rows_list):
    """Map question_id -> the single clean baseline run used as the comparison reference."""
    pool = reference_rows_list if reference_rows_list is not None else [
        r for r in rows if r["fault"] == "clean" and r["strategy"] == "baseline"
    ]
    clean = {}
    for row in pool:
        if row["fault"] != "clean" or row["strategy"] != "baseline":
            raise SystemExit("--reference must contain clean baseline runs only")
        if row["question_id"] in clean:
            raise SystemExit(
                f"Several clean baseline runs for question {row['question_id']}; "
                "pass --reference to choose one directory"
            )
        clean[row["question_id"]] = row
    return clean


def report_reference(path, question_ids):
    """Reference rows from a screening report: per-question mean of its clean repetitions."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = report.get("questions") or {}
    rows = []
    for qid in question_ids:
        entry = questions.get(str(qid))
        if not entry:
            print(f"Warning: question {qid} is not in {path}; it has no reference.",
                  file=sys.stderr)
            continue
        correct = entry.get("correct") or []
        rows.append({
            "question_id": str(qid), "fault": "clean", "strategy": "baseline",
            "reference_runs": len(entry.get("total_tokens") or []),
            "correct": bool(correct) and all(c is True for c in correct),
            "answered": all(s == "completed" for s in entry.get("status") or []),
            "total_tokens": round(statistics.fmean(entry["total_tokens"])),
            "elapsed_seconds": round(statistics.fmean(entry["duration_seconds"]), 1),
            "injected": 0, "restarted": False, "redelegated_after_fault": False,
            "wasted_tokens": 0, "verifier_tokens": 0, "verifier_flagged": 0,
            "verifier_errors": 0,
        })
    return rows


def no_recovery_rows(rows):
    """Map (fault, question_id) -> the fault's single no-recovery run."""
    mapping = {}
    for row in rows:
        if row["fault"] in FAULTS and row["strategy"] == "baseline":
            key = (row["fault"], row["question_id"])
            if key in mapping:
                raise SystemExit(
                    f"Several no-recovery {key[0]} runs for question {key[1]}; "
                    "pass one directory per condition"
                )
            mapping[key] = row
    return mapping


def add_deltas(rows, lookup):
    """Per-run differences from the reference row that lookup(row) returns, if any."""
    for row in rows:
        ref = lookup(row)
        row["ref_correct"] = ref["correct"] if ref else None
        row["ref_tokens"] = ref["total_tokens"] if ref else None
        row["ref_seconds"] = ref["elapsed_seconds"] if ref else None
        tokens, seconds = row["total_tokens"], row["elapsed_seconds"]
        has_tok = ref is not None and tokens is not None and ref["total_tokens"]
        has_sec = ref is not None and ref["elapsed_seconds"]
        row["delta_tokens"] = tokens - ref["total_tokens"] if has_tok else None
        row["tokens_ratio"] = round(tokens / ref["total_tokens"], 3) if has_tok else None
        row["delta_seconds"] = round(seconds - ref["elapsed_seconds"], 1) if has_sec else None
        row["seconds_ratio"] = round(seconds / ref["elapsed_seconds"], 3) if has_sec else None
        row["correct_changed"] = (
            None if ref is None or row["correct"] is None or ref["correct"] is None
            else row["correct"] != ref["correct"]
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dirs", nargs="+", type=Path, help="mar --output-dir directories")
    parser.add_argument("--csv", type=Path, help="Write one row per question run")
    parser.add_argument("--md", type=Path, help="Also write both tables to a Markdown file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reference", type=Path,
                       help="Clean baseline output directory used for every comparison")
    group.add_argument("--reference-report", type=Path,
                       help="Screening report whose per-question clean means are the reference")
    parser.add_argument("--compare-to", choices=("no-recovery", "clean"), default="no-recovery",
                        help="Reference for deltas and ratios (default: the same fault's "
                             "no-recovery run on the same question)")
    args = parser.parse_args(argv)

    loaded = load_manifests(args.dirs)
    if not loaded:
        print("No batch manifests found under the given directories.", file=sys.stderr)
        return 1
    reference_dir = args.reference.resolve() if args.reference else None
    rows = [
        summarize_result(root, result) for root, result in loaded
        if reference_dir is None or root.resolve() != reference_dir
    ]
    reference_list = None
    if args.reference:
        reference_list = [summarize_result(root, r) for root, r in load_manifests([args.reference])]
        if not reference_list:
            raise SystemExit(f"No batch manifests found under {args.reference}")
        extra = [r for r in rows if r["fault"] == "clean" and r["strategy"] == "baseline"]
        if extra:
            print(f"Ignoring {len(extra)} clean baseline runs outside --reference.",
                  file=sys.stderr)
        rows = reference_list + [r for r in rows if r not in extra]
    if args.reference_report:
        extra = [r for r in rows if r["fault"] == "clean" and r["strategy"] == "baseline"]
        if extra:
            print(f"Ignoring {len(extra)} clean baseline runs; using --reference-report.",
                  file=sys.stderr)
        rows = [r for r in rows if r not in extra]
        question_ids = sorted({r["question_id"] for r in rows}, key=lambda q: (len(q), q))
        reference_list = report_reference(args.reference_report, question_ids)
    clean = reference_rows(rows, reference_list)
    if args.compare_to == "clean":
        def lookup(row):
            is_ref = row["fault"] == "clean" and row["strategy"] == "baseline"
            return None if is_ref else clean.get(row["question_id"])
        reference_label = "clean"
    else:
        norec = no_recovery_rows(rows)

        def lookup(row):
            if row["fault"] not in FAULTS or row["strategy"] == "baseline":
                return None
            return norec.get((row["fault"], row["question_id"]))
        reference_label = "no-rec"
    add_deltas(rows, lookup)
    # Report references are means, not runs: they join the tables but not the CSV.
    run_rows = list(rows)
    if args.reference_report:
        rows = reference_list + rows
    missing = [r["question_id"] for r in run_rows if not r["trace_found"]]
    if missing:
        print(f"Warning: no events.sqlite found for questions {missing}.", file=sys.stderr)

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(run_rows[0]))
            writer.writeheader()
            writer.writerows(run_rows)
        print(f"Wrote {len(run_rows)} rows to {args.csv}")

    if args.compare_to == "no-recovery":
        reference_note = (
            "Deltas and ratios: each recovery run vs the same fault's no-recovery run "
            "(strategy baseline) on the same question"
        )
        if clean:
            reference_note += "; clean rows are context only"
    elif args.reference_report:
        reference_note = (
            f"Reference: per-question mean of the clean repetitions in {args.reference_report} "
            "('clean' rows and column; correct only if correct in every repetition)"
        )
    elif args.reference:
        reference_note = f"Reference: {args.reference}"
    else:
        reference_note = "Reference: clean baseline runs"
    notes = (
        f"{reference_note}. Ratios are summed over the paired questions. 'wasted tok' is the discarded first attempt for full-restart, otherwise "
        "the tokens spent by Workers whose results were withheld (result_timeout). 'flagged' "
        "counts verifications with verified=false; 'verif err' counts verifier calls that "
        "failed.\n\nPer-question cells: ✓ correct, ✗ wrong, ∅ no answer, ? ungraded; then "
        "total tokens and seconds. inj = faults injected, R = restarted, re = Lead "
        "re-delegated after the fault, flag = verifier flags. +R = full-restart, "
        "+V = always-verify."
    )
    report = "\n\n".join([
        "## By condition", condition_table(rows, reference_label),
        "## By question", question_table(rows), notes,
    ])
    print(report)
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(report + "\n", encoding="utf-8")
        print(f"\nWrote tables to {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
