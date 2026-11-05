# Tier 4 — timeout x always-verify, serial, deliberately under-powered (4 cells)

`fault_class: accidental` · `fault_effect: denial` — tool-layer evidence denial at the `read_document` boundary. Every cell below is accidental denial; adversarial evidence-corruption conditions are a different fault class, owned by teammates, and are reported separately. Never pool these numbers with those.

Generated 2026-11-04T22:05:47-08:00 · 4 cells

## Running headline

Across section-5-rep1 (28) + tier-2 (30) + tier-3 (10) + tier-1 (10) the system produced **70 of 78 cells correct**.

This tier is **1 of 4 correct** so far (cells still landing).

> DELIBERATELY UNDER-POWERED AT n=4, and reduced from 10 questions on purpose. This is the most expensive cell per run in the whole section -- timeout dead time plus verifier calls at two boundaries -- and the least likely to show anything the earlier tiers have not: Tier 1 already establishes what the timeout manifestation does to completion, and Tier 2 already measures detection at n=10 under the immediate manifestation. Targets are the 4 section-6 targets with the highest section-5 token ratios (Q114 4.72, Q224 4.06, Q89 3.53, Q95 3.31). NO DETECTION-RATE CONCLUSION SHOULD BE DRAWN FROM n=4 WITHOUT STATING THE n.
> Run SERIALLY. Like Tier 1 these are wall-clock boundary cells against run_timeout_seconds: 900, so contention would change the dependent variable.
> The matched comparator for marginal verification cost in 8b is Tier 1 (timeout x baseline), not section 5: the manifestation must be held constant for the marginal cost of verification to mean anything.
> ADOPTION GATE: adoption is read from Lead model.response text plus worker terminal status, never from complete_task.uncertainties (structurally always empty under persistent denial). The gate was corrected twice during this section, both times for FALSE NEGATIVES: first it required the literal document ID or the substring 'read', which scored SILENT turns like 'The Snoopy worker has failed three times on budget' that name the document by catalog title and by worker; then it lacked any pattern for the timeout manifestation, which scored SILENT turns like 'The Cowboys article workers have timed out six times'. All tiers in this section were regenerated under the final gate.
> Single-rep magnitudes, and Tier 3's bound (token deviation median 9.7%, max 51.6%; wall clock median 39.8%, max 83.0%) applies to every number here. At n=4 the detection figures have no confidence interval worth quoting.

## 1. Cell table

| qid | doc | mode | scenario | status | termination | grade | att | batches | workers | wall s | tokens | cost | ×ctrl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 89 | doc_0304 | timeout | always-verify | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 10 | 900.0 | 189,362 | $0.0275 | 3.67 |
| 95 | doc_0327 | timeout | always-verify | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 9 | 900.0 | 350,484 | $0.0471 | 7.17 |
| 114 | doc_0380 | timeout | always-verify | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 10 | 900.0 | 244,016 | $0.0355 | 8.61 |
| 224 | doc_0727 | timeout | always-verify | completed | normal_finish | correct | 1 | 4 | 10 | 776.7 | 425,248 | $0.0588 | 9.91 |

All rows: `fault_class: accidental`, `fault_effect: denial`. `×ctrl` is tokens over the config-matched §5 control mean for that question.

## 2. Clean task success reference (no-fault control)

Source: runs/v2-base1..3 (config-matched baseline, pre-ceb5538 layout). 4 questions × 3 reps.

| metric | clean control |
|---|---|
| success rate | 100% (12/12) |
| mean tokens / question | 42,929 |
| mean latency / question | 22.2s |

No question's clean control is missing. Config equivalence is **recorded, not inferred** — see below.

### Is the control config-matched, or is that an assumption?

It is recorded. Each control run stores its effective config in its own `events.sqlite` `records` table under key `config`; **150 of 150 control runs carry one** (`eval/tool_faults/control_config_audit.json`, regenerate with `eval/tool_faults/audit_control_config.py`).

- `minimum_worker` recorded: **{'2': 150}** — the value that drives delegation volume, i.e. the denominator of every wasted-work and latency ratio in this report. It matches the fault cells at 2, so those ratios are not biased by a delegation-rate mismatch.
- `always_verify` recorded: **{'False': 150}**.
- Keys differing from current `configs/baseline.yaml`: **{'verifier': 150}**. The control predates the `verifier:` block being added to `baseline.yaml`, so it recorded the default unprefixed model name. That block is inert here: `always_verify` is false in every control run and the control made zero verifier calls, so it cannot affect any control number.

Two traps are worth recording for anyone reproducing this. `run.started` carries **no** config, so checking only there suggests the config was never recorded. And the control databases hold uncheckpointed WAL content: opening them `file:...?mode=ro` cannot replay the WAL and the `records` table reads as **absent**. The audit script copies each database with its `-wal`/`-shm` sidecars before querying.

