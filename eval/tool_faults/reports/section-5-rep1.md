# Section 5 rep 1 — immediate x baseline, all 28 (question, document) pairs, rescored through the tier reporter

`fault_class: accidental` · `fault_effect: denial` — tool-layer evidence denial at the `read_document` boundary. Every cell below is accidental denial; adversarial evidence-corruption conditions are a different fault class, owned by teammates, and are reported separately. Never pool these numbers with those.

Generated 2026-11-04T22:05:46-08:00 · 28 cells

> Not a section-6 tier. Section 5's 28-cell dependency sweep rescored with the tier reporter so Tier 3 can compare rep 1 and rep 2 on identical definitions. The canonical section-5 artifact remains eval/tool_faults/fault_propagation_report.json.
> ADOPTION GATE: adoption is read from Lead model.response text plus worker terminal status, never from complete_task.uncertainties (structurally always empty under persistent denial). The gate was corrected twice during this section, both times for FALSE NEGATIVES: first it required the literal document ID or the substring 'read', which scored SILENT turns like 'The Snoopy worker has failed three times on budget' that name the document by catalog title and by worker; then it lacked any pattern for the timeout manifestation, which scored SILENT turns like 'The Cowboys article workers have timed out six times'. All tiers in this section were regenerated under the final gate.

## 1. Cell table

| qid | doc | mode | scenario | status | termination | grade | att | batches | workers | wall s | tokens | cost | ×ctrl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0101 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 8 | 49.9 | 106,950 | $0.0165 | 2.48 |
| 27 | doc_0102 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 8 | 50.9 | 123,188 | $0.0188 | 2.85 |
| 32 | doc_0011 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 7 | 45.8 | 115,073 | $0.0170 | 1.71 |
| 32 | doc_0114 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 10 | 78.1 | 161,888 | $0.0236 | 2.40 |
| 32 | doc_0115 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 13 | 94.4 | 195,950 | $0.0301 | 2.90 |
| 89 | doc_0304 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 13 | 77.0 | 182,436 | $0.0277 | 3.53 |
| 89 | doc_0305 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 3 | 13.2 | 41,742 | $0.0063 | 0.81 |
| 89 | doc_0306 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 10 | 69.1 | 150,677 | $0.0221 | 2.92 |
| 94 | doc_0323 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 2 | 19.8 | 46,337 | $0.0065 | 0.80 |
| 94 | doc_0324 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 7 | 55.6 | 122,552 | $0.0203 | 2.12 |
| 95 | doc_0181 | immediate | baseline | completed | normal_finish | correct | 1 | 2 | 4 | 37.0 | 101,009 | $0.0141 | 2.07 |
| 95 | doc_0325 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 2 | 12.8 | 37,134 | $0.0058 | 0.76 |
| 95 | doc_0326 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 2 | 20.0 | 49,496 | $0.0067 | 1.01 |
| 95 | doc_0327 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 8 | 56.2 | 161,666 | $0.0224 | 3.31 |
| 104 | doc_0351 | immediate | baseline | completed | normal_finish | correct | 1 | 3 | 6 | 32.8 | 109,178 | $0.0157 | 2.29 |
| 104 | doc_0352 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 12 | 42.1 | 153,915 | $0.0231 | 3.23 |
| 114 | doc_0379 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 7 | 40.8 | 99,359 | $0.0142 | 3.51 |
| 114 | doc_0380 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 8 | 78.0 | 133,718 | $0.0196 | 4.72 |
| 224 | doc_0725 | immediate | baseline | completed | normal_finish | correct | 1 | 2 | 5 | 41.8 | 131,817 | $0.0183 | 3.07 |
| 224 | doc_0726 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 3 | 18.4 | 45,619 | $0.0072 | 1.06 |
| 224 | doc_0727 | immediate | baseline | completed | normal_finish | correct | 1 | 3 | 8 | 46.0 | 174,305 | $0.0233 | 4.06 |
| 224 | doc_0728 | immediate | baseline | completed | normal_finish | correct | 1 | 4 | 8 | 50.4 | 178,790 | $0.0264 | 4.17 |
| 251 | doc_0858 | immediate | baseline | completed | normal_finish | correct | 1 | 3 | 7 | 32.1 | 89,535 | $0.0137 | 1.63 |
| 251 | doc_0859 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 3 | 21.0 | 54,968 | $0.0085 | 1.00 |
| 251 | doc_0860 | immediate | baseline | completed | normal_finish | correct | 1 | 3 | 6 | 53.9 | 134,406 | $0.0216 | 2.45 |
| 271 | doc_0927 | immediate | baseline | completed | normal_finish | correct | 1 | 6 | 12 | 153.1 | 305,854 | $0.0472 | 2.64 |
| 271 | doc_0928 | immediate | baseline | completed | normal_finish | correct | 1 | 1 | 3 | 25.9 | 80,825 | $0.0114 | 0.70 |
| 271 | doc_0929 | immediate | baseline | completed | normal_finish | correct | 1 | 3 | 5 | 44.0 | 130,438 | $0.0192 | 1.12 |

