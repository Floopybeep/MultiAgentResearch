# FRAMES QA baseline — 50 questions, 3 repetitions

Baseline for the *Failure Propagation and Recovery in Multi-Agent Systems* study.
Establishes the accuracy and run-to-run variability of the unmodified
Lead → parallel Reader Workers → reassessment pipeline, and selects a question
subset to use as the substrate for later worker-stage fault injection.

**No faults are implemented here.** This directory contains the baseline
measurement, the selection criteria, and the resulting question sets.

## Two sets, deliberately distinct

| Set | Size | File | Definition |
|---|---|---|---|
| **Baseline set** | **50** | `baseline_50_question_ids.txt` | `random.Random(42).sample` over the 822 corpus questions. The accuracy numbers below are measured on these. |
| **Stable subset** | **38** | `stable_38_question_ids.txt` | Of the 50: correct in **all three** runs **and** semantically stable across them. Candidate substrate for fault injection. |

A third, narrower set is recorded in `screening_report.json` but is not given its
own file: the **29** of the 38 that also have an automatically verified injection
target (`eligible.ids`). The remaining **9** (`manual_review`) need human
inspection before use — see Limitations.

```
50 frozen  ──45 correct in all 3 runs──►  ──38 also semantically stable──►  ──29 with a verified target──►
                                                                            └─ 9 to manual review
```

## Configuration

`configs/baseline-pinned.yaml`. Differs from `configs/baseline.yaml`
(**unchanged**, still the artifact under review) in exactly four keys:

| Key | baseline.yaml | pinned |
|---|---|---|
| `lead.options` | `{}` | `{temperature: 0, seed: 42}` |
| `worker.options` | `{}` | `{temperature: 0, seed: 42}` |
| `judge.options` | `{}` | `{temperature: 0, seed: 42}` |
| `max_run_tokens` | `200000` | `600000` |

The judge is pinned because `grading.py:53` is an unpinned LLM call; judge drift
would flip `correct` and be misread as solver instability.

`max_run_tokens` was raised because that budget is **cumulative across the Lead
and every worker**. At 200,000 the workers starved the Lead: on Q25 they consumed
207,508 of 208,356 input tokens, leaving the Lead a single model call, and the
question returned no answer. 3 of the 50 exceed 200,000 tokens and would fail
under `baseline.yaml` as written.

**`seed` is accepted but buys no determinism.** The endpoint is self-hosted vLLM
`0.32.1rc1-tp4`. At `temperature: 0` decoding is greedy, so there is no sampling
RNG for a seed to fix; the residual drift comes from floating-point reduction
order across 4 tensor-parallel shards under continuous batching, which no request
parameter controls.

## Accuracy

| Run | n | correct | wrong answer | no answer | ungraded | accuracy |
|---|---|---|---|---|---|---|
| base1 | 50 | 47 | 3 | 0 | 0 | 94.0% |
| base2 | 50 | 46 | 3 | 1 | 0 | 92.0% |
| base3 | 50 | 45 | 4 | 1 | 0 | 90.0% |

- **45/50 (90%) correct in all three runs**; 47/50 correct at least once; 3 never correct (Q99, Q667, Q761).
- Mean per-run accuracy **92.0%**.
- **`ungraded` was 0 in every run** — no judge or API errors, so no `correct: null`.

`no answer` is held separate from `wrong answer` on purpose.
`runner.py:88` stores an unanswered task as `correct: False`, so
`benchmark.summarize` files it under `incorrect`. Base3's manifest reads
`incorrect: 5`, but only 4 were wrong answers; the fifth produced no answer at
all. Execution completion and correctness are distinct.

### Format validity, reported separately from correctness

| Run | `format_valid` |
|---|---|
| base1 | 50/50 (100%) |
| base2 | 49/50 (98%) |
| base3 | 49/50 (98%) |

Both failures are Q783 and are consequences of budget exhaustion — there was no
response to parse. **Zero genuine formatting failures in 150 question-runs**: the
single-brace rule at `grading.py:21` never rejected a real answer.

### Grading method

`exact_match` 23 / 24 / 22 per run; `llm_judge` 27 / 25 / 27; `judge_error` 0.
Of the 38-question subset, 22 were graded `exact_match` in all three runs, so
their grade is deterministic given the answer string and never invokes the judge.

## Variability (measured, not assumed)

`temperature: 0` is greedy decoding, not determinism. Across the three runs:

| Signal | Changed |
|---|---|
| **Worker count per question** | **24/50 — 48%** |
| Answer string (exact) | 13/50 — 26% |
| **Answer meaning (normalized)** | **10/50 — 20%** |
| Grading method | 2/50 |
| **Grade (`correct`)** | **2/50 — 4%** (Q694, Q783) |

Per-run worker totals drifted 98 → 100 → 104. Of the 24 questions with varying
worker counts, 21 varied by 1 and 3 varied by 2 (Q6 went 1→2→3). Worker-count
variance and answer variance are **largely independent** — only 3 questions
changed both — so delegation drift does not explain most answer drift.

**Token consumption is highly variable.** Q783 used 388,574 tokens in base1
(64.8% of the 600,000 cap) and 628,492 in base2 (104.8%), failing twice. Drift
runs the other way too: Q25 287k→171k, Q716 282k→176k, Q606 104k→36k.

**Implication for fault injection:** the noise floor is ~20% on answer meaning
and ~4% on grade. An injected effect smaller than that is not distinguishable
from drift in a single run, so repetitions per condition are required.

## Selection criteria for the 38

All of the following, measured across all three runs:

