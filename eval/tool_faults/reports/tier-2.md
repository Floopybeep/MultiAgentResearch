# Tier 2 — recovery and detection under immediate denial, plus timeout recovery (30 cells)

`fault_class: accidental` · `fault_effect: denial` — tool-layer evidence denial at the `read_document` boundary. Every cell below is accidental denial; adversarial evidence-corruption conditions are a different fault class, owned by teammates, and are reported separately. Never pool these numbers with those.

Generated 2026-11-04T22:05:46-08:00 · 30 cells

## Running headline

Across section-5-rep1 (28) the system produced **28 of 28 cells correct** — 28 consecutive.

This tier is **30 of 30 correct**.

> PROPAGATION IS STRUCTURALLY UNMEASURABLE IN THE FULL-RESTART ARM (20 of 30 cells). research.py:36-37 stamps status=interrupted on every node once runtime.injected_faults is non-empty while full_restart and attempt==1, and runner.py:129-130 sets will_restart and skips grading for attempt 1, so attempt 1 ends at the first completed node after the denial and the Lead never reasons about the missing evidence; attempt 2 then runs clean via _build_clean_restart_config and sees no fault at all (measured: 0 injections in attempt 2 in 20/20 cells). The full-restart arm measures RECOVERY COST, the always-verify arm measures DETECTION, and only the baseline arm (section 5, Tier 1, Tier 3) measures propagation. Three dependent variables, not one metric in three conditions.
> ADOPTION GATE: adoption is read from Lead model.response text plus worker terminal status, never from complete_task.uncertainties (structurally always empty under persistent denial). The gate was corrected twice during this section, both times for FALSE NEGATIVES: first it required the literal document ID or the substring 'read', which scored SILENT turns like 'The Snoopy worker has failed three times on budget' that name the document by catalog title and by worker; then it lacked any pattern for the timeout manifestation, which scored SILENT turns like 'The Cowboys article workers have timed out six times'. All tiers in this section were regenerated under the final gate.
> Single-rep magnitudes. Tier 3 measures token deviation between identical re-runs at a median 9.7% (max 51.6%) and wall-clock deviation at a median 39.8% (max 83.0%), with injection counts never reproducing exactly.

## 1. Cell table

| qid | doc | mode | scenario | status | termination | grade | att | batches | workers | wall s | tokens | cost | ×ctrl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | immediate | always-verify | completed | normal_finish | correct | 1 | 4 | 8 | 100.0 | 187,116 | $0.0292 | 4.33 |
| 27 | doc_0102 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 42.1 | 99,657 | $0.0139 | 2.31 |
| 27 | doc_0102 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 206.7 | 94,679 | $0.0135 | 2.19 |
| 32 | doc_0115 | immediate | always-verify | completed | normal_finish | correct | 1 | 5 | 11 | 147.3 | 359,361 | $0.0520 | 5.33 |
| 32 | doc_0115 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 6 | 41.4 | 112,150 | $0.0173 | 1.66 |
| 32 | doc_0115 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 6 | 199.1 | 121,619 | $0.0190 | 1.80 |
| 89 | doc_0304 | immediate | always-verify | completed | normal_finish | correct | 1 | 5 | 11 | 123.2 | 258,434 | $0.0397 | 5.01 |
| 89 | doc_0304 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 5 | 30.2 | 69,409 | $0.0111 | 1.34 |
| 89 | doc_0304 | timeout | full-restart | completed | normal_finish | correct | 2 | 2 | 5 | 199.8 | 70,731 | $0.0111 | 1.37 |
| 94 | doc_0324 | immediate | always-verify | completed | normal_finish | correct | 1 | 4 | 8 | 133.1 | 231,961 | $0.0354 | 4.02 |
| 94 | doc_0324 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 41.9 | 93,598 | $0.0143 | 1.62 |
| 94 | doc_0324 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 198.1 | 97,757 | $0.0151 | 1.69 |
| 95 | doc_0327 | immediate | always-verify | completed | normal_finish | correct | 1 | 6 | 12 | 186.4 | 529,491 | $0.0829 | 10.84 |
| 95 | doc_0327 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 45.1 | 97,474 | $0.0153 | 2.00 |
| 95 | doc_0327 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 196.5 | 77,070 | $0.0117 | 1.58 |
| 104 | doc_0352 | immediate | always-verify | completed | normal_finish | correct | 1 | 3 | 6 | 81.0 | 135,891 | $0.0210 | 2.85 |
| 104 | doc_0352 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 31.6 | 65,601 | $0.0095 | 1.37 |
| 104 | doc_0352 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 194.4 | 61,626 | $0.0088 | 1.29 |
| 114 | doc_0380 | immediate | always-verify | completed | normal_finish | correct | 1 | 6 | 12 | 171.9 | 359,344 | $0.0556 | 12.68 |
| 114 | doc_0380 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 21.4 | 70,320 | $0.0107 | 2.48 |
| 114 | doc_0380 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 4 | 194.6 | 48,169 | $0.0076 | 1.70 |
| 224 | doc_0727 | immediate | always-verify | completed | normal_finish | correct | 1 | 2 | 5 | 54.1 | 218,852 | $0.0313 | 5.10 |
| 224 | doc_0727 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 7 | 41.8 | 102,319 | $0.0164 | 2.39 |
| 224 | doc_0727 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 7 | 205.3 | 173,179 | $0.0247 | 4.04 |
| 251 | doc_0858 | immediate | always-verify | completed | normal_finish | correct | 1 | 1 | 3 | 37.7 | 61,345 | $0.0100 | 1.12 |
| 251 | doc_0858 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 6 | 25.0 | 86,786 | $0.0131 | 1.58 |
| 251 | doc_0858 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 6 | 198.4 | 83,062 | $0.0127 | 1.51 |
| 271 | doc_0927 | immediate | always-verify | completed | normal_finish | correct | 1 | 6 | 13 | 153.5 | 452,950 | $0.0651 | 3.90 |
| 271 | doc_0927 | immediate | full-restart | completed | normal_finish | correct | 2 | 1 | 6 | 62.8 | 197,479 | $0.0281 | 1.70 |
| 271 | doc_0927 | timeout | full-restart | completed | normal_finish | correct | 2 | 1 | 6 | 210.0 | 183,579 | $0.0267 | 1.58 |

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
| correct | 30/30 | 30/30 |
| incorrect | 0/30 | 0/30 |
| execution_failed | 0/30 | 0/30 |
| ungradeable | 0/30 | 0/30 |

