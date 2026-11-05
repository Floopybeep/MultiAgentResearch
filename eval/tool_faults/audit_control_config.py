"""Audit whether the clean control's config is RECORDED or merely inferred.

Every wasted-work and latency ratio in section 6 is divided by a clean-control
mean from `runs/v2-base1..3`. `minimum_worker` drives delegation volume, which is
that denominator, so if the control had run at a different value every ratio would
be biased. This script settles it from the traces instead of by inference.

Two traps it works around:

- `run.started` does NOT carry the config (its payload is attempt_number,
  faults_enabled, metadata, previous_run_id, prompt_hashes, query, strategy,
  task_type). Looking only there suggests the config was never recorded.
- The control databases hold uncheckpointed WAL content. Opening them
  `file:...?mode=ro` cannot replay the WAL, and the `records` table reads as
  absent. Each database is therefore copied with its `-wal`/`-shm` sidecars before
  being queried; the originals are never opened for writing.

    python eval/tool_faults/audit_control_config.py \
        --out eval/tool_faults/control_config_audit.json
"""

import argparse
import collections
import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from multi_agent_research.config import RunConfig

CONTROL_REPS = ("runs/v2-base1", "runs/v2-base2", "runs/v2-base3")
SIDECARS = ("", "-wal", "-shm")
# Set per invocation or by the output directory, so they can never match.
IGNORED_KEYS = {"output_dir", "lead_prompt", "worker_prompt", "full_restart"}
BATCH_RE = re.compile(r"^batch(\d+)-")


def read_run(events: Path, workdir: Path):
    """Config record and worker-per-batch counts from one run, via a copy."""
    target = workdir / "copy.sqlite"
    for suffix in SIDECARS:
        source = Path(str(events) + suffix)
        if source.exists():
            shutil.copy2(source, str(target) + suffix)
    try:
        db = sqlite3.connect(str(target))
        tables = {t for (t,) in db.execute(
            "select name from sqlite_master where type='table'")}
        config = None
        if "records" in tables:
            rows = list(db.execute("select body from records where key='config'"))
            if rows:
                config = json.loads(rows[0][0])
        per_batch = collections.Counter()
        if "events" in tables:
            for (body,) in db.execute("select body from events"):
                event = json.loads(body)
                if event["event_type"] == "worker.started":
                    match = BATCH_RE.match(event["agent_id"])
                    if match:
                        per_batch[int(match.group(1))] += 1
        db.close()
        return config, per_batch
    finally:
        for suffix in SIDECARS:
            stale = Path(str(target) + suffix)
            if stale.exists():
                stale.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", nargs="+", default=list(CONTROL_REPS))
    parser.add_argument("--baseline", type=Path, default=Path("configs/baseline.yaml"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    baseline = RunConfig.load(args.baseline).model_dump(mode="json")
    minimum_worker = collections.Counter()
    always_verify = collections.Counter()
    mismatched = collections.Counter()
    workers_per_batch = collections.Counter()
    runs = without_config = 0

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for rep in args.reps:
            for run in sorted(p for p in Path(rep).iterdir() if p.is_dir()):
                events = run / "events.sqlite"
                if not events.exists():
                    continue
                config, per_batch = read_run(events, workdir)
                for count in per_batch.values():
                    workers_per_batch[count] += 1
                if config is None:
                    without_config += 1
                    continue
                runs += 1
                minimum_worker[config.get("minimum_worker")] += 1
                always_verify[config.get("always_verify")] += 1
                for key in set(baseline) | set(config):
                    if key not in IGNORED_KEYS and baseline.get(key) != config.get(key):
                        mismatched[key] += 1

    audit = {
        "reps": args.reps,
        "baseline": str(args.baseline),
        "runs_with_a_recorded_config": runs,
        "run_dirs_without_a_config_record": without_config,
        "config_is_recorded": runs > 0,
        "config_location": "events.sqlite `records` table, key 'config'",
        "not_in": "run.started payload, which carries no config",
        "minimum_worker_recorded": {str(k): v for k, v in minimum_worker.items()},
        "always_verify_recorded": {str(k): v for k, v in always_verify.items()},
        "keys_differing_from_baseline": {k: v for k, v in mismatched.items()},
        "ignored_keys": sorted(IGNORED_KEYS),
        "workers_per_batch_distribution": {str(k): v for k, v in
                                           sorted(workers_per_batch.items())},
        "workers_per_batch_mode": (max(workers_per_batch, key=workers_per_batch.get)
                                   if workers_per_batch else None),
        "delegation_batches_observed": sum(workers_per_batch.values()),
    }
    args.out.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