1. `correct == true` in all 3 runs.
2. Answer **semantically stable**: identical after Unicode/case/whitespace
   normalization plus unit canonicalization (`21 m` ≡ `21 meters`), ordinals
   (`sixth` ≡ `6th`) and magnitudes (`2 million` ≡ `2,000,000`).
   Reported in two tiers: **35 strictly stable** (byte-identical) and
   **3 semantically stable only** (Q30, Q114, Q143).

The 12 excluded break down disjointly as **7** correct-but-unstable
(Q94, Q221, Q226, Q239, Q390, Q460, Q518) and **5** not correct in all three
(Q99, Q667, Q694, Q761, Q783). Note these reasons overlap for some questions:
Q99 is both, Q694 is both, Q783 is both an execution failure and unstable.

For the narrower 29, a third criterion applies — an injection target whose
containing page was read by a worker **in every run**, verified from
`tool.result` offsets in `events.sqlite`, and which shares a content token with
the gold answer. The gold answer appears verbatim in only 28 of 50 questions, so
targets are allowed to be intermediate facts needed to derive the answer rather
than the answer itself.

## Limitations

1. **This is not a baseline of `configs/baseline.yaml` as written.** The token
   budget was raised 3×. Three questions exceed the original 200,000 cap.
2. **Exposure is proven; causal reliance is not.** A verified target means a
   worker *read* a page covering the span, not that it *relied* on that span to
   derive its finding. `echoed_in_runs` (the span text reappearing in the
   worker's findings) is circumstantial, not proof. A document may state the
   same fact in several places, so corrupting one occurrence may change nothing:
   **10 of the 29** targets are flagged `redundant`.
3. **The relevance test has a known blind spot.** It requires a shared content
   token between span and gold answer, which false-negatives on arithmetic and
   date derivations — gold `74 years` versus source fact `1947` shares no token.
   Most of the 9 manual-review questions are this case and several are probably
   good targets; the test simply cannot prove it. **29 is a conservative floor
   and 38 an optimistic ceiling.**
4. **Read-coverage verification is weakly discriminating here.** 35 of 38 targets
   fall inside the first `max_document_chars` page, which workers almost always
   read, so "read in all runs" rarely excludes anything.
5. **Shared endpoint.** Runs executed against a multi-tenant campus endpoint;
   observed variance includes contention from unrelated traffic.
6. **Three repetitions** is enough to detect instability, not to estimate its
   rate precisely.
7. `system_fingerprint` is a constant vLLM build string here, not a per-config
   hash, so it cannot detect silent routing changes — only a vLLM upgrade. It
   was identical across all three runs.

## Defects found in the pipeline (reported, not fixed)

1. `runner.py:88` — unanswered tasks stored as `correct: False`, conflating
   execution failure with an incorrect answer.
2. `max_run_tokens` is a single budget shared by the Lead and all workers, so
   workers can starve the Lead of the turns needed to answer.
3. `models/adapter.py:30` — SDK retries disabled, so a transient 5xx kills a
   call outright. None occurred in 1,191 calls.
4. `cli.py:42` exits non-zero if any question is ungraded, so a healthy batch can
   look failed. Read `runs/batches/*.json`, not the exit code.

## Reproducing

```bash
export OPENAI_API_KEY=... OPENAI_BASE_URL=...
IDS=$(cat eval/baseline_50_question_ids.txt); IDSA=(${=IDS})   # zsh: ${=IDS} splits
uv run mar --config configs/baseline-pinned.yaml --corpus-dir corpus \
    --output-dir runs/base1 --question-ids "${IDSA[@]}"
# repeat for base2, base3, then:
uv run python eval/screen_baseline.py runs/base1 runs/base2 runs/base3 \
    --corpus-dir corpus --out eval/screening_report.json
```

`eval/screen_baseline.py` makes **no API calls** — it reads batch manifests, run
event logs and the local corpus. `--require-exact-match` turns the exact-match
preference from a reported statistic into a hard filter (which would cut the
eligible set to 22).

Run traces are **not committed** (`runs/*` is gitignored); regenerate them with
the commands above. Figures here come from batch manifests, never exit codes.

## Provenance

| | |
|---|---|
| Commit | `03bf890be11a1d60129fa68b55c0a132a56b3525` |
| Model | `api-glm-5.3-flash` |
| Endpoint build | vLLM `0.32.1rc1.dev555+geca54bd1d-tp4`, identical across runs |
| Resolved config hash | `4fc6b425caa32c1269939546fa833a3b875e584d87add9997e607ae1ace04479` (excluding `output_dir`) |
| Config file sha256 | `42ca554b8f5151a08215476fd0f99e581f802cec1b911c1f766ce628179b8076` |
| Corpus fingerprint | `99f7808f416e31b01b7dee33aaf9abe8b6d34e01` (2500 `.md` files) |
| Batches | `261103_182127_…`, `261103_184106_…`, `261103_190944_…` |
| Totals | 8,090,395 input / 400,393 output tokens, 1,191 model calls |
| Estimated cost | $1.168 for the 3 runs; $1.279 including configuration pilots |

Cost is configured rates × returned usage — an estimate, not a bill.

## Files

| File | Contents |
|---|---|
| `baseline_50_question_ids.txt` | The 50 baseline IDs, space-separated for `--question-ids` |
| `baseline_50_provenance.json` | Selection, hashes, fingerprints, pilot record, derived subsets |
| `stable_38_question_ids.txt` | The 38 stable, consistently correct IDs |
| `stable_38_questions.html` | Open directly in a browser to select a stable question ID and view its question, gold answer, and collapsible full local articles. Embeds corpus snapshots; uses the repository’s local Markdown renderer. |
| `screen_baseline.py` | Offline screening script |
| `screening_report.json` | Full machine-readable results, including per-question targets and caveats |