## 4. Dependency verdict — did the workload depend on the denied document?

An ignored message is not evidence of robust recovery, so every ROUTED_AROUND verdict below names the substitute evidence or leak channel the Lead used instead. A correct answer with the denial **unexercised** is a measurement failure, not a robustness result.

| qid | doc | verdict | fired | substitute evidence / channel |
|---|---|---|---|---|
| 27 | doc_0102 | ROUTED_AROUND | 35 | sibling documents doc_0101; parametric knowledge or catalog metadata (Lead text) |
| 27 | doc_0102 | ROUTED_AROUND | 5 | sibling documents doc_0101 |
| 27 | doc_0102 | ROUTED_AROUND | 3 | sibling documents doc_0101 |
| 32 | doc_0115 | ROUTED_AROUND | 35 | sibling documents doc_0011,doc_0114; parametric knowledge or catalog metadata (Lead text) |
| 32 | doc_0115 | ROUTED_AROUND | 5 | sibling documents doc_0011,doc_0114 |
| 32 | doc_0115 | ROUTED_AROUND | 3 | sibling documents doc_0011,doc_0114 |
| 89 | doc_0304 | ROUTED_AROUND | 38 | sibling documents doc_0305,doc_0306; parametric knowledge or catalog metadata (Lead text) |
| 89 | doc_0304 | ROUTED_AROUND | 5 | sibling documents doc_0305,doc_0306 |
| 89 | doc_0304 | ROUTED_AROUND | 3 | sibling documents doc_0305,doc_0306 |
| 94 | doc_0324 | ROUTED_AROUND | 19 | sibling documents doc_0323; parametric knowledge or catalog metadata (Lead text) |
| 94 | doc_0324 | ROUTED_AROUND | 5 | sibling documents doc_0323 |
| 94 | doc_0324 | ROUTED_AROUND | 3 | sibling documents doc_0323 |
| 95 | doc_0327 | ROUTED_AROUND | 32 | sibling documents doc_0181,doc_0325,doc_0326; parametric knowledge or catalog metadata (Lead text) |
| 95 | doc_0327 | ROUTED_AROUND | 5 | sibling documents doc_0181 |
| 95 | doc_0327 | ROUTED_AROUND | 3 | sibling documents doc_0181 |
| 104 | doc_0352 | ROUTED_AROUND | 22 | sibling documents doc_0351 |
| 104 | doc_0352 | ROUTED_AROUND | 5 | sibling documents doc_0351 |
| 104 | doc_0352 | ROUTED_AROUND | 3 | sibling documents doc_0351 |
| 114 | doc_0380 | ROUTED_AROUND | 34 | sibling documents doc_0379 |
| 114 | doc_0380 | ROUTED_AROUND | 5 | sibling documents doc_0379 |
| 114 | doc_0380 | ROUTED_AROUND | 3 | sibling documents doc_0379 |
| 224 | doc_0727 | ROUTED_AROUND | 10 | sibling documents doc_0725,doc_0726,doc_0728 |
| 224 | doc_0727 | ROUTED_AROUND | 5 | sibling documents doc_0725,doc_0728 |
| 224 | doc_0727 | ROUTED_AROUND | 3 | sibling documents doc_0725,doc_0726,doc_0728 |
| 251 | doc_0858 | ROUTED_AROUND | 5 | sibling documents doc_0859,doc_0860 |
| 251 | doc_0858 | ROUTED_AROUND | 5 | sibling documents doc_0859,doc_0860 |
| 251 | doc_0858 | ROUTED_AROUND | 3 | sibling documents doc_0859,doc_0860 |
| 271 | doc_0927 | ROUTED_AROUND | 50 | sibling documents doc_0928,doc_0929 |
| 271 | doc_0927 | ROUTED_AROUND | 5 | sibling documents doc_0928,doc_0929 |
| 271 | doc_0927 | ROUTED_AROUND | 3 | sibling documents doc_0928,doc_0929 |

**This tier:** {'ROUTED_AROUND': 30}.
**§5 reference (immediate × baseline, 28 cells):** 25 ROUTED_AROUND / 3 NOT_EXERCISED / 0 LOAD_BEARING / 0 DEGRADED.

## 5. Failure propagation

