# Tier 1 — timeout x baseline, strictly serial (10 cells)

`fault_class: accidental` · `fault_effect: denial` — tool-layer evidence denial at the `read_document` boundary. Every cell below is accidental denial; adversarial evidence-corruption conditions are a different fault class, owned by teammates, and are reported separately. Never pool these numbers with those.

Generated 2026-11-04T22:05:47-08:00 · 10 cells

## Running headline

Across section-5-rep1 (28) + tier-2 (30) + tier-3 (10) the system produced **68 of 68 cells correct** — 68 consecutive.

This tier is **2 of 10 correct**.

> STRICTLY SERIAL, one cell at a time, no overlap with any other tier. Wall clock is the primary readout and these are boundary cells against worker_timeout_seconds: 180 and run_timeout_seconds: 900, so contention from a parallel run would shift wall clock and thereby change the dependent variable itself. The mechanism by which dead time accrues is reported as MEASURED from the traces in section 9, not derived from predicted arithmetic.
> Targeting is IDENTICAL to section 5 (one document, persistent: true, max_failures: null, offsets: []); mode: timeout is the only change, timeout_margin left at 1.5, call_timeout_seconds NOT changed. The agreement table in 1a therefore compares MANIFESTATION (timeout here vs immediate in rep 1) at identical targeting -- it is NOT a variance estimate. Tier 3 is the variance control.
> PREDICTION PARTLY HELD, AND NOT IN THE PREDICTED SHAPE. The prediction was a mix of successful completions and run timeouts. A mix did appear (2 completions, 8 failures) but it contains a THIRD mechanism nobody predicted: a Lead model-call timeout (Q27, 424.7s, 2 batches, stop_reason=ModelCallTimeout). Q27's own successful Lead calls in that run took 1.3-1.8s, so the 60s stall is a ~30x outlier against its own run and sits above the 43.32s maximum observed across 1,191 baseline calls; it is consistent with an endpoint stall being fatal because SDK retries are disabled, and should NOT be attributed to the fault. Terminating at exactly 900.0s is run_timeout_seconds firing by definition and is not itself a confirmed prediction.
> Dead time is MEASURED from tool.error(TimeoutError) durations and tool.cancelled timestamps, never as 60s x tool.failure_injected: that formula would give Q32 1,620s of dead time inside a 900s run. See the mechanism subsection under section 9.
> ADOPTION GATE: adoption is read from Lead model.response text plus worker terminal status, never from complete_task.uncertainties (structurally always empty under persistent denial). The gate was corrected twice during this section, both times for FALSE NEGATIVES: first it required the literal document ID or the substring 'read', which scored SILENT turns like 'The Snoopy worker has failed three times on budget' that name the document by catalog title and by worker; then it lacked any pattern for the timeout manifestation, which scored SILENT turns like 'The Cowboys article workers have timed out six times'. All tiers in this section were regenerated under the final gate.
> Single-rep magnitudes; Tier 3 bounds token deviation between identical runs at a median 9.7% (max 51.6%) and wall clock at a median 39.8% (max 83.0%). The categorical split reported here (8 execution-failed / 2 correct) is the kind of quantity Tier 3 found stable at n=1; the per-cell second counts are not.

## 1. Cell table

| qid | doc | mode | scenario | status | termination | grade | att | batches | workers | wall s | tokens | cost | ×ctrl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | timeout | baseline | failed | model_call_timeout | execution_failed | 1 | 2 | 3 | 424.7 | 46,107 | $0.0077 | 1.07 |
| 32 | doc_0115 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 11 | 900.0 | 117,434 | $0.0166 | 1.74 |
| 89 | doc_0304 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 10 | 900.0 | 97,183 | $0.0146 | 1.88 |
| 94 | doc_0324 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 8 | 900.1 | 80,889 | $0.0120 | 1.40 |
| 95 | doc_0327 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 8 | 900.0 | 136,105 | $0.0195 | 2.79 |
| 104 | doc_0352 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 8 | 900.0 | 104,510 | $0.0145 | 2.19 |
| 114 | doc_0380 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 8 | 900.1 | 92,305 | $0.0138 | 3.26 |
| 224 | doc_0727 | timeout | baseline | completed | normal_finish | correct | 1 | 3 | 6 | 550.2 | 137,540 | $0.0168 | 3.21 |
| 251 | doc_0858 | timeout | baseline | completed | normal_finish | correct | 1 | 2 | 4 | 369.8 | 44,935 | $0.0063 | 0.82 |
| 271 | doc_0927 | timeout | baseline | budget_exhausted | run_timeout | execution_failed | 1 | 5 | 11 | 900.0 | 179,130 | $0.0286 | 1.54 |