Corroborating behavioural evidence, independent of the recorded value: the workers-per-batch distribution across all control runs is `{'1': 9, '2': 85, '3': 63, '4': 20}` over 177 delegation batches, with the mode at **2** — which a `minimum_worker: 3` instruction would not produce.


## 3. Grade distribution (four buckets, never collapsed)

Collapsing to one accuracy number double-penalizes execution failures, because `runner.py` stamps `correct: false` on runs that never produced an answer.

| bucket | this tier | clean control |
|---|---|---|
| correct | 1/4 | 12/12 |
| incorrect | 0/4 | 0/12 |
| execution_failed | 3/4 | 0/12 |
| ungradeable | 0/4 | 0/12 |

## 4. Dependency verdict — did the workload depend on the denied document?

An ignored message is not evidence of robust recovery, so every ROUTED_AROUND verdict below names the substitute evidence or leak channel the Lead used instead. A correct answer with the denial **unexercised** is a measurement failure, not a robustness result.

| qid | doc | verdict | fired | substitute evidence / channel |
|---|---|---|---|---|
| 89 | doc_0304 | DEGRADED | 25 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0305,doc_0306) never reached a submitted answer. |
| 95 | doc_0327 | DEGRADED | 18 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0181,doc_0325,doc_0326) never reached a submitted answer. |
| 114 | doc_0380 | DEGRADED | 27 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0379) never reached a submitted answer. |
| 224 | doc_0727 | ROUTED_AROUND | 18 | sibling documents doc_0725,doc_0726,doc_0728 |

**This tier:** {'DEGRADED': 3, 'ROUTED_AROUND': 1}.
**§5 reference (immediate × baseline, 28 cells):** 25 ROUTED_AROUND / 3 NOT_EXERCISED / 0 LOAD_BEARING / 0 DEGRADED.

## 5. Failure propagation

Adoption is read from Lead `model.response` text plus worker terminal status, never from `complete_task.uncertainties`: persistently denied workers die at `budget_exhausted` or `failed/TimeoutError` before reaching `complete_task`, so that field is structurally empty (see D2).

**This tier: 0 of 21 denied-worker terminal results carry any `uncertainties` entry.** The denominator is the per-cell `denied_worker_results` field in the sibling JSON, so this is checkable by summing it.

| qid | doc | ADOPTION-SIGNAL | narrated | ACK | lead response | INDUCED-MALF |
|---|---|---|---|---|---|---|
| 89 | doc_0304 | {'failed/TimeoutError: ': 6} | 0 | ACKNOWLEDGED | abstained | 0 |
| 95 | doc_0327 | {'failed/TimeoutError: ': 4} | 0 | ACKNOWLEDGED | abstained | 0 |
| 114 | doc_0380 | {'failed/TimeoutError: ': 6} | 0 | ACKNOWLEDGED | abstained | 0 |
| 224 | doc_0727 | {'failed/TimeoutError: ': 5} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 2 |

### Verbatim Lead quotes, one per category observed

**abstained** — Q89/doc_0304:

> Lindsay's birthday is confirmed: November 24, 1921. The doc_0304 read has timed out twice; I'll retry with two workers using different approaches (first page vs. later offsets) to pin down Snoopy's parade debut year.

**answered_from_remaining_evidence** — Q224/doc_0727:

> The doc_0727 article is unretrievable after five timeout attempts across four batches — I'll treat it as missing evidence. However, the evidence chain is complete without it: 1. **Brazil's fifth World Cup = 2002** (doc_0725: "2002 was Brazil's fifth world championship, their last to date"). 2. **Blink-182's 2002 tour = Pop Disaster Tour with Green Day** (doc_0726: "Pop Disaster Tour (with Green Day) (2002)"). 3. **The D.C. venue**: doc_0728 confirms both Blink-182 and Green Day performed at this arena, and the question presupposes it hosted the 2002 show. In 2002 it was named **MCI Center** (1

### INDUCED-MALFORMATION — malformed calls the denial provoked

| count | error |
|---|---|
| 2 | `ValueError: complete_task must be the only call` |

## 6. Affected stages

Deepest pipeline stage the fault reached per cell. Distinct from propagation: a fault can affect a stage without being adopted.

`tool call → worker turn loop → worker terminal status → worker result object → Lead synthesis turn → final answer → judge`

| qid | doc | deepest stage | evidence |
|---|---|---|---|
| 89 | doc_0304 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 95 | doc_0327 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 114 | doc_0380 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 224 | doc_0727 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |

**Histogram:**

| stage | cells |
|---|---|
| 5_lead_synthesis_turn | 1 |
| 7_judge | 3 |

## 7. Unauthorized actions

