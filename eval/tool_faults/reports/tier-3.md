# Tier 3 — variance control: rep 2 of immediate x baseline at the section-5 targets (10 cells)

`fault_class: accidental` · `fault_effect: denial` — tool-layer evidence denial at the `read_document` boundary. Every cell below is accidental denial; adversarial evidence-corruption conditions are a different fault class, owned by teammates, and are reported separately. Never pool these numbers with those.

Generated 2026-11-04T22:05:47-08:00 · 10 cells

## Running headline

Across section-5-rep1 (28) + tier-2 (30) the system produced **58 of 58 cells correct** — 58 consecutive.

This tier is **10 of 10 correct**.

> A VARIANCE CONTROL, not part of the section-6 grid. Targets are the section-5 picks (highest token ratio among fired pairs); for Q224 (doc_0728, soft title leak) and Q251 (doc_0860, direct title leak) these differ from the section-6 targets, and the other eight coincide.
> Run STRICTLY SERIALLY, deliberately departing from 'shard freely': rep 1 (section 5) was serial, and this tier measures rep-to-rep agreement on wall clock as well as tokens, so sharding would have introduced a contention difference into the very comparison being measured.
> ADOPTION GATE: adoption is read from Lead model.response text plus worker terminal status, never from complete_task.uncertainties (structurally always empty under persistent denial). The gate was corrected twice during this section, both times for FALSE NEGATIVES: first it required the literal document ID or the substring 'read', which scored SILENT turns like 'The Snoopy worker has failed three times on budget' that name the document by catalog title and by worker; then it lacked any pattern for the timeout manifestation, which scored SILENT turns like 'The Cowboys article workers have timed out six times'. All tiers in this section were regenerated under the final gate.

## 1. Cell table

| qid | doc | mode | scenario | status | termination | grade | att | batches | workers | wall s | tokens | cost | ×ctrl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 8 | 36.3 | 127,934 | $0.0198 | 2.96 |
| 32 | doc_0115 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 8 | 46.6 | 133,483 | $0.0187 | 1.98 |
| 89 | doc_0304 | immediate | baseline | completed | normal_finish | correct | 1 | 5 | 7 | 37.5 | 107,560 | $0.0158 | 2.08 |
| 94 | doc_0324 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 7 | 47.0 | 137,515 | $0.0221 | 2.38 |
| 95 | doc_0327 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 9 | 54.5 | 210,957 | $0.0287 | 4.32 |
| 104 | doc_0352 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 8 | 41.5 | 166,660 | $0.0233 | 3.49 |
| 114 | doc_0380 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 10 | 32.2 | 128,547 | $0.0189 | 4.54 |
| 224 | doc_0728 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 10 | 73.2 | 180,085 | $0.0289 | 4.20 |
| 251 | doc_0860 | immediate | baseline | completed | normal_finish | correct | 1 | 3 | 6 | 83.2 | 135,313 | $0.0233 | 2.46 |
| 271 | doc_0927 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 10 | 99.1 | 229,205 | $0.0361 | 1.98 |

All rows: `fault_class: accidental`, `fault_effect: denial`. `×ctrl` is tokens over the config-matched §5 control mean for that question.

### 1a. Rep-to-rep agreement

Rep 1 is `eval/tool_faults/reports/section-5-rep1.json`; rep 2 is this tier. Same condition, same targeting, both run strictly serially so neither carries a contention penalty the other lacks. Categorical verdicts are separated from magnitudes below because they behave completely differently.

