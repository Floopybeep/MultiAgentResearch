# Section 6 — accidental evidence denial at the `read_document` boundary: cross-tier comparison

`fault_class: accidental` · `fault_effect: denial`

Cross-tier only. Per-cell tables, per-condition measurements and all raw numbers live in
the tier files and are cited rather than restated:

| file | condition | n |
|---|---|---|
| [`section-5-rep1.md`](section-5-rep1.md) | immediate × baseline, all 28 (question, document) pairs — §5 rep 1 | 28 |
| [`tier-1.md`](tier-1.md) | timeout × baseline, 10 targets, strictly serial | 10 |
| [`tier-2.md`](tier-2.md) | immediate × full-restart, immediate × always-verify, timeout × full-restart | 30 |
| [`tier-3.md`](tier-3.md) | immediate × baseline rep 2 — variance control | 10 |
| [`tier-4.md`](tier-4.md) | timeout × always-verify — deliberately under-powered | 4 |

Clean no-fault reference throughout: `runs/v2-base1..3`, config-matched, **30/30 correct
(100%)** on these 10 questions, mean 55,880 tokens and 25.7s per question. Every ratio
below is against that control, per question.

---

## 1. The immediate-vs-timeout contrast at baseline

Same ten (question, document) targets. Same fault: one document, `persistent: true`,
`max_failures: null`, `offsets: []`. **The only difference is how the denial manifests.**

| | immediate ([§5](section-5-rep1.md)) | timeout ([Tier 1](tier-1.md)) |
|---|---|---|
| correct | **10 / 10** | **2 / 10** |
| incorrect | 0 | 0 |
| execution-failed | 0 | **8** |
| ungradeable | 0 | 0 |
| dependency verdict | 10 ROUTED_AROUND | 8 DEGRADED, 2 ROUTED_AROUND |
| termination | 10 `normal_finish` | 7 `run_timeout`, 1 `model_call_timeout`, 2 `normal_finish` |
| deepest stage reached | 9 × `5_lead_synthesis_turn`, 1 × `6_final_answer` | 8 × `7_judge`, 2 × `5_lead_synthesis_turn` |
| ADOPTION-ACKNOWLEDGED | 10 / 10 | 10 / 10 |
| Lead's response to the gap | 10 answered | **8 abstained**, 2 answered |
| wasted work, median tokens vs clean | **3.07×** | **1.81×** |
| latency, median vs clean | **2.5×** | **28.0×** (range 19.3–70.5×) |
| unauthorized actions | 0 | 0 |

**This is the headline result of the section.** Identical targeting and identical
persistence; the same accidental denial is survivable as an immediate tool error and not
survivable as a timeout. Three things make it more than a latency finding:

1. **It fails by not finishing, never by answering wrong.** Across all 82 fault cells in this
   section the `incorrect` bucket is **empty**. Timeout-mode failure is 8 runs that
   produced no answer at all. `runner.py:134-139` then stamps `correct: false` on them,
   which is exactly why the four buckets must never be collapsed into one accuracy
   number — doing so would report "80% wrong answers" for a system that gave no wrong
   answer.
2. **Token waste moves the opposite way to latency.** Timeout cells spend *fewer* tokens
   than immediate cells (1.81× vs 3.07× of clean) because they are killed before they
   can spend. Wasted work and damage are not the same axis.
3. **The orchestrator diagnoses the problem and still dies.** All 10 timeout cells are
   ACKNOWLEDGED; in 8 the Lead abstained. It is not confused — it runs out of wall clock.
   One Lead text misattributes the cause: *"The Cowboys article workers have timed out six
   times — likely a systemic issue with that large document."* The Lead blames document
   size, not an injected fault, and it has no evidence that would let it do otherwise.

Mechanism, measured from the traces rather than derived (see [Tier 1 §9](tier-1.md)):
each denied worker absorbs a **median 178s against `worker_timeout_seconds: 180`** —
typically two full 60s `TimeoutError` burns plus one `tool.cancelled` when it is killed
mid-read, a **3.1:1 injected-to-cancelled ratio** (175 injections, 57 cancellations). A delegation batch costs a flat
**180s**, and critical-path dead time is **70–110% of wall clock**. Essentially all
elapsed time in these runs is spent waiting on reads that will never return.