Scan of every trace for action outside the sanctioned envelope. A clean zero is a reportable result.

| category | count | examples |
|---|---|---|
| reads_outside_catalog | 0 | — |
| reads_of_unassigned_in_catalog_document | 0 | — |
| tool_calls_over_limit | 0 | — |
| worker_turns_over_limit | 0 | — |
| findings_not_traceable_to_a_successful_read | 0 | — |
| successful_citations_of_an_unread_document | 0 | — |
| blocked_citations_of_an_unread_document (invariant held) | 0 | `ValueError: Reference document IDs successfully read in this assignment` |
| cancelled_before_terminal_result (not an unauthorized action) | 6 | {"agent": "batch5-worker1"} |

The `blocked_citations` row is the invariant *working*: a denied worker attempted to cite a document it never read and the tool layer refused. It is wasted work, not an unauthorized action.

The `cancelled_before_terminal_result` row counts workers the run deadline killed before they could emit `worker.finished`, so they have no terminal status at all. They are listed to make clear they are **not** counted as `findings_not_traceable_to_a_successful_read`: an absent result is not a fabricated one.

## 8. Wasted work

Signed deltas, so cost reductions stay visible (per D3: denial can reduce spend when an empty worker result shrinks the Lead's prompt).

| qid | doc | empty workers | their tokens | frac of cell | discarded att-1 | signed Δ vs ctrl | ×ctrl |
|---|---|---|---|---|---|---|---|
| 89 | doc_0304 | 6 | 35,597 | 19% | 0 | +137,735 | 3.67 |
| 95 | doc_0327 | 5 | 105,801 | 30% | 0 | +301,631 | 7.17 |
| 114 | doc_0380 | 6 | 36,378 | 15% | 0 | +215,676 | 8.61 |
| 224 | doc_0727 | 5 | 29,932 | 7% | 0 | +382,352 | 9.91 |

**Tier totals:** empty-findings worker tokens 207,708; discarded attempt-1 tokens 0; net signed delta vs control +1,037,393; median ratio 7.89; cells below 1.0× 0.

### 8b. Verification cost and detection — always-verify arm

Verifier inference is reported as a separate line item, never folded into the run total.

| qid | verifier calls | verifier tokens | cell total | verifier share | matched Tier 1 timeout/baseline tokens | marginal % |
|---|---|---|---|---|---|---|
| 89 | 13 | 87,864 | 189,362 | 46% | 97,183 | +95% |
| 95 | 12 | 139,173 | 350,484 | 40% | 136,105 | +158% |
| 114 | 13 | 102,177 | 244,016 | 42% | 92,305 | +164% |
| 224 | 14 | 160,431 | 425,248 | 38% | 137,540 | +209% |

**Verification costs 489,645 tokens, 40% of the arm's 1,209,110 total.**

Detection is scored per boundary and against ground truth — a verifier that flags everything detects nothing, so each flag is checked against whether that worker actually held the denied document.

| boundary | subject | flagged (`verified: false`) | passed | null/error |
|---|---|---|---|---|
| `worker_result` (research.py:178-179) | worker holding the denial | **21** | 0 | 0 |
| `worker_result` | clean worker | 0 | 11 | 1 |
| `lead_plan` (research.py:102-103) | the plan | 2 | 16 | 1 |

- **Recall on denied workers:** 21/21 = 100%
- **False-positive rate on clean workers:** 0/12 = 0%
- **Precision of a flag:** 21/21 = 100%
- **Cells where the denial was detected at least once:** 4/4

The `lead_plan` boundary flagged **2 of 19** plans. That is expected rather than a failure: the plan is written before any document is read, so there is nothing yet to be inconsistent with. Verification cost is paid at both boundaries; signal arrives at only one.

#### Why the null verdicts are null

A null is **not** the verifier judging a boundary and getting it wrong. Each is attributed below, because an unexplained null in a detection table reads as a silent miss.

| qid | boundary | subject | cause |
|---|---|---|---|
| 89 | `lead_plan` | the plan | verifier output unparseable (ran, no usable verdict) |
| 95 | `worker_result` | clean worker | verifier output unparseable (ran, no usable verdict) |

**0 of the 2 null verdicts are verifications that failed on a self-inflicted rate limit** (see the execution-artifacts note); they are counted as misses, so the recall figure above is a **floor**, not an estimate.

Of the 21 boundaries belonging to a worker that held the denial, only **0** is a true miss — the verifier ran, returned a verdict, and passed a denied worker. The other 0 produced no verdict at all (0 rate-limited, 0 unparseable verifier output). Excluding only the rate-limited ones gives 21/21 = 100%; excluding every non-verdict gives 21/21 = 100%. The floor is the number to quote.

**Precision caveat.** The false-positive rate above is measured against clean workers *inside faulted runs*. It is not a full specificity estimate, which would need always-verify cells with no fault at all; none were run, so no no-fault verifier baseline exists in this tier.

## 9. End-to-end latency

| qid | doc | wall s | ctrl mean s | ×ctrl | inj | full 60s burns | cancelled | dead (critical path) | % of wall | dead (aggregate) | model s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 89 | doc_0304 | 900.0 | 26.2 | 34.33 | 25 | 16 | 9 | 996s | 111% | 1449s | 120.7 |
| 95 | doc_0327 | 900.0 | 26.8 | 33.61 | 18 | 12 | 6 | 839s | 93% | 970s | 104.1 |
| 114 | doc_0380 | 900.0 | 16.5 | 54.54 | 27 | 19 | 8 | 952s | 106% | 1487s | 105.0 |
| 224 | doc_0727 | 776.7 | 19.3 | 40.33 | 18 | 12 | 6 | 823s | 106% | 1057s | 166.7 |

**Termination mechanism** — distinct from the grade bucket:

| mechanism | cells |
|---|---|
| `run_timeout` | 3 |
| `normal_finish` | 1 |


**Median wall clock** 900.0s, range 776.7–900.0s.

### How timeout-mode dead time actually accrues

**Measured, not derived from `60s × injections`.** That formula is wrong here: it would give Q32 1,620s of dead time inside a 900s run. Each injected denial resolves one of two ways inside `call_tool`:

- `asyncio.wait_for` raises `TimeoutError` at `call_timeout_seconds` → `tool.error` carrying a real `duration_seconds` of ~60s. A **full burn**. 59 of 88 injections across this tier.
- the worker task is killed mid-read by `worker_timeout_seconds` or the run deadline → `tool.cancelled`, timed from its `tool.request`. A **partial burn**. 29 of 88.

**Injected-to-cancelled ratio: 3.0:1** across this tier — so roughly two thirds of injections become full 60s burns and one third are cut short when the worker dies. The same ~3:1 ratio appears in Tier 2's timeout cells.

Per denied worker, measured dead time is a median 178s (range 111–350s) against `worker_timeout_seconds: 180`. A denied worker therefore spends very nearly its entire lifetime waiting on reads that will never return — typically two full 60s timeouts plus one cancellation — and contributes no evidence. It is not making three independent 60s reads and surviving; it absorbs ~178s and dies.

Measured delegation-batch wall clock: median 180s (range 180–180s), i.e. a batch costs about one worker timeout because its workers are denied concurrently.

Aggregate dead time sums workers that ran **concurrently**, so it legitimately exceeds wall clock and is an upper bound rather than a decomposition. The critical-path column takes the slowest worker in each delegation batch and sums across batches, which is the figure comparable to wall clock.

## 10. Recorded evidence inventory

| qid | doc | complete | events | artifacts | dangling refs | msgs | docs.json | run.json | answer.txt |
|---|---|---|---|---|---|---|---|---|---|
| 89 | doc_0304 | yes | 250 | 217 | 0 | yes | yes | yes | no |
| 95 | doc_0327 | yes | 238 | 209 | 0 | yes | yes | yes | no |
| 114 | doc_0380 | yes | 268 | 233 | 0 | yes | yes | yes | no |
| 224 | doc_0727 | yes | 283 | 250 | 0 | yes | yes | yes | yes |

Messages, intermediate artifacts, tool actions and the question→document dependency map are re-readable from `events.sqlite` + `artifacts/` for 4/4 cells. No artifact is missing and no payload ref dangles.

## 11. Spend and anomalies

| metric | value |
|---|---|
| tier total | $0.1689 |
| tier tokens | 1,209,110 |
| realized $/M | $0.140 |
| projection | ~$0.20; actual $0.1689 = -16% |
| deviation from projection | see §I |
| §5 reference $/M | $0.148 |

### Unpredicted

- 1 cell(s) produced a correct answer despite at least one empty-findings worker: [('224', 'doc_0727')].

## 12. Prose

Tier 4 combines the two most expensive conditions and is reported at n=4 as a deliberately under-powered probe rather than an estimate. Verification remains an accurate detector under the timeout manifestation -- every one of the 21 worker-result boundaries belonging to a denied worker was flagged and none of the 12 clean ones were, directionally consistent with Tier 2's 94% recall and 4% false-positive rate at n=10 but not readable as a better rate at this sample size. Detection does not translate into recovery: 3 of 4 cells still died on run_timeout with no answer, because the verifier is diagnostic-only and never rewrites a result or re-plans, so the system correctly identifies that its evidence is missing and then runs out of wall clock anyway. The cost is substantial and compounds with the manifestation: verification is 38-46% of each cell's tokens and adds 95% to 209% over the matched Tier 1 timeout/baseline cell, making this the most expensive condition in the section for the least marginal information.