**Structurally unmeasurable in this arm.** PROPAGATION IS STRUCTURALLY UNMEASURABLE IN THE FULL-RESTART ARM (20 of 30 cells). research.py:36-37 stamps status=interrupted on every node once runtime.injected_faults is non-empty while full_restart and attempt==1, and runner.py:129-130 sets will_restart and skips grading for attempt 1, so attempt 1 ends at the first completed node after the denial and the Lead never reasons about the missing evidence; attempt 2 then runs clean via _build_clean_restart_config and sees no fault at all (measured: 0 injections in attempt 2 in 20/20 cells). The full-restart arm measures RECOVERY COST, the always-verify arm measures DETECTION, and only the baseline arm (section 5, Tier 1, Tier 3) measures propagation. Three dependent variables, not one metric in three conditions.

Adoption is read from Lead `model.response` text plus worker terminal status, never from `complete_task.uncertainties`: persistently denied workers die at `budget_exhausted` or `failed/TimeoutError` before reaching `complete_task`, so that field is structurally empty (see D2).

**This tier: 0 of 84 denied-worker terminal results carry any `uncertainties` entry.** The denominator is the per-cell `denied_worker_results` field in the sibling JSON, so this is checkable by summing it. A further 19 target-document workers DID report uncertainties, all of them in the clean restart attempt, where they read the document successfully; they are not denied workers and are counted separately.