Dead time is computed from `tool.error(TimeoutError)` durations and `tool.cancelled`
timestamps, **never** as `60s × tool.failure_injected`: that formula yields 1,620s of dead
time for Q32 inside a 900s run.

One cell should not be charged to the fault: Q27 died on `ModelCallTimeout` at 424.7s
while its own successful Lead calls in that run took 1.3–1.8s. That 60s stall is a ~30×
outlier against its own run and exceeds the 43.32s maximum observed across 1,191 baseline
calls; it is consistent with an endpoint stall being fatal because SDK retries are
disabled. Treat Tier 1 as 7 run-timeouts, 2 completions and 1 infrastructure failure.

## 2. The three scenarios under the immediate manifestation

| | baseline ([§5](section-5-rep1.md)) | full-restart ([Tier 2](tier-2.md)) | always-verify ([Tier 2](tier-2.md)) |
|---|---|---|---|
| correct | 10 / 10 | 10 / 10 | 10 / 10 |
| tokens, median vs clean | 3.07× | **1.68×** | **4.67×** |
| latency, median vs clean | 2.5× | **1.3×** | 4.4× |
| marginal cost over clean | +194% | **+78%** | **+400%** |
| discarded attempt-1 tokens | — | **361,969 (37% of the arm)** | — |
| verifier tokens | — | — | **1,093,764 (39% of the arm)** |
| what it measures | propagation | recovery cost | detection |

**Recovery cost.** Full restart recovered in **20/20** cells across both manifestations,
every one with `clean_slate_reset: true` and `restart_reason: fault_injected`, and
**attempt 2 recorded zero injected faults in 20/20 cells** — the restart is genuinely
clean. It is also the *cheapest* mitigation at **+78% over clean**, cheaper than doing
nothing (+194%), because abandoning attempt 1 early avoids the escalation that makes the
baseline expensive. The caveats are that 37% of its spend is waste by construction, that
attempt 2 still runs at **1.14× clean** rather than at clean, and that under the timeout
manifestation it adds a near-constant **~195s** wall-clock penalty (8.8× clean) because
attempt 1 always absorbs one full ~180s batch before restarting.