All rows: `fault_class: accidental`, `fault_effect: denial`. `×ctrl` is tokens over the config-matched §5 control mean for that question.

### 1a. Rep-to-rep agreement

Rep 1 is `eval/tool_faults/reports/section-5-rep1.json`; rep 2 is this tier. Same condition, same targeting, both run strictly serially so neither carries a contention penalty the other lacks. Categorical verdicts are separated from magnitudes below because they behave completely differently.

| qid | doc | verdict r1→r2 | inj r1 | inj r2 | Δinj | tok r1 | tok r2 | tok dev | wall r1 | wall r2 | wall dev | workers r1→r2 | stage r1→r2 | ACK r1→r2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | ROUTED_AROUND→DEGRADED | 34 | 5 | -29 | 123,188 | 46,107 | 91.1% | 50.9 | 424.7 | 157.2% | 8→3 | 5→7 | ACK→ACK |
| 32 | doc_0115 | ROUTED_AROUND→DEGRADED | 45 | 27 | -18 | 195,950 | 117,434 | 50.1% | 94.4 | 900.0 | 162.0% | 13→11 | 5→7 | ACK→ACK |
| 89 | doc_0304 | ROUTED_AROUND→DEGRADED | 48 | 24 | -24 | 182,436 | 97,183 | 61.0% | 77.0 | 900.0 | 168.5% | 13→10 | 5→7 | ACK→ACK |
| 94 | doc_0324 | ROUTED_AROUND→DEGRADED | 26 | 23 | -3 | 122,552 | 80,889 | 41.0% | 55.6 | 900.1 | 176.7% | 7→8 | 6→7 | ACK→ACK |
| 95 | doc_0327 | ROUTED_AROUND→DEGRADED | 30 | 18 | -12 | 161,666 | 136,105 | 17.2% | 56.2 | 900.0 | 176.5% | 8→8 | 5→7 | ACK→ACK |
| 104 | doc_0352 | ROUTED_AROUND→DEGRADED | 51 | 21 | -30 | 153,915 | 104,510 | 38.2% | 42.1 | 900.0 | 182.1% | 12→8 | 5→7 | ACK→ACK |
| 114 | doc_0380 | ROUTED_AROUND→DEGRADED | 30 | 18 | -12 | 133,718 | 92,305 | 36.6% | 78.0 | 900.1 | 168.1% | 8→8 | 5→7 | ACK→ACK |
| 224 | doc_0727 | ROUTED_AROUND→ROUTED_AROUND | 21 | 9 | -12 | 174,305 | 137,540 | 23.6% | 46.0 | 550.2 | 169.2% | 8→6 | 5→5 | ACK→ACK |
| 251 | doc_0858 | ROUTED_AROUND→ROUTED_AROUND | 25 | 6 | -19 | 89,535 | 44,935 | 66.3% | 32.1 | 369.8 | 168.1% | 7→4 | 5→5 | ACK→ACK |
| 271 | doc_0927 | ROUTED_AROUND→DEGRADED | 32 | 24 | -8 | 305,854 | 179,130 | 52.3% | 153.1 | 900.0 | 141.8% | 12→11 | 5→7 | ACK→ACK |

**Categorical agreement — what a single rep CAN carry:**

| quantity | agreement |
|---|---|
| dependency verdict | **2/10** |
| grade bucket | **2/10** |
| deepest affected stage | 2/10 |
| ADOPTION-ACKNOWLEDGED (ACK vs SILENT) | 10/10 |
| lead response sub-category | 1/10 |

**Magnitude agreement — what a single rep CANNOT carry:**

| quantity | median | mean | max |
|---|---|---|---|
| token deviation | 45.5% | 47.7% | 91.1% |
| wall-clock deviation | 168.3% | 167.0% | 182.1% |
| injections, absolute difference | 15.0 | 16.7 | 30 |
| workers spawned, absolute difference | 2.0 | 2.1 | 5 |
| exact injection-count agreement | 0/10 | | |
| exact worker-count agreement | 2/10 | | |