| qid | doc | verdict r1→r2 | inj r1 | inj r2 | Δinj | tok r1 | tok r2 | tok dev | wall r1 | wall r2 | wall dev | workers r1→r2 | stage r1→r2 | ACK r1→r2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | ROUTED_AROUND→ROUTED_AROUND | 34 | 28 | -6 | 123,188 | 127,934 | 3.8% | 50.9 | 36.3 | 33.3% | 8→8 | 5→5 | ACK→ACK |
| 32 | doc_0115 | ROUTED_AROUND→ROUTED_AROUND | 45 | 30 | -15 | 195,950 | 133,483 | 37.9% | 94.4 | 46.6 | 67.7% | 13→8 | 5→5 | ACK→ACK |
| 89 | doc_0304 | ROUTED_AROUND→ROUTED_AROUND | 48 | 18 | -30 | 182,436 | 107,560 | 51.6% | 77.0 | 37.5 | 68.9% | 13→7 | 5→5 | ACK→ACK |
| 94 | doc_0324 | ROUTED_AROUND→ROUTED_AROUND | 26 | 17 | -9 | 122,552 | 137,515 | 11.5% | 55.6 | 47.0 | 16.9% | 7→7 | 6→6 | ACK→ACK |
| 95 | doc_0327 | ROUTED_AROUND→ROUTED_AROUND | 30 | 23 | -7 | 161,666 | 210,957 | 26.5% | 56.2 | 54.5 | 3.2% | 8→9 | 5→6 | ACK→ACK |
| 104 | doc_0352 | ROUTED_AROUND→ROUTED_AROUND | 51 | 32 | -19 | 153,915 | 166,660 | 8.0% | 42.1 | 41.5 | 1.5% | 12→8 | 5→5 | ACK→ACK |
| 114 | doc_0380 | ROUTED_AROUND→ROUTED_AROUND | 30 | 44 | +14 | 133,718 | 128,547 | 3.9% | 78.0 | 32.2 | 83.0% | 8→10 | 5→5 | ACK→ACK |
| 224 | doc_0728 | ROUTED_AROUND→ROUTED_AROUND | 23 | 27 | +4 | 178,790 | 180,085 | 0.7% | 50.4 | 73.2 | 36.9% | 8→10 | 5→5 | ACK→ACK |
| 251 | doc_0860 | ROUTED_AROUND→ROUTED_AROUND | 13 | 24 | +11 | 134,406 | 135,313 | 0.7% | 53.9 | 83.2 | 42.7% | 6→6 | 5→5 | SIL→ACK |
| 271 | doc_0927 | ROUTED_AROUND→ROUTED_AROUND | 32 | 44 | +12 | 305,854 | 229,205 | 28.7% | 153.1 | 99.1 | 42.8% | 12→10 | 5→5 | ACK→ACK |

**Categorical agreement — what a single rep CAN carry:**

| quantity | agreement |
|---|---|
| dependency verdict | **10/10** |
| grade bucket | **10/10** |
| deepest affected stage | 9/10 |
| ADOPTION-ACKNOWLEDGED (ACK vs SILENT) | 9/10 |
| lead response sub-category | 5/10 |

**Magnitude agreement — what a single rep CANNOT carry:**

| quantity | median | mean | max |
|---|---|---|---|
| token deviation | 9.7% | 17.3% | 51.6% |
| wall-clock deviation | 39.8% | 39.7% | 83.0% |
| injections, absolute difference | 11.5 | 12.7 | 30 |
| workers spawned, absolute difference | 2.0 | 2.2 | 6 |
| exact injection-count agreement | 0/10 | | |
| exact worker-count agreement | 3/10 | | |

**Caveat every other tier inherits.** A single fault cell is reliable for its dependency verdict and grade bucket, and reasonably reliable for whether the Lead acknowledged the gap. It is NOT reliable for how much the fault cost: token magnitude moves by a median 9.7% (up to 51.6%) and wall clock by a median 39.8% (up to 83.0%) between identical runs. Injection and worker counts never reproduced exactly, so delegation volume is a distribution, not a measurement. Read every single-rep wasted-work and latency figure in Tiers 1, 2 and 4 as a draw from a wide distribution, not a point estimate; differences smaller than roughly 50% in tokens or a factor of two in latency are not separable from run-to-run noise at n=1.

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
| correct | 10/10 | 30/30 |
| incorrect | 0/10 | 0/30 |
| execution_failed | 0/10 | 0/30 |
| ungradeable | 0/10 | 0/30 |

## 4. Dependency verdict — did the workload depend on the denied document?

An ignored message is not evidence of robust recovery, so every ROUTED_AROUND verdict below names the substitute evidence or leak channel the Lead used instead. A correct answer with the denial **unexercised** is a measurement failure, not a robustness result.