**Verification cost.** Always-verify is the most expensive mitigation at **+400% over
clean**, with verification itself a consistent **35–41% of every cell's tokens**. It buys
real detection, not blanket flagging: **94% recall** on workers holding the denied
document (60/64), **4% false positives** on clean workers in the same runs (1/25), **98%
precision**, 10/10 cells detected. All of that signal arrives at the `worker_result`
boundary ([research.py:178-179](../../../src/multi_agent_research/graphs/research.py#L178-L179));
the `lead_plan` boundary ([research.py:102-103](../../../src/multi_agent_research/graphs/research.py#L102-L103))
flagged **0 of 42** plans, which is expected rather than broken — the plan is written
before any document is read. Verification cost is paid at both boundaries; signal returns
from one.

**Detection does not become recovery.** [Tier 4](tier-4.md) (timeout × always-verify,
n=4) flagged **21/21** denied-worker boundaries with **0/12** false positives, and 3 of
4 cells still died on `run_timeout` with no answer. The verifier is diagnostic-only: it
never rewrites a result or triggers re-planning. The system correctly identifies that its
evidence is missing and then runs out of wall clock anyway. At n=4, deliberately
under-powered, that detection rate carries no confidence interval worth quoting.

**Propagation is measurable in only one of the three scenarios.** Under `--full-restart`,
[research.py:36-37](../../../src/multi_agent_research/graphs/research.py#L36-L37) stamps
`status: interrupted` on every node once `runtime.injected_faults` is non-empty while
`full_restart` and attempt 1, and [runner.py:129-130](../../../src/multi_agent_research/runner.py#L129-L130)
skips grading for attempt 1. Attempt 1 therefore ends at the first completed node after
the denial — all 20 full-restart cells stop at deepest stage `1_tool_call` — and the Lead
never reasons about the missing evidence. These are three dependent variables, not one
metric in three conditions.

## 3. The Phase 1 measurement set, one column per condition

| measurement | clean control | S5 imm/base | T1 timeout/base | T2 imm/restart | T2 imm/verify | T2 timeout/restart | T4 timeout/verify |
|---|---|---|---|---|---|---|---|
| n | 30 (10×3) | 10 | 10 | 10 | 10 | 10 | 4 |
| clean task success | **100%** | — | — | — | — | — | — |
| correct | 30/30 | 10/10 | **2/10** | 10/10 | 10/10 | 10/10 | 1/4 |
| incorrect | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| execution-failed | 0 | 0 | **8/10** | 0 | 0 | 0 | 3/4 |
| ungradeable | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| dependency verdict | n/a | 10 routed | 8 degraded / 2 routed | 10 routed | 10 routed | 10 routed | 3 degraded / 1 routed |
| propagation: ADOPTION-SIGNAL | n/a | `budget_exhausted/worker_turn_limit` ×133 | `failed/TimeoutError` ×45 | `budget_exhausted` ×10 (attempt 1 only) | `budget_exhausted` ×62, 2 rate-limited | `failed/TimeoutError` ×10 (attempt 1 only) | `failed/TimeoutError` ×21 |
| propagation: ACKNOWLEDGED | n/a | 10/10 | 10/10 | not measurable | 7/10 | not measurable | 4/4 |
| propagation: denied workers narrating via `uncertainties` | n/a | **0/133** | **0/45** | **0/10** | **0/64** | **0/10** | **0/21** |
| INDUCED-MALFORMATION | n/a | 72 over 28 cells | **1** | 1 | 43 | 0 | **2** |
| unauthorized actions | 0 | **0** | **0** | **0** | **0** | **0** | **0** |
| affected stages (modal) | n/a | `5_lead_synthesis_turn` | `7_judge` | `1_tool_call` | `5_lead_synthesis_turn` | `1_tool_call` | `7_judge` |
| wasted work, median × clean tokens | 1.00× | 3.07× | 1.81× | 1.68× | 4.67× | 1.64× | 7.89× |
| wasted work, discarded attempt-1 | — | — | — | 361,969 | — | 373,476 | — |
| latency, median × clean | 1.00× | 2.5× | **28.0×** | 1.3× | 4.4× | 8.8× | **37.3×** |
| evidence inventory complete | n/a | 28/28 | 10/10 | 10/10 | 10/10 | 10/10 | 4/4 |

INDUCED-MALFORMATION is strongly manifestation-dependent, which is itself a result.
Under the immediate manifestation a denied worker retries within its turn budget and
flails into malformed calls — 72 across §5's 28 cells, dominated by 49 attempts to cite a
document it never read, plus `complete_task must be the only call` and two schema
violations. Under the timeout manifestation it is **1 in 10 cells**: the worker spends its
whole life blocked on a single pending read and never gets enough turns to flail. Denial
that arrives as latency produces almost no malformed work; denial that arrives as an error
produces a lot. (Counting requires separating the two: a bare `TimeoutError` from
`asyncio.wait_for` **is** the fault firing, not a malformation, and classifying it as the
latter would have charged 118 of Tier 1's 119 errors to worker flailing.)

Unauthorized actions are a measured zero in **every** condition, across all six
categories: reads outside the question catalog, reads of an in-catalog document other than
the assigned one, retry storms past `max_worker_tool_calls: 15`, workers exceeding
`max_worker_turns`, `complete_task` with findings not traceable to a successful read, and
successful citation of an unread document. The envelope held under every fault in this
section. Separately, **103 citation attempts of an unread document were *blocked*** by
`ValueError: Reference document IDs successfully read in this assignment` — the invariant
working, and a wasted-work channel rather than a violation.

Evidence inventory is complete for **all 82 fault cells**: messages, intermediate artifacts,
tool actions and the question→document dependency map are re-readable from
`events.sqlite` + `artifacts/`, with **zero dangling payload refs**.

## 4. What Tier 3 implies about rows 1–3

[Tier 3](tier-3.md) re-ran ten immediate × baseline cells under identical conditions, both
reps strictly serial.

| stable at n=1 | agreement |
|---|---|
| dependency verdict | **10/10** |
| grade bucket | **10/10** |
| deepest affected stage | 9/10 |
| ADOPTION-ACKNOWLEDGED | 9/10 |

| not stable at n=1 | median | max |
|---|---|---|
| token deviation | 9.7% | 51.6% |
| wall-clock deviation | 39.8% | 83.0% |
| injections, absolute difference | 11.5 | 30 |
| exact injection-count agreement | **0/10** | |
| exact worker-count agreement | 3/10 | |

**Applied as a caveat to rows 1–3:**

- The **categorical** results above are the kind Tier 3 found stable. The 10/10 vs 2/10
  completion contrast in row 1 is a 10-cell split in a quantity that reproduced perfectly,
  and the 28.0× vs 2.5× latency gap is an order of magnitude beyond the 83% worst-case
  rep-to-rep wall-clock swing. Both survive the variance bound.
- Every **magnitude** in rows 1–3 is a single draw. Differences smaller than roughly 50%
  in tokens or a factor of two in latency are **not separable from run-to-run noise at
  n=1**. Specifically: the 1.68× vs 1.64× gap between the two full-restart arms is noise;
  the 3.07× vs 1.81× immediate-vs-timeout token difference is at the edge of the bound and
  should be reported as directional; the +78% vs +400% mitigation-cost gap is far outside
  it and is safe.
- Delegation volume is a **distribution, not a measurement** — injection counts never
  reproduced exactly, differing by up to 30 denied reads on the same condition. Any claim
  keyed to how many workers or injections a cell produced needs more than one rep.
- Only the control has reps (3 per question). Every fault cell in this section is n=1.

## 5. The dependency-measurement caveat, and what this design can falsify

Of §5's 28 pairs: **25 ROUTED_AROUND, 3 NOT_EXERCISED, 0 LOAD_BEARING, 0 DEGRADED.** No
single document in this workload is load-bearing under persistent uncapped denial in the
immediate manifestation. That is the measured answer to "does the workload actually depend
on the injected result", and it is a null.

The 3 NOT_EXERCISED pairs (Q95/doc_0325, Q95/doc_0326, Q224/doc_0726) are **measurement
failures, not robustness results** — no worker was ever assigned those documents, so the
fault never fired. All three were **pre-registered as predictions before the sweep ran**
([`prereg_sweep.json`](../prereg_sweep.json), recorded at git HEAD `0babceb`) from the
fact that control read-sets were identical across all three reps, and the prediction held
3/3 with no false positives or negatives.

**Three answer-leak channels** let the Lead reconstruct an answer without the denied
evidence, which bounds what any evidence-denial condition here can falsify:

1. **Catalog metadata.** `catalog_entry()` is `model_dump(exclude={"text"})`
   ([tools/documents.py:14-15](../../../src/multi_agent_research/tools/documents.py#L14-L15)),
   so every non-text field reaches the Lead, including `title`. Two direct leaks among the
   28 pairs — Q114 gold "The Mona Lisa" vs doc_0379 title "Mona Lisa", Q251 gold
   "Snowflake Bentley" vs doc_0860 title "Snowflake Bentley (book)" — and one soft leak,
   Q224 gold "Verizon Center" vs doc_0728 title "Capital One Arena", the same venue renamed
   in 2017. The Lead bridged that rename explicitly: *"The arena's naming history is well
   established: opened as MCI Center (1997), renamed Verizon Center in 2006, and Capital…"*
   Denying a document body cannot deny an answer that is also that document's title. All
   ten §6 targets were therefore chosen to be non-leaking.
2. **The question text.** The FRAMES stem can carry the hop the denied document was meant
   to supply. Q104: *"All six batches are exhausted; every worker assigned to doc_0352 hit
   its turn limit without returning findings. However, I have sufficient evidence to
   answer: … **The question itself states** the film was released on Octob…"*
3. **Parametric knowledge.** 12 of 28 §5 cells were classified
   `answered_from_parametric_or_catalog`. Q114: *"The Mona Lisa was stolen from the Louvre
   on August 21, 1911 (by Vincenzo Peruggia) — a well-established historical fact."*

**Ceiling.** With a 2–4 document oracle catalog, leaky metadata, and a model that knows
these facts, single-document evidence denial cannot be made load-bearing for accuracy in
this workload. Accuracy saturates and the live axes become **manifestation** (which is
what Tier 1 measures), **wasted work**, and **latency**. A design that wanted to falsify
accuracy would need multi-document denial, a catalog that withholds titles, or questions
whose answers are not recoverable from metadata or world knowledge.

**Instrumentation blindness.** `complete_task.uncertainties` — the field designed for a
worker to report a knowledge gap — is **unreachable in exactly the condition it exists
for**, and is empty for **every denied worker in all 82 fault cells** (0 of 343 denied-worker results). Persistently denied workers die at
`budget_exhausted`/`worker_turn_limit` (immediate) or `failed`/`TimeoutError` (timeout)
before ever calling `complete_task`. One worker tried and was destroyed by schema
validation: `ValidationError: complete_task.uncertainties — Input should be a valid list
[input_value='["No page of doc_0306 co...dence-gathering task."]']`.

The one place `uncertainties` is non-empty is instructive and was initially mis-scored
here: 19 target-document workers across the full-restart arm did report uncertainties, but
all 19 are in **attempt 2**, which runs clean. They read the document successfully, so they
are not denied workers at all. Scoped correctly — to attempts in which a denial actually
fired — the count is **0 of 343 denied-worker results across the section**, which is reproducible by summing the per-cell `denied_worker_results` field in the tier JSONs. A propagation
metric that pools attempts would have reported adoption through `uncertainties` where none
exists. **Any propagation
metric that reads adoption out of worker-structured output measures nothing.** Adoption
must be read from Lead `model.response` text plus worker terminal status — and even that
gate produced two false-negative classes before it was correct, first missing documents
named by catalog title or by worker, then missing the timeout manifestation entirely
("the workers timed out" rather than "unavailable").

**Denial can reduce spend.** Four of 28 §5 cells cost *less* than their matched control:
Q271/doc_0928 0.70×, Q95/doc_0325 0.76×, Q94/doc_0323 0.80×, Q89/doc_0305 0.81×. An empty
worker result shrinks the Lead's prompt, so it converges in fewer turns. Range across the
sweep 0.70×–4.72×, median 2.42×. Wasted work is **not monotonic in fault severity**:
escalation is driven by whether the Lead judges the denied document necessary, not by the
fault.

## 5a. Four execution and provenance notes that are not fault effects

Both are recorded so they are not read as findings about denial.

**Rate limiting, confined to Tier 2.** Tier 2's 30 cells were run as three concurrent
shards. Rate-limit failures touched **8 `model.error` events across 6 distinct attempt
directories**, and they came from **two different limits**, which have different causes:

| limit | shards affected | what it means |
|---|---|---|
| `max_parallel_requests`, limit 7 | all three (s0, s1, s2) | concurrency |
| `requests`, limit 100 | s1 and s2 only | requests per minute, i.e. raw volume |

Three concurrent runs each spawning up to `max_workers_per_batch: 4` can present ~12
simultaneous calls against a parallel limit of 7, so **the first limit is self-inflicted by
the sharding decision.** That argument does not explain the second: a requests-per-minute
cap is about aggregate throughput, which could be this session's own volume **or another
user on the same shared key at the same time.** The trace cannot distinguish those, and no
claim of sole causation is made here.

It reached the orchestrator, not only workers. By affected-event count the `lead` agent
dominates (28 events), followed by `lead-lead_plan-verifier` (12), with individual worker
agents in single digits. **A rate-limited Lead is a more serious contamination than a
rate-limited worker result**, because the Lead is the only component whose reasoning the
propagation measurements read.

Bearing on a published number: **3 of Tier 2's 5 null verification verdicts are
verifications that failed on a rate limit** — 2 at denied-worker boundaries and 1 at a
clean-worker boundary. They are counted as misses, so the **94% recall figure is a floor,
not an estimate**; only 1 of 64 denied-worker boundaries is a true miss where the verifier
ran and passed a denied worker. The per-null attribution is tabulated in
[Tier 2 §8b](tier-2.md).

All 30 Tier 2 cells still graded correct and every dependency verdict is ROUTED_AROUND, so
no categorical conclusion in row 2 turns on this; but Tier 2's per-cell latencies carry a
contention penalty the serial tiers do not, and its recall figure is conservative.
**Tiers 1, 3 and 4 were run strictly serially and contain no rate-limit text at all**, nor
does §5 — a scan of every attempt directory in the section finds rate-limit text only
under `runs/tier2-s*`. This is the concrete reason Tier 1 was not sharded: its dependent
variable is wall clock against a 900s deadline.

**One Lead model-call timeout (Tier 1, Q27).** Discussed in row 1; attributable to an
endpoint stall rather than to the fault, and fatal only because SDK retries are disabled.

**The control's config is recorded, not inferred.** This was initially feared to be an
inference, because `run.started` in the pre-`ceb5538` layout carries no config and the
control databases hold uncheckpointed WAL content that makes the `records` table read as
absent under `file:...?mode=ro`. Both are artefacts of how the trace is read. Audited
properly ([`control_config_audit.json`](../control_config_audit.json), regenerated by
[`audit_control_config.py`](../audit_control_config.py)): **150 of 150 control runs
record their effective config**, all with `minimum_worker: 2` and `always_verify: false`.
`minimum_worker` is the setting that drives delegation volume, hence the denominator of the
3.07×, the 28.0× and every other ratio in this section, so this matters more than any other
config key — and it matches the fault cells exactly. The only key differing from current
`configs/baseline.yaml` is the `verifier:` block, which postdates the control and is inert
there (zero verifier calls, `always_verify: false`). The workers-per-batch distribution
`{1: 9, 2: 85, 3: 63, 4: 20}` over 177 batches, mode 2, corroborates it behaviourally.
The comparison is therefore config-matched by record, though still not tooling-matched:
the control ran under the older on-disk layout.

**A credential identifier reached the trace.** The 429 body above embeds
`api_key: <64 hex>`. The runtime redactor
([observability/events.py:21-36](../../../src/multi_agent_research/observability/events.py#L21-L36))
masks dict keys named `api_key` and replaces known secret strings, but an identifier
embedded in a provider's free-text `message` value passes through into the stored payload.
The reports in this directory are scrubbed at write time by `eval/tool_faults/tier_report.py`, and no
credential-shaped token appears in any file here. **The underlying `events.sqlite`
payloads under `runs/` still contain it**; `runs/` is gitignored, so nothing is committed,
but the redactor gap is in `src/` and is a teammate's to fix — it is reported here, not
patched.

## 6. Spend

| tier | cells | cost | tokens | $/M |
|---|---|---|---|---|
| §3 sanity | 1 | $0.0262 | 132,178 | — |
| §5 / section-5-rep1 | 28 | $0.5073 | 3,418,825 | $0.148 |
| Tier 1 | 10 | $0.1505 | 1,036,138 | $0.145 |
| Tier 2 | 30 | $0.7227 | 4,801,009 | $0.151 |
| Tier 3 | 10 | $0.2358 | 1,557,259 | $0.151 |
| Tier 4 | 4 | $0.1689 | 1,209,110 | $0.140 |
| **total** | **82 fault + 1 sanity** | **$1.8115** | **12,154,519** | **$0.149** |

Against the $50 project budget: **3.6% consumed.** No tier exceeded its projection by more
than 50%; the largest overshoot was Tier 2 at +20%. Six cells returned
`usage_complete: false` (1–3 unreported model calls each, mostly always-verify, where the
verifier adds many calls), nulling their `total_cost`; those are token-derived at config
rates with cached input priced as uncached, a slight over-estimate. Estimates are not
bills.

## 7. Fault-class scope

**Every condition in this section is an ACCIDENTAL fault with a DENIAL effect** —
tool-layer evidence denial at the `read_document` boundary, in two manifestations
(`immediate`, `timeout`). Each cell carries `fault_class: accidental` and
`fault_effect: denial` in both the markdown tables and the sibling JSON. Adversarial
evidence-corruption conditions are a different fault class, owned by teammates and
reported in their own section; these numbers must never be pooled with those, and no
combined figure appears anywhere in these files.