**Caveat every other tier inherits.** A single fault cell is reliable for its dependency verdict and grade bucket, and reasonably reliable for whether the Lead acknowledged the gap. It is NOT reliable for how much the fault cost: token magnitude moves by a median 45.5% (up to 91.1%) and wall clock by a median 168.3% (up to 182.1%) between identical runs. Injection and worker counts never reproduced exactly, so delegation volume is a distribution, not a measurement. Read every single-rep wasted-work and latency figure in Tiers 1, 2 and 4 as a draw from a wide distribution, not a point estimate; differences smaller than roughly 50% in tokens or a factor of two in latency are not separable from run-to-run noise at n=1.

## 2. Clean task success reference (no-fault control)

Source: runs/v2-base1..3 (config-matched baseline, pre-ceb5538 layout). 10 questions × 3 reps.

| metric | clean control |
|---|---|
| success rate | 100% (30/30) |
| mean tokens / question | 55,880 |
| mean latency / question | 25.7s |

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
| correct | 2/10 | 30/30 |
| incorrect | 0/10 | 0/30 |
| execution_failed | 8/10 | 0/30 |
| ungradeable | 0/10 | 0/30 |

## 4. Dependency verdict — did the workload depend on the denied document?

An ignored message is not evidence of robust recovery, so every ROUTED_AROUND verdict below names the substitute evidence or leak channel the Lead used instead. A correct answer with the denial **unexercised** is a measurement failure, not a robustness result.

| qid | doc | verdict | fired | substitute evidence / channel |
|---|---|---|---|---|
| 27 | doc_0102 | DEGRADED | 5 | No answer produced; terminated by `model_call_timeout` after 2 batches. Evidence read from siblings (doc_0101) never reached a submitted answer. |
| 32 | doc_0115 | DEGRADED | 27 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0011,doc_0114) never reached a submitted answer. |
| 89 | doc_0304 | DEGRADED | 24 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0305,doc_0306) never reached a submitted answer. |
| 94 | doc_0324 | DEGRADED | 23 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0323) never reached a submitted answer. |
| 95 | doc_0327 | DEGRADED | 18 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0181,doc_0325) never reached a submitted answer. |
| 104 | doc_0352 | DEGRADED | 21 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0351) never reached a submitted answer. |
| 114 | doc_0380 | DEGRADED | 18 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0379) never reached a submitted answer. |
| 224 | doc_0727 | ROUTED_AROUND | 9 | sibling documents doc_0725,doc_0726,doc_0728; parametric knowledge or catalog metadata (Lead text) |
| 251 | doc_0858 | ROUTED_AROUND | 6 | sibling documents doc_0859,doc_0860 |
| 271 | doc_0927 | DEGRADED | 24 | No answer produced; terminated by `run_timeout` after 5 batches. Evidence read from siblings (doc_0928,doc_0929) never reached a submitted answer. |

**This tier:** {'DEGRADED': 8, 'ROUTED_AROUND': 2}.
**§5 reference (immediate × baseline, 28 cells):** 25 ROUTED_AROUND / 3 NOT_EXERCISED / 0 LOAD_BEARING / 0 DEGRADED.

## 5. Failure propagation

Adoption is read from Lead `model.response` text plus worker terminal status, never from `complete_task.uncertainties`: persistently denied workers die at `budget_exhausted` or `failed/TimeoutError` before reaching `complete_task`, so that field is structurally empty (see D2).

**This tier: 0 of 45 denied-worker terminal results carry any `uncertainties` entry.** The denominator is the per-cell `denied_worker_results` field in the sibling JSON, so this is checkable by summing it.