All rows: `fault_class: accidental`, `fault_effect: denial`. `×ctrl` is tokens over the config-matched §5 control mean for that question.

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
| correct | 28/28 | 30/30 |
| incorrect | 0/28 | 0/30 |
| execution_failed | 0/28 | 0/30 |
| ungradeable | 0/28 | 0/30 |

## 4. Dependency verdict — did the workload depend on the denied document?

An ignored message is not evidence of robust recovery, so every ROUTED_AROUND verdict below names the substitute evidence or leak channel the Lead used instead. A correct answer with the denial **unexercised** is a measurement failure, not a robustness result.

| qid | doc | verdict | fired | substitute evidence / channel |
|---|---|---|---|---|
| 27 | doc_0101 | ROUTED_AROUND | 34 | sibling documents doc_0102 |
| 27 | doc_0102 | ROUTED_AROUND | 34 | sibling documents doc_0101 |
| 32 | doc_0011 | ROUTED_AROUND | 24 | sibling documents doc_0114,doc_0115; parametric knowledge or catalog metadata (Lead text) |
| 32 | doc_0114 | ROUTED_AROUND | 36 | sibling documents doc_0011,doc_0115; parametric knowledge or catalog metadata (Lead text) |
| 32 | doc_0115 | ROUTED_AROUND | 45 | sibling documents doc_0011,doc_0114 |
| 89 | doc_0304 | ROUTED_AROUND | 48 | sibling documents doc_0305,doc_0306 |
| 89 | doc_0305 | ROUTED_AROUND | 5 | sibling documents doc_0304,doc_0306 |
| 89 | doc_0306 | ROUTED_AROUND | 29 | sibling documents doc_0304,doc_0305; parametric knowledge or catalog metadata (Lead text) |
| 94 | doc_0323 | ROUTED_AROUND | 5 | sibling documents doc_0324 |
| 94 | doc_0324 | ROUTED_AROUND | 26 | sibling documents doc_0323; parametric knowledge or catalog metadata (Lead text) |
| 95 | doc_0181 | ROUTED_AROUND | 10 | sibling documents doc_0325,doc_0327 |
| 95 | doc_0325 | NOT_EXERCISED | 0 | **MEASUREMENT FAILURE — fault never fired; no worker was assigned it** |
| 95 | doc_0326 | NOT_EXERCISED | 0 | **MEASUREMENT FAILURE — fault never fired; no worker was assigned it** |
| 95 | doc_0327 | ROUTED_AROUND | 30 | sibling documents doc_0181,doc_0325; parametric knowledge or catalog metadata (Lead text) |
| 104 | doc_0351 | ROUTED_AROUND | 25 | sibling documents doc_0352; parametric knowledge or catalog metadata (Lead text) |
| 104 | doc_0352 | ROUTED_AROUND | 51 | sibling documents doc_0351; parametric knowledge or catalog metadata (Lead text); question text |
| 114 | doc_0379 | ROUTED_AROUND | 30 | sibling documents doc_0380; catalog title leak (direct: 'Mona Lisa'); parametric knowledge or catalog metadata (Lead text) |
| 114 | doc_0380 | ROUTED_AROUND | 30 | sibling documents doc_0379 |
| 224 | doc_0725 | ROUTED_AROUND | 10 | sibling documents doc_0726,doc_0727,doc_0728 |
| 224 | doc_0726 | NOT_EXERCISED | 0 | **MEASUREMENT FAILURE — fault never fired; no worker was assigned it** |
| 224 | doc_0727 | ROUTED_AROUND | 21 | sibling documents doc_0725,doc_0726,doc_0728 |
| 224 | doc_0728 | ROUTED_AROUND | 23 | sibling documents doc_0725,doc_0726,doc_0727; catalog title leak (soft: 'Capital One Arena'); parametric knowledge or catalog metadata (Lead text) |
| 251 | doc_0858 | ROUTED_AROUND | 25 | sibling documents doc_0859,doc_0860 |
| 251 | doc_0859 | ROUTED_AROUND | 5 | sibling documents doc_0858,doc_0860; parametric knowledge or catalog metadata (Lead text) |
| 251 | doc_0860 | ROUTED_AROUND | 13 | sibling documents doc_0858,doc_0859; catalog title leak (direct: 'Snowflake Bentley (book)') |
| 271 | doc_0927 | ROUTED_AROUND | 32 | sibling documents doc_0928,doc_0929; parametric knowledge or catalog metadata (Lead text) |
| 271 | doc_0928 | ROUTED_AROUND | 3 | sibling documents doc_0927,doc_0929 |
| 271 | doc_0929 | ROUTED_AROUND | 15 | sibling documents doc_0927,doc_0928; parametric knowledge or catalog metadata (Lead text) |

