"""Batch replay: recover faulted attempts from the checkpoint before the faulted batch.

Takes the output of `mar ... --full-restart`. For every question that was restarted,
attempt-1 is the faulted attempt, interrupted after the faulted batch. This script
replays it from the pre-batch delegation checkpoint with every fault disabled
(`recover(..., disable_faults=True)`), grades the replayed answer, and compares the cost
with the full restart (attempt-2) on the same faulted attempt, so both strategies share
an identical fault schedule.

Work before the checkpoint (the Lead's planning) is preserved; everything from the
checkpoint on is discarded and replayed. No Worker results are reused yet.

Usage (makes real model calls for the replay and for grading):
    uv run python eval/delegation_faults/batch_replay.py runs/exp/drop_restart \\
        runs/exp/timeout_restart --csv runs/exp/batch_replay.csv --md runs/exp/batch_replay.md

Replays are written to questions/<id>/batch-replay/ next to the attempts. Completed
replays are reused on later invocations; failed ones are retried into a fresh directory
(batch-replay-2, ...), and --force replays again even when the last one completed.
"""

import argparse
import asyncio
import csv
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path

from multi_agent_research.recovery import recover
from multi_agent_research.runtime import INJECTION_EVENTS

FAULTS = ("connection_drop", "result_timeout")
REPLAY_DIR = "batch-replay"


def read_events(run_dir):
    db_path = Path(run_dir) / "events.sqlite"
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        return [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]


def payload(run_dir, event):
    path = Path(run_dir) / "artifacts" / f"{event['payload_ref']}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def response_tokens(run_dir, events):
    total = 0
    for event in events:
        if event["event_type"] == "model.response":
            usage = payload(run_dir, event).get("usage_metadata") or {}
            total += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return total


def timestamp(event):
    return datetime.fromisoformat(event["timestamp"])


def fault_of(config):
    enabled = [name for name in FAULTS if (config.get(name) or {}).get("enabled")]
    return enabled[0] if len(enabled) == 1 else "other"


def checkpoint_before_fault(events):
    """The pre-batch delegation checkpoint of the batch with the earliest injection.

    Every delegation call in a batch points to the same pre-batch graph checkpoint;
    the first one's ID is used.
    """
    injected = next((e for e in events if e["event_type"] in INJECTION_EVENTS), None)
    if injected is None or injected.get("batch_id") is None:
        return None, None
    batch = injected["batch_id"]
    for index, event in enumerate(events):
        if (event["event_type"] == "delegation.request" and event.get("batch_id") == batch
                and event.get("recovery_point_id")):
            return event["recovery_point_id"], index
    return None, None


def question_and_reference(attempt):
    """Taken from the graded full-restart attempt, which records both."""
    for event in read_events(attempt):
        if event["event_type"] == "grade.started":
            body = payload(attempt, event)
            return body["question"], body["reference_answer"]
    raise ValueError(f"No graded question in {attempt}")


async def grade(directory, config, question, reference, answer, model=None):
    """Grade the replayed answer with the project's grader in a separate log."""
    from multi_agent_research.config import RunConfig
    from multi_agent_research.grading import grade_answer
    from multi_agent_research.models.adapter import OpenAIChatCompletionsAdapter
    from multi_agent_research.runtime import Runtime
    from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

    if not answer:
        return {"method": "not_answered", "correct": False, "usage": {"total_tokens": 0}}
    # Grading reads no documents; the runtime only needs a non-empty catalog.
    placeholder = OracleDocuments([LocalDocument(
        document_id="grading", title="grading", url="https://example.org/grading", text="-",
    )])
    runtime = Runtime(RunConfig.model_validate(config),
                      model or OpenAIChatCompletionsAdapter(), placeholder,
                      root=Path(directory))
    try:
        return await grade_answer(runtime, question, reference, answer)
    finally:
        runtime.close()