| qid | doc | ADOPTION-SIGNAL | narrated | ACK | lead response | INDUCED-MALF |
|---|---|---|---|---|---|---|
| 27 | doc_0102 | {'failed/TimeoutError: ': 2} | 0 | ACKNOWLEDGED | abstained | 0 |
| 32 | doc_0115 | {'failed/TimeoutError: ': 7} | 0 | ACKNOWLEDGED | abstained | 0 |
| 89 | doc_0304 | {'failed/TimeoutError: ': 6} | 0 | ACKNOWLEDGED | abstained | 0 |
| 94 | doc_0324 | {'failed/TimeoutError: ': 6} | 0 | ACKNOWLEDGED | abstained | 0 |
| 95 | doc_0327 | {'failed/TimeoutError: ': 4} | 0 | ACKNOWLEDGED | abstained | 1 |
| 104 | doc_0352 | {'failed/TimeoutError: ': 5} | 0 | ACKNOWLEDGED | abstained | 0 |
| 114 | doc_0380 | {'failed/TimeoutError: ': 4} | 0 | ACKNOWLEDGED | abstained | 0 |
| 224 | doc_0727 | {'failed/TimeoutError: ': 3} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 251 | doc_0858 | {'failed/TimeoutError: ': 2} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 0 |
| 271 | doc_0927 | {'failed/TimeoutError: ': 6} | 0 | ACKNOWLEDGED | abstained | 0 |

### Verbatim Lead quotes, one per category observed

**abstained** — Q27/doc_0102:

> Worker 1 confirmed Lawton was a centre-forward at Chelsea (1945–1947), well before squad numbering. Worker 2 timed out, so I'll re-delegate the squad-number article.

**answered_from_parametric_or_catalog** — Q224/doc_0727:

> The Pop Disaster Tour article worker timed out three times, but I have sufficient evidence from the other three documents to answer confidently: 1. **Brazil's fifth World Cup**: 2002 (titles in 1958, 1962, 1970, 1994, 2002 — doc_0725 explicitly states "2002 was Brazil's fifth world championship"). 2. **Blink-182's 2002 tour**: The Pop Disaster Tour, co-headlined with Green Day (doc_0726: "Pop Disaster Tour (with Green Day) (2002)"). 3. **The D.C. venue**: The catalog's venue article is Capital One Arena (doc_0728), which confirms Blink-182 performed there. Its naming history: MCI Center (1997–

**answered_from_remaining_evidence** — Q251/doc_0858:

