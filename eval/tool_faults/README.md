# Tool faults — accidental evidence denial at the `read_document` boundary

`fault_class: accidental` · `fault_effect: denial`. One fault family among several in
`eval/`. Delegation faults, budget faults and prompt injection are different families with
their own directories; **never pool their cells with these**, and no combined number
appears in anything here.

## The grid this study hangs on

Two manifestations × three scenarios. Targeting is identical in every cell — one document,
`persistent: true`, `max_failures: null`, `offsets: []` — so a move across this grid changes
only how the denial appears or how the system is allowed to respond to it.

| | baseline | `--full-restart` | `--always-verify` |
|---|---|---|---|
| **`immediate`** (tool raises at once) | §5, n=28 · Tier 3 rep 2, n=10 | Tier 2, n=10 | Tier 2, n=10 |
| **`timeout`** (read outlives `call_timeout_seconds`) | **Tier 1, n=10** | Tier 2, n=10 | Tier 4, n=4 |

82 fault cells, plus 1 sanity cell counted only in the spend table. Tier 1 is bold because
the immediate-vs-timeout contrast at baseline is the headline result: 68/68 correct as an
immediate error, 2/10 as a timeout, failing by not finishing rather than by answering wrong.

## ⚠ Three dependent variables, not one metric in three conditions

**Propagation is structurally unmeasurable in the 20 full-restart cells.**
`research.py:36-37` stamps `status: interrupted` on every node as soon as
`runtime.injected_faults` is non-empty while `full_restart` and attempt 1, and
`runner.py:129-130` skips grading for attempt 1. Attempt 1 therefore ends at the first
completed node after the denial, the Lead never reasons about the missing evidence, and
attempt 2 runs clean. All 20 cells stop at deepest stage `1_tool_call`.

Reading propagation across all six grid cells will find nothing in a third of them and
invite the conclusion that the fault did nothing. It is not that. **Baseline measures
propagation, full-restart measures recovery cost, always-verify measures detection.**
Compare each arm against the clean control, never against each other.

## What each report is for

| report | measures | why it exists |
|---|---|---|
| [`reports/section-5-rep1.md`](reports/section-5-rep1.md) | propagation; which documents the workload actually depends on | all 28 pairs, so bearers are found empirically rather than guessed. Result: 25 routed around, 3 never exercised, **0 load-bearing** |
| [`reports/tier-1.md`](reports/tier-1.md) | the manifestation contrast | **the headline.** Same targeting as §5, `timeout` the only change. Primary readout is latency and completion, not tokens |
| [`reports/tier-2.md`](reports/tier-2.md) | recovery cost (full-restart arm) | what a clean restart costs: discarded attempt-1 tokens, attempt-2 vs clean, wall-clock penalty |
| [`reports/tier-2.md`](reports/tier-2.md) | detection (always-verify arm) | whether the verifier flags the denial *specifically*, scored against ground truth, and what verification costs |
| [`reports/tier-3.md`](reports/tier-3.md) | run-to-run variance | **bounds every n=1 magnitude in the other tiers.** Verdicts reproduce 10/10; tokens move ±9.7% median, wall clock ±39.8% |
| [`reports/tier-4.md`](reports/tier-4.md) | the last empty grid cell | deliberately under-powered at n=4: most expensive cell, least marginal information. Quote no detection rate without the n |
| [`reports/section-6.md`](reports/section-6.md) | cross-tier consolidation | the Phase 1 measurement set, one column per condition |

## Three traps

1. **`section-5-rep1` is not a fifth tier.** There is no Tier 5. It is §5 rep 1 rescored
   through the tier reporter so Tier 3 can compare reps on identical definitions. The
   canonical §5 artifact is `fault_propagation_report.json`.
   Practical consequence: globbing `reports/tier-*.json` yields **54** cells and silently
   drops §5's 28. Aggregating all 82 needs `reports/*.json`.
2. **Tier numbers are spending batches, not execution or logical order.** Execution order
   was §5 → Tier 2 → Tier 3 → Tier 1 → Tier 4. Nothing depends on the numbering.
3. **§6 and Tier 3 targets diverge on Q224 and Q251.** Tier 3 uses the §5 picks (highest
   token ratio among fired pairs); §6 additionally excludes title-leaking documents, so it
   uses doc_0727 over doc_0728 and doc_0858 over doc_0860. The other eight coincide.

## Files

| | |
|---|---|
| `make_fault_configs.py` | one YAML per cell; `--cells MODE:SCENARIO` for non-cross-product tiers |
| `title_leak.py` | does catalog metadata alone reveal the gold answer? |
| `fault_analysis.py` | §5 dependency sweep → `fault_propagation_report.json` |
| `tier_report.py` | per-tier Phase 1 report → `reports/` |
| `audit_control_config.py` | is the clean control config-matched by record? → `control_config_audit.json` |
| `targets_section6.tsv`, `targets_tier3_variance.tsv`, `targets_tier4.tsv` | per-tier targets |
| `prereg_sweep.json` | NOT_EXERCISED prediction, recorded before §5 ran |

Shared infrastructure stays at `eval/`: `shared_10_question_ids.txt`,
`v2_screening_report.json`, `build_v2_report.py`, `screen_baseline.py`. Run everything from
the repository root. Traces live under `runs/` and are gitignored.