async def replay_question(question_dir, *, model=None, force=False):
    """Replay one restarted question; return the metrics row, or None if not restarted."""
    question_dir = Path(question_dir)
    first, second = question_dir / "attempt-1", question_dir / "attempt-2"
    if not second.is_dir():
        return None
    events = read_events(first)
    point, checkpoint_index = checkpoint_before_fault(events)
    if point is None:
        return None
    first_run = json.loads((first / "run.json").read_text(encoding="utf-8"))
    second_run = json.loads((second / "run.json").read_text(encoding="utf-8"))
    attempts = second_run.get("attempts") or []
    first_attempt = attempts[0] if attempts else first_run
    second_attempt = attempts[-1] if attempts else second_run

    destination = question_dir / REPLAY_DIR
    record = destination / "batch_replay.json"
    if record.is_file() and not force:
        previous = json.loads(record.read_text(encoding="utf-8"))
        # Reuse only finished replays; a failed one (e.g. a lost connection) is retried.
        if previous.get("replay_status") == "completed":
            return previous
    if destination.exists():
        # Forced, failed, or stopped before recording: never overwrite earlier output.
        index = 2
        while (question_dir / f"{REPLAY_DIR}-{index}").exists():
            index += 1
        destination = question_dir / f"{REPLAY_DIR}-{index}"
        record = destination / "batch_replay.json"

    replay = await recover(first, point, model=model, output_dir=destination,
                           disable_faults=True)
    question, reference = question_and_reference(second)
    graded = await grade(destination / "grading", second_attempt["config"], question,
                         reference, replay.get("answer"), model=model)

    first_tokens = first_attempt["usage"]["total_tokens"]
    preserved_tokens = response_tokens(first, events[:checkpoint_index])
    # recover() restores the source attempt's usage, so subtract it to get the replay.
    replay_tokens = replay["usage"]["total_tokens"] - first_tokens
    judge_tokens = (graded.get("usage") or {}).get("total_tokens", 0)
    first_seconds = first_attempt["elapsed_seconds"]
    preserved_seconds = (timestamp(events[checkpoint_index]) - timestamp(events[0])).total_seconds()
    restart_correct = second_attempt.get("correct")
    row = {
        "question_id": question_dir.name,
        "fault": fault_of(first_attempt["config"]),
        "recovery_point_id": point,
        "replay_status": replay["status"],
        "replay_error": replay.get("error"),
        "replay_correct": graded.get("correct"),
        "replay_grade_method": graded.get("method"),
        "replay_grade_error": graded.get("error"),
        "restart_correct": restart_correct,
        "faulted_attempt_tokens": first_tokens,
        "preserved_tokens": preserved_tokens,
        "replay_wasted_tokens": first_tokens - preserved_tokens,
        "restart_wasted_tokens": first_tokens,
        "replay_tokens": replay_tokens + judge_tokens,
        "restart_tokens": second_attempt["usage"]["total_tokens"],
        "replay_total_tokens": first_tokens + replay_tokens + judge_tokens,
        "restart_total_tokens": first_tokens + second_attempt["usage"]["total_tokens"],
        "faulted_attempt_seconds": round(first_seconds, 1),
        "preserved_seconds": round(preserved_seconds, 1),
        "replay_wasted_seconds": round(first_seconds - preserved_seconds, 1),
        "restart_wasted_seconds": round(first_seconds, 1),
        "replay_seconds": round(replay["duration_seconds"], 1),
        "restart_seconds": round(second_attempt["elapsed_seconds"], 1),
        "replay_total_seconds": round(first_seconds + replay["duration_seconds"], 1),
        "restart_total_seconds": round(first_seconds + second_attempt["elapsed_seconds"], 1),
        "replay_dir": str(destination),
    }
    record.write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def question_dirs(directories):
    for directory in directories:
        for batch in sorted(Path(directory).glob("*/batch.json")):
            for question in sorted((batch.parent / "questions").iterdir(),
                                   key=lambda p: (len(p.name), p.name)):
                if question.is_dir():
                    yield question


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def table(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["fault"]].append(row)
    header = ["fault", "strategy", "n", "correct", "wasted tok", "preserved tok",
              "recovery tok", "total tok", "wasted s", "recovery s", "total s"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for fault in sorted(groups):
        group = groups[fault]
        for name, prefix, preserved in (("full restart", "restart", 0),
                                        ("batch replay", "replay", None)):
            correct = sum(r[f"{prefix}_correct"] is True for r in group)
            lines.append("| " + " | ".join([
                fault, name, str(len(group)), f"{correct}/{len(group)}",
                f"{mean(r[f'{prefix}_wasted_tokens'] for r in group):.0f}",
                f"{preserved if preserved is not None else mean(r['preserved_tokens'] for r in group):.0f}",
                f"{mean(r[f'{prefix}_tokens'] for r in group):.0f}",
                f"{mean(r[f'{prefix}_total_tokens'] for r in group):.0f}",
                f"{mean(r[f'{prefix}_wasted_seconds'] for r in group):.1f}",
                f"{mean(r[f'{prefix}_seconds'] for r in group):.1f}",
                f"{mean(r[f'{prefix}_total_seconds'] for r in group):.1f}",
            ]) + " |")
    note = (
        "Per-question means over restarted questions; both strategies start from the same "
        "faulted attempt. Wasted = faulted-attempt work that is discarded (all of it for "
        "full restart; everything after the pre-batch checkpoint for batch replay). "
        "Preserved = Lead work before that checkpoint. Recovery = the restart or replay "
        "itself, including grading. Total = faulted attempt + recovery."
    )
    return "\n".join(lines) + "\n\n" + note


async def main_async(args):
    rows = []
    for question in question_dirs(args.dirs):
        try:
            row = await replay_question(question, force=args.force)
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            print(f"{question}: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        if row is not None:
            print(f"{question}: replay {row['replay_status']}, correct={row['replay_correct']}")
            rows.append(row)
    if not rows:
        print("No restarted questions found.", file=sys.stderr)
        return 1
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = table(rows)
    print(report)
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(report + "\n", encoding="utf-8")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dirs", nargs="+", type=Path, help="mar --full-restart output dirs")
    parser.add_argument("--csv", type=Path, help="Write one row per question")
    parser.add_argument("--md", type=Path, help="Write the summary table")
    parser.add_argument("--force", action="store_true", help="Replay again into a new directory")
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