> The Caldecott article worker timed out again, but I already have sufficient evidence from the successful workers to complete the chain: 1. **Timeline (doc_0859)**: The Sydney Summer Olympics were held September 15 – October 1, 2000, so the book was read around 2000. 2. **"Recently won" the Caldecott (doc_0860)**: *Snowflake Bentley* won the 1999 Caldecott Medal (the article's awards table shows "Caldecott Medal recipient 1999 | Preceded by Rapunzel | Succeeded by Joseph Had a Little Overcoat") — so in 2000 it was indeed the book that had *recently* won the medal. 3. **Plot clues (doc_0860)**: 

### INDUCED-MALFORMATION — malformed calls the denial provoked

| count | error |
|---|---|
| 1 | `ValidationError: 1 validation error for complete_task uncertainties Input should be a valid list [type=list_type, input_value='["The article snapshot ` |

## 6. Affected stages

Deepest pipeline stage the fault reached per cell. Distinct from propagation: a fault can affect a stage without being adopted.

`tool call → worker turn loop → worker terminal status → worker result object → Lead synthesis turn → final answer → judge`

| qid | doc | deepest stage | evidence |
|---|---|---|---|
| 27 | doc_0102 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 32 | doc_0115 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 89 | doc_0304 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 94 | doc_0324 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 95 | doc_0327 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 104 | doc_0352 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 114 | doc_0380 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |
| 224 | doc_0727 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 251 | doc_0858 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 271 | doc_0927 | 7_judge | Run produced no answer, so the judge recorded method=not_answered and runner stamped correct:false against a control that was correct. The fault reached the grade as an EXECUTION FAILURE, not as a wrong answer. |

**Histogram:**

| stage | cells |
|---|---|
| 5_lead_synthesis_turn | 2 |
| 7_judge | 8 |

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
| cancelled_before_terminal_result (not an unauthorized action) | 13 | {"agent": "batch5-worker1"} |

The `blocked_citations` row is the invariant *working*: a denied worker attempted to cite a document it never read and the tool layer refused. It is wasted work, not an unauthorized action.

The `cancelled_before_terminal_result` row counts workers the run deadline killed before they could emit `worker.finished`, so they have no terminal status at all. They are listed to make clear they are **not** counted as `findings_not_traceable_to_a_successful_read`: an absent result is not a fabricated one.

## 8. Wasted work

Signed deltas, so cost reductions stay visible (per D3: denial can reduce spend when an empty worker result shrinks the Lead's prompt).

| qid | doc | empty workers | their tokens | frac of cell | discarded att-1 | signed Δ vs ctrl | ×ctrl |
|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | 2 | 9,884 | 21% | 0 | +2,910 | 1.07 |
| 32 | doc_0115 | 7 | 41,272 | 35% | 0 | +49,975 | 1.74 |
| 89 | doc_0304 | 6 | 35,444 | 36% | 0 | +45,556 | 1.88 |
| 94 | doc_0324 | 6 | 36,712 | 45% | 0 | +23,132 | 1.40 |
| 95 | doc_0327 | 4 | 23,376 | 17% | 0 | +87,252 | 2.79 |
| 104 | doc_0352 | 5 | 28,811 | 28% | 0 | +56,789 | 2.19 |
| 114 | doc_0380 | 4 | 23,007 | 25% | 0 | +63,965 | 3.26 |
| 224 | doc_0727 | 3 | 17,626 | 13% | 0 | +94,644 | 3.21 |
| 251 | doc_0858 | 2 | 11,673 | 26% | 0 | -9,972 | 0.82 |
| 271 | doc_0927 | 6 | 35,510 | 20% | 0 | +63,090 | 1.54 |

**Tier totals:** empty-findings worker tokens 263,315; discarded attempt-1 tokens 0; net signed delta vs control +477,339; median ratio 1.81; cells below 1.0× 1.

## 9. End-to-end latency

| qid | doc | wall s | ctrl mean s | ×ctrl | inj | full 60s burns | cancelled | dead (critical path) | % of wall | dead (aggregate) | model s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | 424.7 | 20.5 | 20.68 | 5 | 4 | 1 | 298s | 70% | 298s | 34.7 |
| 32 | doc_0115 | 900.0 | 37.5 | 24.01 | 27 | 18 | 9 | 836s | 93% | 1494s | 105.0 |
| 89 | doc_0304 | 900.0 | 26.2 | 34.33 | 24 | 16 | 8 | 873s | 97% | 1389s | 46.0 |
| 94 | doc_0324 | 900.1 | 32.8 | 27.42 | 23 | 16 | 7 | 989s | 110% | 1344s | 40.5 |
| 95 | doc_0327 | 900.0 | 26.8 | 33.61 | 18 | 12 | 6 | 877s | 97% | 1044s | 50.2 |
| 104 | doc_0352 | 900.0 | 12.8 | 70.54 | 21 | 14 | 7 | 883s | 98% | 1231s | 30.0 |
| 114 | doc_0380 | 900.1 | 16.5 | 54.54 | 18 | 12 | 6 | 882s | 98% | 1051s | 30.7 |
| 224 | doc_0727 | 550.2 | 19.3 | 28.57 | 9 | 6 | 3 | 535s | 97% | 535s | 39.5 |
| 251 | doc_0858 | 369.8 | 19.2 | 19.27 | 6 | 4 | 2 | 355s | 96% | 355s | 22.9 |
| 271 | doc_0927 | 900.0 | 45.5 | 19.77 | 24 | 16 | 8 | 852s | 95% | 1349s | 108.5 |

**Termination mechanism** — distinct from the grade bucket:

| mechanism | cells |
|---|---|
| `run_timeout` | 7 |
| `normal_finish` | 2 |
| `model_call_timeout` | 1 |


**Median wall clock** 900.0s, range 369.8–900.1s.

### How timeout-mode dead time actually accrues

**Measured, not derived from `60s × injections`.** That formula is wrong here: it would give Q32 1,620s of dead time inside a 900s run. Each injected denial resolves one of two ways inside `call_tool`:

- `asyncio.wait_for` raises `TimeoutError` at `call_timeout_seconds` → `tool.error` carrying a real `duration_seconds` of ~60s. A **full burn**. 118 of 175 injections across this tier.
- the worker task is killed mid-read by `worker_timeout_seconds` or the run deadline → `tool.cancelled`, timed from its `tool.request`. A **partial burn**. 57 of 175.

**Injected-to-cancelled ratio: 3.1:1** across this tier — so roughly two thirds of injections become full 60s burns and one third are cut short when the worker dies. The same ~3:1 ratio appears in Tier 2's timeout cells.

Per denied worker, measured dead time is a median 178s (range 120–238s) against `worker_timeout_seconds: 180`. A denied worker therefore spends very nearly its entire lifetime waiting on reads that will never return — typically two full 60s timeouts plus one cancellation — and contributes no evidence. It is not making three independent 60s reads and surviving; it absorbs ~178s and dies.

Measured delegation-batch wall clock: median 180s (range 180–180s), i.e. a batch costs about one worker timeout because its workers are denied concurrently.

Aggregate dead time sums workers that ran **concurrently**, so it legitimately exceeds wall clock and is an upper bound rather than a decomposition. The critical-path column takes the slowest worker in each delegation batch and sums across batches, which is the figure comparable to wall clock.

## 10. Recorded evidence inventory

| qid | doc | complete | events | artifacts | dangling refs | msgs | docs.json | run.json | answer.txt |
|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | yes | 71 | 66 | 0 | yes | yes | yes | no |
| 32 | doc_0115 | yes | 223 | 185 | 0 | yes | yes | yes | no |
| 89 | doc_0304 | yes | 199 | 167 | 0 | yes | yes | yes | no |
| 94 | doc_0324 | yes | 177 | 147 | 0 | yes | yes | yes | no |
| 95 | doc_0327 | yes | 169 | 147 | 0 | yes | yes | yes | no |
| 104 | doc_0352 | yes | 174 | 149 | 0 | yes | yes | yes | no |
| 114 | doc_0380 | yes | 163 | 136 | 0 | yes | yes | yes | no |
| 224 | doc_0727 | yes | 136 | 123 | 0 | yes | yes | yes | yes |
| 251 | doc_0858 | yes | 87 | 80 | 0 | yes | yes | yes | yes |
| 271 | doc_0927 | yes | 224 | 188 | 0 | yes | yes | yes | no |

Messages, intermediate artifacts, tool actions and the question→document dependency map are re-readable from `events.sqlite` + `artifacts/` for 10/10 cells. No artifact is missing and no payload ref dangles.

## 11. Spend and anomalies

| metric | value |
|---|---|
| tier total | $0.1505 |
| tier tokens | 1,036,138 |
| realized $/M | $0.145 |
| projection | ~$0.25 on the section-5 token profile; actual $0.1505 = -40%, because 8 of 10 runs were killed before spending their token budget |
| deviation from projection | see §I |
| §5 reference $/M | $0.148 |

### Unpredicted

- Schema validation errors inside worker tool calls: ['ValidationError: 1 validation error for complete_task uncertainties Input should be a vali'].
- 2 cell(s) produced a correct answer despite at least one empty-findings worker: [('224', 'doc_0727'), ('251', 'doc_0858')].
- 1 cell(s) returned `usage_complete: false`, so `total_cost` was null and cost is token-derived at config rates (cached input priced as uncached, so a slight over-estimate): [('27', 'doc_0102', 2)] as (qid, doc, unreported_calls).

## 12. Prose

Tier 1 is the decisive contrast of this section. Holding the denied document, persistence and targeting identical to section 5 and changing only the manifestation from an immediate tool error to a timeout, the system goes from 68 of 68 cells correct across section 5 and Tiers 2-3 to 2 of 10 here, and it fails by not finishing rather than by answering wrong: 8 of 10 cells produced no answer at all (7 run_timeout at 900s, 1 Lead model-call timeout at 424.7s) and were then stamped correct:false by runner.py despite never submitting an answer, which is exactly why the four grade buckets must not be collapsed. The mechanism is dead time, measured rather than derived: each denied worker absorbs a median 178s against worker_timeout_seconds: 180 -- typically two full 60s tool timeouts plus one cancellation when it is killed mid-read -- a delegation batch costs a flat 180s, and critical-path dead time is 70-110% of wall clock, so essentially all elapsed time in these runs is spent waiting on reads that will never return. Latency rises 19x to 70x over the clean control while token spend actually FALLS relative to the immediate manifestation (median 1.81x vs 3.07x of clean) because the runs are killed before they can spend, and the two cells that did complete are the two that absorbed the fewest injections (6 and 9 against 18-27 elsewhere).

