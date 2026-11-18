# Delegation faults: propagation and recovery

Phase 1 and 2 measurements for the two delegation faults between the Lead and its
Workers, with the full-restart and always-verify recovery baselines.

| Fault (config key) | Boundary | Effect |
|---|---|---|
| Assignment drop (`connection_drop`) | Lead → Worker | In batch 1, only `num_delivered: 1` assignment reaches a Worker; the rest fail with `ConnectionError` and no Worker starts. |
| Result drop (`result_timeout`) | Worker → Lead | In batch 1, Workers run to completion, but all but one result are withheld; the Lead receives a natural-looking `TimeoutError` failure 180 s after dispatch. |

Both are accidental faults. See `configs/README.md` for their full semantics.

## Setup

- Questions: the shared 10 (`eval/shared_10_question_ids.txt`): 27 32 89 94 95 104 114 224 251 271.
- Configs: `configs/connection_drop.yaml` and `configs/result_timeout.yaml` are the exact
  configs used. They equal the `configs/baseline.yaml` of commit ee665fc with one fault
  enabled. That baseline had `max_workers_per_batch: 6` (main now has 4); no batch in any
  run exceeded 4 assignments, so the cap never applied.
- Conditions per fault, one run each: no recovery, `--full-restart`, `--always-verify`.
- Clean reference: the per-question mean of the 3 clean repetitions in
  `eval/v2_screening_report.json`.

```bash
Q="27 32 89 94 95 104 114 224 251 271"   # in bash; zsh does not split $Q
C=eval/delegation_faults/configs
uv run mar --config $C/connection_drop.yaml --question-ids $Q --output-dir runs/exp/drop_none
uv run mar --config $C/connection_drop.yaml --question-ids $Q --full-restart --output-dir runs/exp/drop_restart
uv run mar --config $C/connection_drop.yaml --question-ids $Q --always-verify --output-dir runs/exp/drop_verify
# Same three commands with result_timeout.yaml -> runs/exp/timeout_{none,restart,verify}

uv run python eval/delegation_faults/summarize.py runs/exp/drop_* runs/exp/timeout_* \
    --reference-report eval/v2_screening_report.json \
    --csv eval/delegation_faults/results/summary.csv --md eval/delegation_faults/results/summary.md
```

`results/summary.md` has the per-condition and per-question tables; `results/summary.csv`
has one row per question run. Recovery deltas are against the same fault without recovery,
paired by question.

## Results

| | Assign. drop | Result drop |
|---|---|---|
| **No recovery** (vs clean: 10/10, 55.9k tokens, 25.7 s) | | |
| Task success | 10/10 | 10/10 |
| Faulty items later re-requested by the Lead | 14/14 | 14/14 |
| Propagated to the final answer | 0/10 | 0/10 |
| Wasted work per run | 0 | 20.1k tokens + 180 s wait |
| Δ tokens / Δ latency vs clean | +11.3k / +6.5 s | +28.0k / +173.2 s |
| **Full restart** (vs no recovery) | | |
| Task success | 10/10 | 9/10 † |
| Discarded first attempt (tokens / s) | 21.3k / 9.6 s | 42.1k / 185.9 s |
| Δ tokens | +13.8k | +6.6k |
| **Always verify** (vs no recovery) | | |
| Task success | 10/10 | 10/10 |
| Injected faults flagged | N/A ‡ | 15/15; 0 false positives in 49 other checks; 1 verifier call failed (malformed JSON) |
| Verifier tokens / Δ tokens | 52.7k / +59.1k | 78.1k / +104.8k |

† Q89 failed in its clean restart attempt because of two natural `ModelCallTimeout`s
(60 s) at the endpoint, unrelated to the injected fault; a rerun under the same condition
answered correctly.
‡ Dropped assignments never start a Worker, so nothing reaches a verification boundary.

## Findings

- Both faults are explicit: the Lead sees an error, re-delegates the lost work, and every
  run answers correctly. The faults cost efficiency, not correctness.
- The Lead's own re-delegation already acts as selective recovery: it redoes only the lost
  assignments, so for assignment drop it is cheaper than full restart (67.2k vs 81.0k tokens).
- Full restart cannot avoid the 180 s result-drop wait, because it interrupts only after
  the faulted batch returns, and it discards all completed work in the first attempt.
- Always verify adds the largest overhead without changing outcomes: it is diagnostic only,
  and these failures are already visible to the Lead.
- Q224 (result drop, always verify): one withheld document was never re-requested, yet the
  answer was correct, so the workload did not depend on it. Correctness alone is not
  evidence of recovery.

## Limitations

- One run per condition. Token deltas are the primary measure; latency depends on
  endpoint load, and conditions ran at different times (the full-restart second attempts
  for assignment drop ran under low load).
- Unauthorized actions are N/A: the QA tools have no side effects, and `read_document`
  is scoped to the question's documents.
- Full restart disables all faults on retry, so it measures the optimistic case in which
  a fault does not persist across the restart.