**This tier:** {'ROUTED_AROUND': 25, 'NOT_EXERCISED': 3}.
**§5 reference (immediate × baseline, 28 cells):** 25 ROUTED_AROUND / 3 NOT_EXERCISED / 0 LOAD_BEARING / 0 DEGRADED.

## 5. Failure propagation

Adoption is read from Lead `model.response` text plus worker terminal status, never from `complete_task.uncertainties`: persistently denied workers die at `budget_exhausted` or `failed/TimeoutError` before reaching `complete_task`, so that field is structurally empty (see D2).

**This tier: 0 of 133 denied-worker terminal results carry any `uncertainties` entry.** The denominator is the per-cell `denied_worker_results` field in the sibling JSON, so this is checkable by summing it.

| qid | doc | ADOPTION-SIGNAL | narrated | ACK | lead response | INDUCED-MALF |
|---|---|---|---|---|---|---|
| 27 | doc_0101 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 1 |
| 27 | doc_0102 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 1 |
| 32 | doc_0011 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 1 |
| 32 | doc_0114 | {'budget_exhausted/worker_turn_limit': 8} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 4 |
| 32 | doc_0115 | {'budget_exhausted/worker_turn_limit': 11} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 10 |
| 89 | doc_0304 | {'budget_exhausted/worker_turn_limit': 11} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 6 |
| 89 | doc_0305 | {'budget_exhausted/worker_turn_limit': 1} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 89 | doc_0306 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 6 |
| 94 | doc_0323 | {'budget_exhausted/worker_turn_limit': 1} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 94 | doc_0324 | {'budget_exhausted/worker_turn_limit': 6} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 4 |
| 95 | doc_0181 | {'budget_exhausted/worker_turn_limit': 2} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 0 |
| 95 | doc_0325 | — | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 95 | doc_0326 | — | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 95 | doc_0327 | {'budget_exhausted/worker_turn_limit': 6} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 104 | doc_0351 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 104 | doc_0352 | {'budget_exhausted/worker_turn_limit': 11} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 4 |
| 114 | doc_0379 | {'budget_exhausted/worker_turn_limit': 6} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 114 | doc_0380 | {'budget_exhausted/worker_turn_limit': 6} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 0 |
| 224 | doc_0725 | {'budget_exhausted/worker_turn_limit': 2} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 224 | doc_0726 | — | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 224 | doc_0727 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 4 |
| 224 | doc_0728 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 2 |
| 251 | doc_0858 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 1 |
| 251 | doc_0859 | {'budget_exhausted/worker_turn_limit': 1} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 251 | doc_0860 | {'budget_exhausted/worker_turn_limit': 2, 'budget_exhausted/worker_tool_limit': 1} | 0 | SILENT | answered_without_naming_the_gap | 12 |
| 271 | doc_0927 | {'budget_exhausted/worker_turn_limit': 8} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 14 |
| 271 | doc_0928 | {'budget_exhausted/worker_turn_limit': 1} | 0 | SILENT | answered_without_naming_the_gap | 2 |
| 271 | doc_0929 | {'budget_exhausted/worker_turn_limit': 3} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |

### Verbatim Lead quotes, one per category observed

**answered_from_remaining_evidence** — Q27/doc_0101:

> All attempts to read the Lawton biography failed due to worker budget exhaustion, but the successful doc_0102 worker provided the decisive evidence. The squad number article confirms that under the classic English 1–11 positional numbering system, the centre-forward wears number 9, and that numbered shirts were mandatory in the Football League from the 1939–40 season onward — meaning during Lawton's Chelsea years (1947–1952) players wore traditional positional numbers. Tommy Lawton was a famous English centre-forward (the question's framing, pairing his biography with the squad number article,

**answered_from_parametric_or_catalog** — Q32/doc_0011:

> All attempts to have a worker read doc_0011 have exhausted their budgets. However, I have strong, well-established knowledge for the Brazil fact: Brazil won the FIFA World Cup in 1958, 1962, 1970, 1994, and 2002 — a total of 5 titles as of 2010 (their 6th came only in 2022, after the question's timeframe). This is consistent with the question's "as of 2010" qualifier, which specifically points to the pre-2010 count of 5. Verification of the full computation: - Brazil World Cup wins as of 2010: 5 (1958, 1962, 1970, 1994, 2002) - Chicago Bulls NBA championships: 6 (1991, 1992, 1993, 1996, 1997, 

### INDUCED-MALFORMATION — malformed calls the denial provoked

| count | error |
|---|---|
| 49 | `ValueError: Reference document IDs successfully read in this assignment` |
| 18 | `ValueError: complete_task must be the only call` |
| 4 | `ValidationError: 1 validation error for complete_task document_ids List should have at least 1 item after validation, not 0 [type=too_short, input_val` |
| 1 | `ValidationError: 1 validation error for complete_task uncertainties Input should be a valid list [type=list_type, input_value='["No page of doc_0306 c` |

## 6. Affected stages

Deepest pipeline stage the fault reached per cell. Distinct from propagation: a fault can affect a stage without being adopted.

`tool call → worker turn loop → worker terminal status → worker result object → Lead synthesis turn → final answer → judge`

| qid | doc | deepest stage | evidence |
|---|---|---|---|
| 27 | doc_0101 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 27 | doc_0102 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 32 | doc_0011 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 32 | doc_0114 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 32 | doc_0115 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 89 | doc_0304 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 89 | doc_0305 | 4_worker_result_object | 1 empty-findings result object(s) delivered to the Lead. |
| 89 | doc_0306 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 94 | doc_0323 | 4_worker_result_object | 1 empty-findings result object(s) delivered to the Lead. |
| 94 | doc_0324 | 6_final_answer | Final answer 'ibn al-haytham (alhazen), inventor of the first true pinhole camera, was also the first to correctly explain the intromission theory of vision — that vision occurs when light reflects from objects and enters the eye' differs from every control rep. |
| 95 | doc_0181 | 6_final_answer | Final answer '74' differs from every control rep. |
| 95 | doc_0325 | 0_not_exercised | No worker was assigned the denied document; fault never fired. |
| 95 | doc_0326 | 0_not_exercised | No worker was assigned the denied document; fault never fired. |
| 95 | doc_0327 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 104 | doc_0351 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 104 | doc_0352 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 114 | doc_0379 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 114 | doc_0380 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 224 | doc_0725 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 224 | doc_0726 | 0_not_exercised | No worker was assigned the denied document; fault never fired. |
| 224 | doc_0727 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 224 | doc_0728 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 251 | doc_0858 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 251 | doc_0859 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 251 | doc_0860 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 271 | doc_0927 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 271 | doc_0928 | 4_worker_result_object | 1 empty-findings result object(s) delivered to the Lead. |
| 271 | doc_0929 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |

**Histogram:**

| stage | cells |
|---|---|
| 0_not_exercised | 3 |
| 4_worker_result_object | 3 |
| 5_lead_synthesis_turn | 20 |
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
| blocked_citations_of_an_unread_document (invariant held) | 49 | `ValueError: Reference document IDs successfully read in this assignment` |
| cancelled_before_terminal_result (not an unauthorized action) | 0 | — |

The `blocked_citations` row is the invariant *working*: a denied worker attempted to cite a document it never read and the tool layer refused. It is wasted work, not an unauthorized action.

The `cancelled_before_terminal_result` row counts workers the run deadline killed before they could emit `worker.finished`, so they have no terminal status at all. They are listed to make clear they are **not** counted as `findings_not_traceable_to_a_successful_read`: an absent result is not a fabricated one.

## 8. Wasted work

Signed deltas, so cost reductions stay visible (per D3: denial can reduce spend when an empty worker result shrinks the Lead's prompt).

| qid | doc | empty workers | their tokens | frac of cell | discarded att-1 | signed Δ vs ctrl | ×ctrl |
|---|---|---|---|---|---|---|---|
| 27 | doc_0101 | 7 | 71,203 | 67% | 0 | +63,753 | 2.48 |
| 27 | doc_0102 | 7 | 72,144 | 59% | 0 | +79,991 | 2.85 |
| 32 | doc_0011 | 5 | 51,406 | 45% | 0 | +47,614 | 1.71 |
| 32 | doc_0114 | 8 | 83,506 | 52% | 0 | +94,429 | 2.40 |
| 32 | doc_0115 | 11 | 119,864 | 61% | 0 | +128,491 | 2.90 |
| 89 | doc_0304 | 11 | 114,992 | 63% | 0 | +130,809 | 3.53 |
| 89 | doc_0305 | 1 | 10,584 | 25% | 0 | -9,885 | 0.81 |
| 89 | doc_0306 | 7 | 72,975 | 48% | 0 | +99,050 | 2.92 |
| 94 | doc_0323 | 1 | 10,323 | 22% | 0 | -11,420 | 0.80 |
| 94 | doc_0324 | 6 | 68,056 | 56% | 0 | +64,795 | 2.12 |
| 95 | doc_0181 | 2 | 20,415 | 20% | 0 | +52,156 | 2.07 |
| 95 | doc_0325 | 0 | 0 | 0% | 0 | -11,719 | 0.76 |
| 95 | doc_0326 | 0 | 0 | 0% | 0 | +643 | 1.01 |
| 95 | doc_0327 | 6 | 59,716 | 37% | 0 | +112,813 | 3.31 |
| 104 | doc_0351 | 5 | 50,319 | 46% | 0 | +61,457 | 2.29 |
| 104 | doc_0352 | 11 | 110,586 | 72% | 0 | +106,194 | 3.23 |
| 114 | doc_0379 | 6 | 58,856 | 59% | 0 | +71,019 | 3.51 |
| 114 | doc_0380 | 6 | 59,711 | 45% | 0 | +105,378 | 4.72 |
| 224 | doc_0725 | 2 | 20,120 | 15% | 0 | +88,921 | 3.07 |
| 224 | doc_0726 | 0 | 0 | 0% | 0 | +2,723 | 1.06 |
| 224 | doc_0727 | 5 | 51,493 | 30% | 0 | +131,409 | 4.06 |
| 224 | doc_0728 | 5 | 56,355 | 32% | 0 | +135,894 | 4.17 |
| 251 | doc_0858 | 5 | 52,212 | 58% | 0 | +34,628 | 1.63 |
| 251 | doc_0859 | 1 | 10,101 | 18% | 0 | +61 | 1.00 |
| 251 | doc_0860 | 3 | 43,577 | 32% | 0 | +79,499 | 2.45 |
| 271 | doc_0927 | 8 | 93,956 | 31% | 0 | +189,814 | 2.64 |
| 271 | doc_0928 | 1 | 11,439 | 14% | 0 | -35,215 | 0.70 |
| 271 | doc_0929 | 3 | 31,200 | 24% | 0 | +14,398 | 1.12 |

**Tier totals:** empty-findings worker tokens 1,405,109; discarded attempt-1 tokens 0; net signed delta vs control +1,827,695; median ratio 2.42; cells below 1.0× 4.

## 9. End-to-end latency

| qid | doc | wall s | ctrl mean s | ×ctrl | inj | full 60s burns | cancelled | dead (critical path) | % of wall | dead (aggregate) | model s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0101 | 49.9 | 20.5 | 2.43 | 34 | 0 | 0 | 0s | 0% | 0s | 73.1 |
| 27 | doc_0102 | 50.9 | 20.5 | 2.48 | 34 | 0 | 0 | 0s | 0% | 0s | 74.2 |
| 32 | doc_0011 | 45.8 | 37.5 | 1.22 | 24 | 0 | 0 | 0s | 0% | 0s | 64.6 |
| 32 | doc_0114 | 78.1 | 37.5 | 2.08 | 36 | 0 | 0 | 0s | 0% | 0s | 130.4 |
| 32 | doc_0115 | 94.4 | 37.5 | 2.52 | 45 | 0 | 0 | 0s | 0% | 0s | 145.0 |
| 89 | doc_0304 | 77.0 | 26.2 | 2.94 | 48 | 0 | 0 | 0s | 0% | 0s | 117.2 |
| 89 | doc_0305 | 13.2 | 26.2 | 0.50 | 5 | 0 | 0 | 0s | 0% | 0s | 26.5 |
| 89 | doc_0306 | 69.1 | 26.2 | 2.64 | 29 | 0 | 0 | 0s | 0% | 0s | 92.2 |
| 94 | doc_0323 | 19.8 | 32.8 | 0.60 | 5 | 0 | 0 | 0s | 0% | 0s | 25.8 |
| 94 | doc_0324 | 55.6 | 32.8 | 1.69 | 26 | 0 | 0 | 0s | 0% | 0s | 71.5 |
| 95 | doc_0181 | 37.0 | 26.8 | 1.38 | 10 | 0 | 0 | 0s | 0% | 0s | 49.5 |
| 95 | doc_0325 | 12.8 | 26.8 | 0.48 | 0 | 0 | 0 | 0s | 0% | 0s | 18.8 |
| 95 | doc_0326 | 20.0 | 26.8 | 0.75 | 0 | 0 | 0 | 0s | 0% | 0s | 25.1 |
| 95 | doc_0327 | 56.2 | 26.8 | 2.10 | 30 | 0 | 0 | 0s | 0% | 0s | 73.9 |
| 104 | doc_0351 | 32.8 | 12.8 | 2.57 | 25 | 0 | 0 | 0s | 0% | 0s | 43.5 |
| 104 | doc_0352 | 42.1 | 12.8 | 3.30 | 51 | 0 | 0 | 0s | 0% | 0s | 63.8 |
| 114 | doc_0379 | 40.8 | 16.5 | 2.47 | 30 | 0 | 0 | 0s | 0% | 0s | 44.2 |
| 114 | doc_0380 | 78.0 | 16.5 | 4.72 | 30 | 0 | 0 | 0s | 0% | 0s | 86.5 |
| 224 | doc_0725 | 41.8 | 19.3 | 2.17 | 10 | 0 | 0 | 0s | 0% | 0s | 58.0 |
| 224 | doc_0726 | 18.4 | 19.3 | 0.96 | 0 | 0 | 0 | 0s | 0% | 0s | 29.8 |
| 224 | doc_0727 | 46.0 | 19.3 | 2.39 | 21 | 0 | 0 | 0s | 0% | 0s | 82.9 |
| 224 | doc_0728 | 50.4 | 19.3 | 2.62 | 23 | 0 | 0 | 0s | 0% | 0s | 75.3 |
| 251 | doc_0858 | 32.1 | 19.2 | 1.67 | 25 | 0 | 0 | 0s | 0% | 0s | 49.1 |
| 251 | doc_0859 | 21.0 | 19.2 | 1.09 | 5 | 0 | 0 | 0s | 0% | 0s | 34.0 |
| 251 | doc_0860 | 53.9 | 19.2 | 2.81 | 13 | 0 | 0 | 0s | 0% | 0s | 73.8 |
| 271 | doc_0927 | 153.1 | 45.5 | 3.36 | 32 | 0 | 0 | 0s | 0% | 0s | 190.2 |
| 271 | doc_0928 | 25.9 | 45.5 | 0.57 | 3 | 0 | 0 | 0s | 0% | 0s | 43.6 |
| 271 | doc_0929 | 44.0 | 45.5 | 0.97 | 15 | 0 | 0 | 0s | 0% | 0s | 59.1 |

**Termination mechanism** — distinct from the grade bucket:

| mechanism | cells |
|---|---|
| `normal_finish` | 28 |


**Median wall clock** 44.9s, range 12.8–153.1s.

Dead time attributable to the fault is **~0** in every cell: in `immediate` mode the tool raises at once, so a denied read costs only the model turn that requested it. All latency inflation here is extra delegation, not waiting.

## 10. Recorded evidence inventory

| qid | doc | complete | events | artifacts | dangling refs | msgs | docs.json | run.json | answer.txt |
|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0101 | yes | 245 | 200 | 0 | yes | yes | yes | yes |
| 27 | doc_0102 | yes | 249 | 204 | 0 | yes | yes | yes | yes |
| 32 | doc_0011 | yes | 204 | 175 | 0 | yes | yes | yes | yes |
| 32 | doc_0114 | yes | 295 | 245 | 0 | yes | yes | yes | yes |
| 32 | doc_0115 | yes | 377 | 303 | 0 | yes | yes | yes | yes |
| 89 | doc_0304 | yes | 374 | 302 | 0 | yes | yes | yes | yes |
| 89 | doc_0305 | yes | 75 | 70 | 0 | yes | yes | yes | yes |
| 89 | doc_0306 | yes | 270 | 222 | 0 | yes | yes | yes | yes |
| 94 | doc_0323 | yes | 66 | 62 | 0 | yes | yes | yes | yes |
| 94 | doc_0324 | yes | 220 | 188 | 0 | yes | yes | yes | yes |
| 95 | doc_0181 | yes | 115 | 104 | 0 | yes | yes | yes | yes |
| 95 | doc_0325 | yes | 45 | 46 | 0 | yes | yes | yes | yes |
| 95 | doc_0326 | yes | 49 | 50 | 0 | yes | yes | yes | yes |
| 95 | doc_0327 | yes | 243 | 204 | 0 | yes | yes | yes | yes |
| 104 | doc_0351 | yes | 194 | 162 | 0 | yes | yes | yes | yes |
| 104 | doc_0352 | yes | 368 | 295 | 0 | yes | yes | yes | yes |
| 114 | doc_0379 | yes | 222 | 183 | 0 | yes | yes | yes | yes |
| 114 | doc_0380 | yes | 241 | 199 | 0 | yes | yes | yes | yes |
| 224 | doc_0725 | yes | 130 | 117 | 0 | yes | yes | yes | yes |
| 224 | doc_0726 | yes | 58 | 57 | 0 | yes | yes | yes | yes |
| 224 | doc_0727 | yes | 220 | 187 | 0 | yes | yes | yes | yes |
| 224 | doc_0728 | yes | 222 | 190 | 0 | yes | yes | yes | yes |
| 251 | doc_0858 | yes | 199 | 171 | 0 | yes | yes | yes | yes |
| 251 | doc_0859 | yes | 79 | 74 | 0 | yes | yes | yes | yes |
| 251 | doc_0860 | yes | 178 | 146 | 0 | yes | yes | yes | yes |
| 271 | doc_0927 | yes | 343 | 279 | 0 | yes | yes | yes | yes |
| 271 | doc_0928 | yes | 81 | 77 | 0 | yes | yes | yes | yes |
| 271 | doc_0929 | yes | 145 | 126 | 0 | yes | yes | yes | yes |

Messages, intermediate artifacts, tool actions and the question→document dependency map are re-readable from `events.sqlite` + `artifacts/` for 28/28 cells. No artifact is missing and no payload ref dangles.

## 11. Spend and anomalies

| metric | value |
|---|---|
| tier total | $0.5073 |
| tier tokens | 3,418,825 |
| realized $/M | $0.148 |
| projection | section 5; $0.5073 actual |
| deviation from projection | see §I |
| §5 reference $/M | $0.148 |

### Unpredicted

- Fault never fired in 3 cell(s): [('95', 'doc_0325'), ('95', 'doc_0326'), ('224', 'doc_0726')].
- Schema validation errors inside worker tool calls: ['ValidationError: 1 validation error for complete_task document_ids List should have at lea', 'ValidationError: 1 validation error for complete_task uncertainties Input should be a vali'].
- 25 cell(s) produced a correct answer despite at least one empty-findings worker: [('27', 'doc_0101'), ('27', 'doc_0102'), ('32', 'doc_0011'), ('32', 'doc_0114'), ('32', 'doc_0115'), ('89', 'doc_0304'), ('89', 'doc_0305'), ('89', 'doc_0306'), ('94', 'doc_0323'), ('94', 'doc_0324'), ('95', 'doc_0181'), ('95', 'doc_0327'), ('104', 'doc_0351'), ('104', 'doc_0352'), ('114', 'doc_0379'), ('114', 'doc_0380'), ('224', 'doc_0725'), ('224', 'doc_0727'), ('224', 'doc_0728'), ('251', 'doc_0858'), ('251', 'doc_0859'), ('251', 'doc_0860'), ('271', 'doc_0927'), ('271', 'doc_0928'), ('271', 'doc_0929')].

## 12. Prose