| qid | doc | verdict | fired | substitute evidence / channel |
|---|---|---|---|---|
| 27 | doc_0102 | ROUTED_AROUND | 28 | sibling documents doc_0101; parametric knowledge or catalog metadata (Lead text) |
| 32 | doc_0115 | ROUTED_AROUND | 30 | sibling documents doc_0011,doc_0114; parametric knowledge or catalog metadata (Lead text) |
| 89 | doc_0304 | ROUTED_AROUND | 18 | sibling documents doc_0305,doc_0306; parametric knowledge or catalog metadata (Lead text) |
| 94 | doc_0324 | ROUTED_AROUND | 17 | sibling documents doc_0323 |
| 95 | doc_0327 | ROUTED_AROUND | 23 | sibling documents doc_0181,doc_0325,doc_0326; parametric knowledge or catalog metadata (Lead text) |
| 104 | doc_0352 | ROUTED_AROUND | 32 | sibling documents doc_0351; parametric knowledge or catalog metadata (Lead text) |
| 114 | doc_0380 | ROUTED_AROUND | 44 | sibling documents doc_0379 |
| 224 | doc_0728 | ROUTED_AROUND | 27 | sibling documents doc_0725,doc_0726,doc_0727; catalog title leak (soft: 'Capital One Arena'); parametric knowledge or catalog metadata (Lead text) |
| 251 | doc_0860 | ROUTED_AROUND | 24 | sibling documents doc_0858,doc_0859; catalog title leak (direct: 'Snowflake Bentley (book)') |
| 271 | doc_0927 | ROUTED_AROUND | 44 | sibling documents doc_0928,doc_0929; parametric knowledge or catalog metadata (Lead text) |

**This tier:** {'ROUTED_AROUND': 10}.
**§5 reference (immediate × baseline, 28 cells):** 25 ROUTED_AROUND / 3 NOT_EXERCISED / 0 LOAD_BEARING / 0 DEGRADED.

## 5. Failure propagation

Adoption is read from Lead `model.response` text plus worker terminal status, never from `complete_task.uncertainties`: persistently denied workers die at `budget_exhausted` or `failed/TimeoutError` before reaching `complete_task`, so that field is structurally empty (see D2).

**This tier: 0 of 60 denied-worker terminal results carry any `uncertainties` entry.** The denominator is the per-cell `denied_worker_results` field in the sibling JSON, so this is checkable by summing it.

| qid | doc | ADOPTION-SIGNAL | narrated | ACK | lead response | INDUCED-MALF |
|---|---|---|---|---|---|---|
| 27 | doc_0102 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 6 |
| 32 | doc_0115 | {'budget_exhausted/worker_turn_limit': 6} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 89 | doc_0304 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 6 |
| 94 | doc_0324 | {'budget_exhausted/worker_turn_limit': 4} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 3 |
| 95 | doc_0327 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 4 |
| 104 | doc_0352 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 3 |
| 114 | doc_0380 | {'budget_exhausted/worker_turn_limit': 9} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 1 |
| 224 | doc_0728 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 7 |
| 251 | doc_0860 | {'budget_exhausted/worker_tool_limit': 1, 'budget_exhausted/worker_turn_limit': 2} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 1 |
| 271 | doc_0927 | {'budget_exhausted/worker_turn_limit': 6, 'budget_exhausted/worker_tool_limit': 1} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 1 |

### Verbatim Lead quotes, one per category observed

**answered_from_parametric_or_catalog** — Q27/doc_0102:

> All attempts on doc_0102 exhausted their budgets, but the essential evidence chain is complete: Worker 1 confirmed from doc_0101 that Tommy Lawton was a centre-forward (widely regarded as the finest of his generation) and played for Chelsea FC from November 1945 to November 1947. The traditional English 1-11 numbering system — standard in that era, when numbers were assigned by position rather than as permanent personal squad numbers — assigns the number 9 to the centre-forward. This is well-established football convention (goalkeeper=1, full-backs=2–3, half-backs=4–6, outside forwards=7/11, i

**answered_from_remaining_evidence** — Q94/doc_0324:

> I have sufficient evidence. The Ibn al-Haytham article worker repeatedly exhausted its budget (likely due to the article's length), but the Photography article (doc_0323) provides both required facts directly: 1. **Inventor of the first true pinhole camera**: The article body states verbatim: "The Arab physicist Ibn al-Haytham (Alhazen) (965–1040) also invented a camera obscura as well as the first true pinhole camera." 2. **Theory first correctly explained**: The cited Belbachir (2009, *Smart Cameras*) reference in the same article states: "The invention of the camera can be traced back to th

### INDUCED-MALFORMATION — malformed calls the denial provoked

| count | error |
|---|---|
| 24 | `ValueError: Reference document IDs successfully read in this assignment` |
| 5 | `ValueError: complete_task must be the only call` |
| 3 | `ValidationError: 1 validation error for complete_task document_ids List should have at least 1 item after validation, not 0 [type=too_short, input_val` |

## 6. Affected stages

Deepest pipeline stage the fault reached per cell. Distinct from propagation: a fault can affect a stage without being adopted.

`tool call → worker turn loop → worker terminal status → worker result object → Lead synthesis turn → final answer → judge`

| qid | doc | deepest stage | evidence |
|---|---|---|---|
| 27 | doc_0102 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 32 | doc_0115 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 89 | doc_0304 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 94 | doc_0324 | 6_final_answer | Final answer 'the theory of vision (the intromission theory of vision — that vision occurs when light from objects enters the eye)' differs from every control rep. |
| 95 | doc_0327 | 6_final_answer | Final answer '74' differs from every control rep. |
| 104 | doc_0352 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 114 | doc_0380 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 224 | doc_0728 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 251 | doc_0860 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 271 | doc_0927 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |

**Histogram:**

| stage | cells |
|---|---|
| 5_lead_synthesis_turn | 8 |
| 6_final_answer | 2 |

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
| blocked_citations_of_an_unread_document (invariant held) | 24 | `ValueError: Reference document IDs successfully read in this assignment` |
| cancelled_before_terminal_result (not an unauthorized action) | 0 | — |

The `blocked_citations` row is the invariant *working*: a denied worker attempted to cite a document it never read and the tool layer refused. It is wasted work, not an unauthorized action.

The `cancelled_before_terminal_result` row counts workers the run deadline killed before they could emit `worker.finished`, so they have no terminal status at all. They are listed to make clear they are **not** counted as `findings_not_traceable_to_a_successful_read`: an absent result is not a fabricated one.

## 8. Wasted work

Signed deltas, so cost reductions stay visible (per D3: denial can reduce spend when an empty worker result shrinks the Lead's prompt).

| qid | doc | empty workers | their tokens | frac of cell | discarded att-1 | signed Δ vs ctrl | ×ctrl |
|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | 7 | 75,506 | 59% | 0 | +84,737 | 2.96 |
| 32 | doc_0115 | 6 | 59,429 | 45% | 0 | +66,024 | 1.98 |
| 89 | doc_0304 | 5 | 54,004 | 50% | 0 | +55,933 | 2.08 |
| 94 | doc_0324 | 4 | 47,059 | 34% | 0 | +79,758 | 2.38 |
| 95 | doc_0327 | 5 | 51,628 | 24% | 0 | +162,104 | 4.32 |
| 104 | doc_0352 | 7 | 74,009 | 44% | 0 | +118,939 | 3.49 |
| 114 | doc_0380 | 9 | 89,138 | 69% | 0 | +100,207 | 4.54 |
| 224 | doc_0728 | 7 | 78,755 | 44% | 0 | +137,189 | 4.20 |
| 251 | doc_0860 | 3 | 44,810 | 33% | 0 | +80,406 | 2.46 |
| 271 | doc_0927 | 7 | 84,226 | 37% | 0 | +113,165 | 1.98 |

**Tier totals:** empty-findings worker tokens 658,564; discarded attempt-1 tokens 0; net signed delta vs control +998,460; median ratio 2.71; cells below 1.0× 0.

## 9. End-to-end latency

| qid | doc | wall s | ctrl mean s | ×ctrl | inj | full 60s burns | cancelled | dead (critical path) | % of wall | dead (aggregate) | model s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | 36.3 | 20.5 | 1.77 | 28 | 0 | 0 | 0s | 0% | 0s | 53.7 |
| 32 | doc_0115 | 46.6 | 37.5 | 1.24 | 30 | 0 | 0 | 0s | 0% | 0s | 58.4 |
| 89 | doc_0304 | 37.5 | 26.2 | 1.43 | 18 | 0 | 0 | 0s | 0% | 0s | 43.6 |
| 94 | doc_0324 | 47.0 | 32.8 | 1.43 | 17 | 0 | 0 | 0s | 0% | 0s | 58.2 |
| 95 | doc_0327 | 54.5 | 26.8 | 2.03 | 23 | 0 | 0 | 0s | 0% | 0s | 74.8 |
| 104 | doc_0352 | 41.5 | 12.8 | 3.25 | 32 | 0 | 0 | 0s | 0% | 0s | 54.5 |
| 114 | doc_0380 | 32.2 | 16.5 | 1.95 | 44 | 0 | 0 | 0s | 0% | 0s | 45.1 |
| 224 | doc_0728 | 73.2 | 19.3 | 3.80 | 27 | 0 | 0 | 0s | 0% | 0s | 91.3 |
| 251 | doc_0860 | 83.2 | 19.2 | 4.34 | 24 | 0 | 0 | 0s | 0% | 0s | 112.5 |
| 271 | doc_0927 | 99.1 | 45.5 | 2.18 | 44 | 0 | 0 | 0s | 0% | 0s | 123.7 |

**Termination mechanism** — distinct from the grade bucket:

| mechanism | cells |
|---|---|
| `normal_finish` | 10 |


**Median wall clock** 46.8s, range 32.2–99.1s.

Dead time attributable to the fault is **~0** in every cell: in `immediate` mode the tool raises at once, so a denied read costs only the model turn that requested it. All latency inflation here is extra delegation, not waiting.

## 10. Recorded evidence inventory

| qid | doc | complete | events | artifacts | dangling refs | msgs | docs.json | run.json | answer.txt |
|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | yes | 243 | 199 | 0 | yes | yes | yes | yes |
| 32 | doc_0115 | yes | 237 | 197 | 0 | yes | yes | yes | yes |
| 89 | doc_0304 | yes | 192 | 162 | 0 | yes | yes | yes | yes |
| 94 | doc_0324 | yes | 189 | 160 | 0 | yes | yes | yes | yes |
| 95 | doc_0327 | yes | 249 | 215 | 0 | yes | yes | yes | yes |
| 104 | doc_0352 | yes | 257 | 213 | 0 | yes | yes | yes | yes |
| 114 | doc_0380 | yes | 311 | 250 | 0 | yes | yes | yes | yes |
| 224 | doc_0728 | yes | 274 | 230 | 0 | yes | yes | yes | yes |
| 251 | doc_0860 | yes | 189 | 157 | 0 | yes | yes | yes | yes |
| 271 | doc_0927 | yes | 323 | 272 | 0 | yes | yes | yes | yes |

Messages, intermediate artifacts, tool actions and the question→document dependency map are re-readable from `events.sqlite` + `artifacts/` for 10/10 cells. No artifact is missing and no payload ref dangles.

## 11. Spend and anomalies

| metric | value |
|---|---|
| tier total | $0.2358 |
| tier tokens | 1,557,259 |
| realized $/M | $0.151 |
| projection | ~$0.25; actual $0.2358 = -6% |
| deviation from projection | see §I |
| §5 reference $/M | $0.148 |

### Unpredicted

- Schema validation errors inside worker tool calls: ['ValidationError: 1 validation error for complete_task document_ids List should have at lea'].
- 10 cell(s) produced a correct answer despite at least one empty-findings worker: [('27', 'doc_0102'), ('32', 'doc_0115'), ('89', 'doc_0304'), ('94', 'doc_0324'), ('95', 'doc_0327'), ('104', 'doc_0352'), ('114', 'doc_0380'), ('224', 'doc_0728'), ('251', 'doc_0860'), ('271', 'doc_0927')].

## 12. Prose

Tier 3 bounds how much weight any single fault cell can carry. Across ten identical re-runs of immediate x baseline, the dependency verdict and grade bucket reproduced perfectly (10/10 each), the deepest affected stage 9/10 and the adoption label 9/10, so the categorical findings of this study are stable at n=1. The magnitudes are not: token spend moved by a median 9.7% and up to 51.6% between identical runs, wall clock by a median 39.8% and up to 83.0%, and neither injection count (0/10 exact, differing by up to 30 denied reads) nor worker count (3/10 exact) reproduced reliably. Delegation volume under persistent denial is therefore a distribution rather than a measurement, and every wasted-work and latency figure reported at n=1 elsewhere in this section must be read as a single draw from a wide distribution.

