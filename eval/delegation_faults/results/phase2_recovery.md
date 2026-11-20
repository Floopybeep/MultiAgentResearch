# Phase 2: delegation fault recovery

Shared 10 questions, one run per condition. Full restart and batch replay start from the same
faulted attempt (`mar --full-restart`, then `batch_replay.py`); their totals include that attempt.
Online recovery is one `mar` run with `delegation_recovery: {enabled: true}`, otherwise the same config.

| Fault | Strategy | Correct | Tokens, mean (median) | Redundant tokens | Seconds, mean |
|---|---|---|---|---|---|
| Assignment drop | Online recovery | 10/10 | 64.8k (59.0k) | 0 | 36.5 |
| Assignment drop | Batch replay | 10/10 | 61.2k (60.4k) | 15.4k | 19.0 |
| Assignment drop | Full restart | 10/10 | 81.2k (76.8k) | 20.2k | 22.1 |
| Result drop | Online recovery | 10/10 | 54.1k (50.3k) | 0 | 195.3 |
| Result drop | Batch replay | 10/10 | 105.7k (92.0k) | 49.0k | 197.5 |
| Result drop | Full restart | 10/10 | 117.8k (115.3k) | 54.1k | 200.6 |

Redundant tokens: faulted-attempt work that is discarded and redone (full restart: the whole
faulted attempt; batch replay: everything after the pre-batch checkpoint, i.e. the Workers
that already ran in the faulted batch; online recovery: none, since each Worker runs once). Unlike totals, it does
not depend on the path the Lead takes after recovery.

Recovery triggered as expected: every dropped assignment was resent (15 retries for 15 drops) and every withheld result was retrieved (14/14); no failure reached the Lead.

## Findings

- Result drop: online retrieval needs no Worker reruns and roughly halves tokens vs batch replay
  (cheaper on 10/10 questions). Latency is unchanged: the 180 s timeout must elapse before the
  failure is observed.
- Assignment drop: online recovery avoids rerunning the delivered Workers (about 15k redundant
  tokens per question in batch replay), but total tokens are within run-to-run Lead variance at one run
  per condition (online cheaper on 8/10 questions).
- Both beat full restart, which discards the whole faulted attempt.

## Limitations

- These are archived measurements from the original implementation. Its batch-replay
  seconds excluded grading, while full-restart seconds included grading; the replay
  timings above and in the CSV are therefore not directly comparable. The corrected
  evaluator includes grading for new replays. These runs have not been repeated.
- Online runs used a slower endpoint (median model call 3.8 s vs 1.9 s), so seconds are not
  comparable across strategies for assignment drop.
- One run per condition; totals include Lead variance after recovery.

Per-question rows: `phase2_recovery.csv`.