| qid | doc | ADOPTION-SIGNAL | narrated | ACK | lead response | INDUCED-MALF |
|---|---|---|---|---|---|---|
| 27 | doc_0102 | {'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 0 |
| 27 | doc_0102 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 27 | doc_0102 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 32 | doc_0115 | {'budget_exhausted/worker_turn_limit': 8} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 5 |
| 32 | doc_0115 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 32 | doc_0115 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 89 | doc_0304 | {"failed/OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Rate limit exceeded for api_key: [REDACTED]. Limit type: requests. Current limit: 100, Remaining: 0. Limit resets at: 2026-11-05 01:25:29 UTC', 'type': 'throttling_error', 'param': None, 'code': '429'}}": 1, 'budget_exhausted/worker_turn_limit': 7} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 0 |
| 89 | doc_0304 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 89 | doc_0304 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 94 | doc_0324 | {'budget_exhausted/worker_turn_limit': 6} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 10 |
| 94 | doc_0324 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 94 | doc_0324 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 95 | doc_0327 | {'budget_exhausted/worker_turn_limit': 7, "failed/OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Rate limit exceeded for api_key: [REDACTED]. Limit type: max_parallel_requests. Current limit: 7, Remaining: 0. Limit resets at: 2026-11-05 01:29:56 UTC', 'type': 'throttling_error', 'param': None, 'code': '429'}}": 1} | 0 | ACKNOWLEDGED | answered_from_parametric_or_catalog | 14 |
| 95 | doc_0327 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 1 |
| 95 | doc_0327 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 104 | doc_0352 | {'budget_exhausted/worker_turn_limit': 5} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 3 |
| 104 | doc_0352 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 104 | doc_0352 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 114 | doc_0380 | {'budget_exhausted/worker_turn_limit': 9} | 0 | ACKNOWLEDGED | answered_from_remaining_evidence | 11 |
| 114 | doc_0380 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 114 | doc_0380 | {'failed/TimeoutError: ': 1} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 224 | doc_0727 | {'budget_exhausted/worker_turn_limit': 2} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 224 | doc_0727 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 224 | doc_0727 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 251 | doc_0858 | {'budget_exhausted/worker_turn_limit': 1} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 251 | doc_0858 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 251 | doc_0858 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 271 | doc_0927 | {'budget_exhausted/worker_turn_limit': 10} | 0 | SILENT | answered_without_naming_the_gap | 0 |
| 271 | doc_0927 | {'budget_exhausted/worker_turn_limit': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |
| 271 | doc_0927 | {'failed/TimeoutError: ': 1} | 0 (+1 in the clean restart attempt) | SILENT | answered_without_naming_the_gap | 0 |

### Verbatim Lead quotes, one per category observed

**answered_from_parametric_or_catalog** — Q27/doc_0102:

> The doc_0102 read tool is systemically unavailable across four batches (persistent ToolUnavailableError), so further retries are unlikely to change the outcome. I have sufficient evidence to answer: - **doc_0101 (verified)**: Tommy Lawton played for Chelsea FC (1945–1947, 42 league appearances, 30 goals) as a **centre-forward** — "widely regarded as the finest centre-forward of his generation." - **doc_0102 (unavailable)**: Lawton's era (1940s) predates fixed squad numbering in England (introduced 1993), when players wore numbers 1–11 assigned by position on match days. The traditional number 

**answered_from_remaining_evidence** — Q89/doc_0304:

> Both doc_0304 workers failed again due to tool unavailability. I have budget remaining (batches 4–6), so I'll retry doc_0304 once more with two workers, instructing them to retry reads and report even partial content.

### INDUCED-MALFORMATION — malformed calls the denial provoked

| count | error |
|---|---|
| 30 | `ValueError: Reference document IDs successfully read in this assignment` |
| 11 | `ValueError: complete_task must be the only call` |
| 2 | `ValidationError: 1 validation error for complete_task document_ids List should have at least 1 item after validation, not 0 [type=too_short, input_val` |
| 1 | `ValidationError: 1 validation error for complete_task uncertainties Input should be a valid list [type=list_type, input_value='["The article snapshot ` |

## 6. Affected stages

Deepest pipeline stage the fault reached per cell. Distinct from propagation: a fault can affect a stage without being adopted.

`tool call → worker turn loop → worker terminal status → worker result object → Lead synthesis turn → final answer → judge`

| qid | doc | deepest stage | evidence |
|---|---|---|---|
| 27 | doc_0102 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 27 | doc_0102 | 1_tool_call | 0 denied read(s). |
| 27 | doc_0102 | 1_tool_call | 0 denied read(s). |
| 32 | doc_0115 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 32 | doc_0115 | 1_tool_call | 0 denied read(s). |
| 32 | doc_0115 | 1_tool_call | 0 denied read(s). |
| 89 | doc_0304 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 89 | doc_0304 | 1_tool_call | 0 denied read(s). |
| 89 | doc_0304 | 1_tool_call | 0 denied read(s). |
| 94 | doc_0324 | 6_final_answer | Final answer 'the intromission theory of vision (how human vision works — light reflecting off objects and entering the eye)' differs from every control rep. |
| 94 | doc_0324 | 1_tool_call | 0 denied read(s). |
| 94 | doc_0324 | 1_tool_call | 0 denied read(s). |
| 95 | doc_0327 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 95 | doc_0327 | 1_tool_call | 0 denied read(s). |
| 95 | doc_0327 | 1_tool_call | 0 denied read(s). |
| 104 | doc_0352 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 104 | doc_0352 | 1_tool_call | 0 denied read(s). |
| 104 | doc_0352 | 1_tool_call | 0 denied read(s). |
| 114 | doc_0380 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 114 | doc_0380 | 1_tool_call | 0 denied read(s). |
| 114 | doc_0380 | 1_tool_call | 0 denied read(s). |
| 224 | doc_0727 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 224 | doc_0727 | 1_tool_call | 0 denied read(s). |
| 224 | doc_0727 | 1_tool_call | 0 denied read(s). |
| 251 | doc_0858 | 4_worker_result_object | 1 empty-findings result object(s) delivered to the Lead. |
| 251 | doc_0858 | 1_tool_call | 0 denied read(s). |
| 251 | doc_0858 | 1_tool_call | 0 denied read(s). |
| 271 | doc_0927 | 5_lead_synthesis_turn | Lead re-delegated the denied document or named the gap in its own text. |
| 271 | doc_0927 | 1_tool_call | 0 denied read(s). |
| 271 | doc_0927 | 1_tool_call | 0 denied read(s). |

**Histogram:**

| stage | cells |
|---|---|
| 1_tool_call | 20 |
| 4_worker_result_object | 1 |
| 5_lead_synthesis_turn | 8 |
| 6_final_answer | 1 |

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
| blocked_citations_of_an_unread_document (invariant held) | 30 | `ValueError: Reference document IDs successfully read in this assignment` |
| cancelled_before_terminal_result (not an unauthorized action) | 0 | — |

The `blocked_citations` row is the invariant *working*: a denied worker attempted to cite a document it never read and the tool layer refused. It is wasted work, not an unauthorized action.

The `cancelled_before_terminal_result` row counts workers the run deadline killed before they could emit `worker.finished`, so they have no terminal status at all. They are listed to make clear they are **not** counted as `findings_not_traceable_to_a_successful_read`: an absent result is not a fabricated one.

## 8. Wasted work

Signed deltas, so cost reductions stay visible (per D3: denial can reduce spend when an empty worker result shrinks the Lead's prompt).

| qid | doc | empty workers | their tokens | frac of cell | discarded att-1 | signed Δ vs ctrl | ×ctrl |
|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | 7 | 71,805 | 38% | 0 | +143,919 | 4.33 |
| 27 | doc_0102 | 1 | 10,340 | 10% | 38,390 | +56,460 | 2.31 |
| 27 | doc_0102 | 1 | 5,941 | 6% | 34,288 | +51,482 | 2.19 |
| 32 | doc_0115 | 8 | 85,356 | 24% | 0 | +291,902 | 5.33 |
| 32 | doc_0115 | 1 | 10,252 | 9% | 52,572 | +44,691 | 1.66 |
| 32 | doc_0115 | 1 | 5,857 | 5% | 56,518 | +54,160 | 1.80 |
| 89 | doc_0304 | 9 | 77,422 | 30% | 0 | +206,807 | 5.01 |
| 89 | doc_0304 | 1 | 10,181 | 15% | 27,107 | +17,782 | 1.34 |
| 89 | doc_0304 | 1 | 5,879 | 8% | 22,931 | +19,104 | 1.37 |
| 94 | doc_0324 | 6 | 68,998 | 30% | 0 | +174,204 | 4.02 |
| 94 | doc_0324 | 1 | 10,488 | 11% | 24,020 | +35,841 | 1.62 |
| 94 | doc_0324 | 1 | 5,973 | 6% | 50,420 | +40,000 | 1.69 |
| 95 | doc_0327 | 8 | 79,702 | 15% | 0 | +480,638 | 10.84 |
| 95 | doc_0327 | 1 | 10,155 | 10% | 31,122 | +48,621 | 2.00 |
| 95 | doc_0327 | 1 | 5,945 | 8% | 27,005 | +28,217 | 1.58 |
| 104 | doc_0352 | 5 | 52,953 | 39% | 0 | +88,170 | 2.85 |
| 104 | doc_0352 | 1 | 10,010 | 15% | 23,600 | +17,880 | 1.37 |
| 104 | doc_0352 | 1 | 5,822 | 9% | 18,986 | +13,905 | 1.29 |
| 114 | doc_0380 | 10 | 105,113 | 29% | 0 | +331,004 | 12.68 |
| 114 | doc_0380 | 1 | 9,919 | 14% | 26,262 | +41,980 | 2.48 |
| 114 | doc_0380 | 1 | 5,813 | 12% | 19,600 | +19,829 | 1.70 |
| 224 | doc_0727 | 2 | 20,378 | 9% | 0 | +175,956 | 5.10 |
| 224 | doc_0727 | 2 | 19,560 | 19% | 45,425 | +59,423 | 2.39 |
| 224 | doc_0727 | 1 | 5,873 | 3% | 43,228 | +130,283 | 4.04 |
| 251 | doc_0858 | 1 | 10,683 | 17% | 0 | +6,438 | 1.12 |
| 251 | doc_0858 | 1 | 10,293 | 12% | 30,156 | +31,879 | 1.58 |
| 251 | doc_0858 | 1 | 6,077 | 7% | 30,000 | +28,155 | 1.51 |
| 271 | doc_0927 | 10 | 101,095 | 22% | 0 | +336,910 | 3.90 |
| 271 | doc_0927 | 1 | 10,391 | 5% | 63,315 | +81,439 | 1.70 |
| 271 | doc_0927 | 1 | 6,171 | 3% | 70,500 | +67,539 | 1.58 |

**Tier totals:** empty-findings worker tokens 844,445; discarded attempt-1 tokens 735,445; net signed delta vs control +3,124,613; median ratio 1.90; cells below 1.0× 0.

### 8a. Recovery cost — full-restart arm

Attempt 1 is waste by construction: it is abandoned ungraded as soon as a denial is recorded, and attempt 2 re-runs clean via `_build_clean_restart_config`. Recovery cost is therefore attempt-1 tokens plus whatever attempt 2 exceeds the clean control by.

| qid | mode | att-1 discarded | att-2 | total | ctrl mean | ×ctrl | att-2 ×ctrl | wall s | ctrl wall | wall penalty | restarted | clean_slate_reset |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | immediate | 38,390 | 61,267 | 99,657 | 43,197 | 2.31 | 1.42 | 42.1 | 20.5 | +21.6s | True | True |
| 27 | timeout | 34,288 | 60,391 | 94,679 | 43,197 | 2.19 | 1.40 | 206.7 | 20.5 | +186.2s | True | True |
| 32 | immediate | 52,572 | 59,578 | 112,150 | 67,459 | 1.66 | 0.88 | 41.4 | 37.5 | +3.9s | True | True |
| 32 | timeout | 56,518 | 65,101 | 121,619 | 67,459 | 1.80 | 0.97 | 199.1 | 37.5 | +161.6s | True | True |
| 89 | immediate | 27,107 | 42,302 | 69,409 | 51,627 | 1.34 | 0.82 | 30.2 | 26.2 | +4.0s | True | True |
| 89 | timeout | 22,931 | 47,800 | 70,731 | 51,627 | 1.37 | 0.93 | 199.8 | 26.2 | +173.5s | True | True |
| 94 | immediate | 24,020 | 69,578 | 93,598 | 57,757 | 1.62 | 1.20 | 41.9 | 32.8 | +9.1s | True | True |
| 94 | timeout | 50,420 | 47,337 | 97,757 | 57,757 | 1.69 | 0.82 | 198.1 | 32.8 | +165.2s | True | True |
| 95 | immediate | 31,122 | 66,352 | 97,474 | 48,853 | 2.00 | 1.36 | 45.1 | 26.8 | +18.4s | True | True |
| 95 | timeout | 27,005 | 50,065 | 77,070 | 48,853 | 1.58 | 1.02 | 196.5 | 26.8 | +169.7s | True | True |
| 104 | immediate | 23,600 | 42,001 | 65,601 | 47,721 | 1.37 | 0.88 | 31.6 | 12.8 | +18.8s | True | True |
| 104 | timeout | 18,986 | 42,640 | 61,626 | 47,721 | 1.29 | 0.89 | 194.4 | 12.8 | +181.6s | True | True |
| 114 | immediate | 26,262 | 44,058 | 70,320 | 28,340 | 2.48 | 1.55 | 21.4 | 16.5 | +4.9s | True | True |
| 114 | timeout | 19,600 | 28,569 | 48,169 | 28,340 | 1.70 | 1.01 | 194.6 | 16.5 | +178.1s | True | True |
| 224 | immediate | 45,425 | 56,894 | 102,319 | 42,896 | 2.39 | 1.33 | 41.8 | 19.3 | +22.5s | True | True |
| 224 | timeout | 43,228 | 129,951 | 173,179 | 42,896 | 4.04 | 3.03 | 205.3 | 19.3 | +186.1s | True | True |
| 251 | immediate | 30,156 | 56,630 | 86,786 | 54,907 | 1.58 | 1.03 | 25.0 | 19.2 | +5.8s | True | True |
| 251 | timeout | 30,000 | 53,062 | 83,062 | 54,907 | 1.51 | 0.97 | 198.4 | 19.2 | +179.2s | True | True |
| 271 | immediate | 63,315 | 134,164 | 197,479 | 116,040 | 1.70 | 1.16 | 62.8 | 45.5 | +17.3s | True | True |
| 271 | timeout | 70,500 | 113,079 | 183,579 | 116,040 | 1.58 | 0.97 | 210.0 | 45.5 | +164.5s | True | True |

**Recovery succeeded in 20/20 cells**, every one with `clean_slate_reset: true` and `restart_reason: fault_injected`; 20/20 graded correct.

Discarded attempt-1 tokens: total 735,445, mean 36,772, range 18,986–70,500 — 37% of the arm's spend is pure waste by construction.

Attempt 2 runs at 1.14× the clean control on average, so the clean re-run is itself slightly costlier than clean — the restart is clean in state, not free in tokens.

Wall clock, immediate mode: median 41.6s, range 21.4–62.8s (clean control median 23.4s).
Wall clock, timeout mode: median 198.8s, range 194.4–210.0s (clean control median 23.4s).

### 8b. Verification cost and detection — always-verify arm

Verifier inference is reported as a separate line item, never folded into the run total.

| qid | verifier calls | verifier tokens | cell total | verifier share | matched §5 immediate/baseline tokens | marginal % |
|---|---|---|---|---|---|---|
| 27 | 12 | 69,511 | 187,116 | 37% | 123,188 | +52% |
| 32 | 16 | 141,850 | 359,361 | 39% | 195,950 | +83% |
| 89 | 16 | 106,925 | 258,434 | 41% | 182,436 | +42% |
| 94 | 12 | 90,134 | 231,961 | 39% | 122,552 | +89% |
| 95 | 18 | 208,907 | 529,491 | 39% | 161,666 | +228% |
| 104 | 9 | 50,445 | 135,891 | 37% | 153,915 | -12% |
| 114 | 18 | 144,543 | 359,344 | 40% | 133,718 | +169% |
| 224 | 7 | 77,459 | 218,852 | 35% | 174,305 | +26% |
| 251 | 4 | 23,468 | 61,345 | 38% | 89,535 | -31% |
| 271 | 19 | 180,522 | 452,950 | 40% | 305,854 | +48% |

**Verification costs 1,093,764 tokens, 39% of the arm's 2,794,745 total.**

Detection is scored per boundary and against ground truth — a verifier that flags everything detects nothing, so each flag is checked against whether that worker actually held the denied document.

| boundary | subject | flagged (`verified: false`) | passed | null/error |
|---|---|---|---|---|
| `worker_result` (research.py:178-179) | worker holding the denial | **60** | 1 | 3 |
| `worker_result` | clean worker | 1 | 23 | 1 |
| `lead_plan` (research.py:102-103) | the plan | 0 | 41 | 1 |

- **Recall on denied workers:** 60/64 = 94%
- **False-positive rate on clean workers:** 1/25 = 4%
- **Precision of a flag:** 60/61 = 98%
- **Cells where the denial was detected at least once:** 10/10

The `lead_plan` boundary flagged **0 of 42** plans. That is expected rather than a failure: the plan is written before any document is read, so there is nothing yet to be inconsistent with. Verification cost is paid at both boundaries; signal arrives at only one.

#### Why the null verdicts are null

A null is **not** the verifier judging a boundary and getting it wrong. Each is attributed below, because an unexplained null in a detection table reads as a silent miss.

| qid | boundary | subject | cause |
|---|---|---|---|
| 27 | `worker_result` | worker holding the denial | rate_limit (verifier never ran) |
| 27 | `worker_result` | worker holding the denial | verifier output unparseable (ran, no usable verdict) |
| 89 | `worker_result` | clean worker | rate_limit (verifier never ran) |
| 95 | `worker_result` | worker holding the denial | rate_limit (verifier never ran) |
| 224 | `lead_plan` | the plan | verifier output unparseable (ran, no usable verdict) |

**3 of the 5 null verdicts are verifications that failed on a self-inflicted rate limit** (see the execution-artifacts note); they are counted as misses, so the recall figure above is a **floor**, not an estimate.

Of the 64 boundaries belonging to a worker that held the denial, only **1** is a true miss — the verifier ran, returned a verdict, and passed a denied worker. The other 3 produced no verdict at all (2 rate-limited, 1 unparseable verifier output). Excluding only the rate-limited ones gives 60/62 = 97%; excluding every non-verdict gives 60/61 = 98%. The floor is the number to quote.

**Precision caveat.** The false-positive rate above is measured against clean workers *inside faulted runs*. It is not a full specificity estimate, which would need always-verify cells with no fault at all; none were run, so no no-fault verifier baseline exists in this tier.

## 9. End-to-end latency

| qid | doc | wall s | ctrl mean s | ×ctrl | inj | full 60s burns | cancelled | dead (critical path) | % of wall | dead (aggregate) | model s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | 100.0 | 20.5 | 4.87 | 35 | 0 | 0 | 0s | 0% | 0s | 136.9 |
| 27 | doc_0102 | 42.1 | 20.5 | 2.05 | 5 | 0 | 0 | 0s | 0% | 0s | 58.9 |
| 27 | doc_0102 | 206.7 | 20.5 | 10.07 | 3 | 2 | 1 | 178s | 86% | 178s | 51.6 |
| 32 | doc_0115 | 147.3 | 37.5 | 3.93 | 35 | 0 | 0 | 0s | 0% | 0s | 213.7 |
| 32 | doc_0115 | 41.4 | 37.5 | 1.10 | 5 | 0 | 0 | 0s | 0% | 0s | 82.3 |
| 32 | doc_0115 | 199.1 | 37.5 | 5.31 | 3 | 2 | 1 | 177s | 89% | 177s | 66.2 |
| 89 | doc_0304 | 123.2 | 26.2 | 4.70 | 38 | 0 | 0 | 0s | 0% | 0s | 162.4 |
| 89 | doc_0304 | 30.2 | 26.2 | 1.15 | 5 | 0 | 0 | 0s | 0% | 0s | 48.8 |
| 89 | doc_0304 | 199.8 | 26.2 | 7.62 | 3 | 2 | 1 | 176s | 88% | 176s | 34.8 |
| 94 | doc_0324 | 133.1 | 32.8 | 4.06 | 19 | 0 | 0 | 0s | 0% | 0s | 177.8 |
| 94 | doc_0324 | 41.9 | 32.8 | 1.28 | 5 | 0 | 0 | 0s | 0% | 0s | 62.6 |
| 94 | doc_0324 | 198.1 | 32.8 | 6.03 | 3 | 2 | 1 | 178s | 90% | 178s | 40.1 |
| 95 | doc_0327 | 186.4 | 26.8 | 6.96 | 32 | 0 | 0 | 0s | 0% | 0s | 236.2 |
| 95 | doc_0327 | 45.1 | 26.8 | 1.69 | 5 | 0 | 0 | 0s | 0% | 0s | 61.2 |
| 95 | doc_0327 | 196.5 | 26.8 | 7.34 | 3 | 2 | 1 | 178s | 91% | 178s | 30.1 |
| 104 | doc_0352 | 81.0 | 12.8 | 6.35 | 22 | 0 | 0 | 0s | 0% | 0s | 114.5 |
| 104 | doc_0352 | 31.6 | 12.8 | 2.47 | 5 | 0 | 0 | 0s | 0% | 0s | 45.1 |
| 104 | doc_0352 | 194.4 | 12.8 | 15.23 | 3 | 2 | 1 | 177s | 91% | 177s | 27.3 |
| 114 | doc_0380 | 171.9 | 16.5 | 10.42 | 34 | 0 | 0 | 0s | 0% | 0s | 225.7 |
| 114 | doc_0380 | 21.4 | 16.5 | 1.29 | 5 | 0 | 0 | 0s | 0% | 0s | 30.3 |
| 114 | doc_0380 | 194.6 | 16.5 | 11.79 | 3 | 2 | 1 | 178s | 91% | 178s | 26.2 |
| 224 | doc_0727 | 54.1 | 19.3 | 2.81 | 10 | 0 | 0 | 0s | 0% | 0s | 90.5 |
| 224 | doc_0727 | 41.8 | 19.3 | 2.17 | 5 | 0 | 0 | 0s | 0% | 0s | 78.7 |
| 224 | doc_0727 | 205.3 | 19.3 | 10.66 | 3 | 2 | 1 | 177s | 86% | 177s | 75.0 |
| 251 | doc_0858 | 37.7 | 19.2 | 1.97 | 5 | 0 | 0 | 0s | 0% | 0s | 55.3 |
| 251 | doc_0858 | 25.0 | 19.2 | 1.30 | 5 | 0 | 0 | 0s | 0% | 0s | 44.0 |
| 251 | doc_0858 | 198.4 | 19.2 | 10.34 | 3 | 2 | 1 | 177s | 89% | 177s | 42.8 |
| 271 | doc_0927 | 153.5 | 45.5 | 3.37 | 50 | 0 | 0 | 0s | 0% | 0s | 203.9 |
| 271 | doc_0927 | 62.8 | 45.5 | 1.38 | 5 | 0 | 0 | 0s | 0% | 0s | 121.1 |
| 271 | doc_0927 | 210.0 | 45.5 | 4.61 | 3 | 2 | 1 | 178s | 85% | 178s | 82.3 |

**Termination mechanism** — distinct from the grade bucket:

| mechanism | cells |
|---|---|
| `normal_finish` | 30 |


**Median wall clock** 128.2s, range 21.4–210.0s.

### How timeout-mode dead time actually accrues

**Measured, not derived from `60s × injections`.** That formula is wrong here: it would give Q32 1,620s of dead time inside a 900s run. Each injected denial resolves one of two ways inside `call_tool`:

- `asyncio.wait_for` raises `TimeoutError` at `call_timeout_seconds` → `tool.error` carrying a real `duration_seconds` of ~60s. A **full burn**. 20 of 360 injections across this tier.
- the worker task is killed mid-read by `worker_timeout_seconds` or the run deadline → `tool.cancelled`, timed from its `tool.request`. A **partial burn**. 10 of 360.

**Injected-to-cancelled ratio: 36.0:1** across this tier — so roughly two thirds of injections become full 60s burns and one third are cut short when the worker dies. The same ~3:1 ratio appears in Tier 2's timeout cells.

Per denied worker, measured dead time is a median 178s (range 176–178s) against `worker_timeout_seconds: 180`. A denied worker therefore spends very nearly its entire lifetime waiting on reads that will never return — typically two full 60s timeouts plus one cancellation — and contributes no evidence. It is not making three independent 60s reads and surviving; it absorbs ~178s and dies.

Measured delegation-batch wall clock: median 11s (range 3–180s), i.e. a batch costs about one worker timeout because its workers are denied concurrently.

Aggregate dead time sums workers that ran **concurrently**, so it legitimately exceeds wall clock and is an upper bound rather than a decomposition. The critical-path column takes the slowest worker in each delegation batch and sums across batches, which is the figure comparable to wall clock.

## 10. Recorded evidence inventory

| qid | doc | complete | events | artifacts | dangling refs | msgs | docs.json | run.json | answer.txt |
|---|---|---|---|---|---|---|---|---|---|
| 27 | doc_0102 | yes | 296 | 244 | 0 | yes | yes | yes | yes |
| 27 | doc_0102 | yes | 110 | 105 | 0 | yes | yes | yes | yes |
| 27 | doc_0102 | yes | 100 | 98 | 0 | yes | yes | yes | yes |
| 32 | doc_0115 | yes | 377 | 319 | 0 | yes | yes | yes | yes |
| 32 | doc_0115 | yes | 136 | 129 | 0 | yes | yes | yes | yes |
| 32 | doc_0115 | yes | 128 | 124 | 0 | yes | yes | yes | yes |
| 89 | doc_0304 | yes | 354 | 296 | 0 | yes | yes | yes | yes |
| 89 | doc_0304 | yes | 111 | 106 | 0 | yes | yes | yes | yes |
| 89 | doc_0304 | yes | 103 | 101 | 0 | yes | yes | yes | yes |
| 94 | doc_0324 | yes | 274 | 237 | 0 | yes | yes | yes | yes |
| 94 | doc_0324 | yes | 112 | 107 | 0 | yes | yes | yes | yes |
| 94 | doc_0324 | yes | 102 | 100 | 0 | yes | yes | yes | yes |
| 95 | doc_0327 | yes | 409 | 342 | 0 | yes | yes | yes | yes |
| 95 | doc_0327 | yes | 110 | 109 | 0 | yes | yes | yes | yes |
| 95 | doc_0327 | yes | 96 | 98 | 0 | yes | yes | yes | yes |
| 104 | doc_0352 | yes | 219 | 192 | 0 | yes | yes | yes | yes |
| 104 | doc_0352 | yes | 104 | 99 | 0 | yes | yes | yes | yes |
| 104 | doc_0352 | yes | 94 | 92 | 0 | yes | yes | yes | yes |
| 114 | doc_0380 | yes | 403 | 338 | 0 | yes | yes | yes | yes |
| 114 | doc_0380 | yes | 106 | 101 | 0 | yes | yes | yes | yes |
| 114 | doc_0380 | yes | 90 | 88 | 0 | yes | yes | yes | yes |
| 224 | doc_0727 | yes | 160 | 147 | 0 | yes | yes | yes | yes |
| 224 | doc_0727 | yes | 145 | 138 | 0 | yes | yes | yes | yes |
| 224 | doc_0727 | yes | 147 | 143 | 0 | yes | yes | yes | yes |
| 251 | doc_0858 | yes | 89 | 85 | 0 | yes | yes | yes | yes |
| 251 | doc_0858 | yes | 130 | 123 | 0 | yes | yes | yes | yes |
| 251 | doc_0858 | yes | 120 | 116 | 0 | yes | yes | yes | yes |
| 271 | doc_0927 | yes | 456 | 381 | 0 | yes | yes | yes | yes |
| 271 | doc_0927 | yes | 148 | 141 | 0 | yes | yes | yes | yes |
| 271 | doc_0927 | yes | 138 | 134 | 0 | yes | yes | yes | yes |

Messages, intermediate artifacts, tool actions and the question→document dependency map are re-readable from `events.sqlite` + `artifacts/` for 30/30 cells. No artifact is missing and no payload ref dangles.

## 11. Spend and anomalies

| metric | value |
|---|---|
| tier total | $0.7227 |
| tier tokens | 4,801,009 |
| realized $/M | $0.151 |
| projection | ~$0.60; actual $0.7227 = +20%, inside the 50% flag threshold |
| deviation from projection | see §I |
| §5 reference $/M | $0.148 |

### Unpredicted

- Schema validation errors inside worker tool calls: ['ValidationError: 1 validation error for complete_task uncertainties Input should be a vali', 'ValidationError: 1 validation error for complete_task document_ids List should have at lea'].
- 30 cell(s) produced a correct answer despite at least one empty-findings worker: [('27', 'doc_0102'), ('27', 'doc_0102'), ('27', 'doc_0102'), ('32', 'doc_0115'), ('32', 'doc_0115'), ('32', 'doc_0115'), ('89', 'doc_0304'), ('89', 'doc_0304'), ('89', 'doc_0304'), ('94', 'doc_0324'), ('94', 'doc_0324'), ('94', 'doc_0324'), ('95', 'doc_0327'), ('95', 'doc_0327'), ('95', 'doc_0327'), ('104', 'doc_0352'), ('104', 'doc_0352'), ('104', 'doc_0352'), ('114', 'doc_0380'), ('114', 'doc_0380'), ('114', 'doc_0380'), ('224', 'doc_0727'), ('224', 'doc_0727'), ('224', 'doc_0727'), ('251', 'doc_0858'), ('251', 'doc_0858'), ('251', 'doc_0858'), ('271', 'doc_0927'), ('271', 'doc_0927'), ('271', 'doc_0927')].
- 5 cell(s) returned `usage_complete: false`, so `total_cost` was null and cost is token-derived at config rates (cached input priced as uncached, so a slight over-estimate): [('27', 'doc_0102', 1), ('89', 'doc_0304', 3), ('95', 'doc_0327', 2), ('114', 'doc_0380', 1), ('224', 'doc_0727', 1)] as (qid, doc, unreported_calls).

## 12. Prose

Tier 2 establishes that both mitigation strategies work as designed against accidental evidence denial, at measurable and very different costs. Full restart recovered in 20/20 cells with a verified clean slate -- attempt 2 recorded zero injected faults in every cell -- but discards 37% of the arm's tokens as waste by construction, and under timeout manifestation it adds a near-constant ~195s wall-clock penalty. Always-verify detects the denial reliably rather than indiscriminately: 94% recall on the workers that actually held the denied document against a 4% false-positive rate on clean workers in the same runs (98% precision), at a cost of 39% of total tokens, with all of that signal arriving at the worker-result boundary while the plan boundary flagged 0 of 42 plans. Neither strategy changed the outcome -- all 30 cells graded correct -- reproducing section 5's finding that persistent single-document denial under the immediate manifestation has no measurable effect on answer accuracy.

