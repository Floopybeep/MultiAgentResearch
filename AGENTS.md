# MultiAgentResearch repository guidance

## Scope and working principles

This project studies **Failure Propagation and Recovery in Multi-Agent Systems**.
The active task is **FRAMES multi-hop QA** with the question's gold Wikipedia
articles as an oracle local evidence collection. No RAG, global index, or runtime
web search. See README for the current scope and open research design tasks.

The deliverable is a minimal framework migration, not the full Phase 1 study:
local data loading, Lead → parallel Reader Workers → reassessment, `{answer}`,
and a naive hybrid grader. The CLI always performs a fresh real API run; no
synthetic/demo or fixed-example modes.
Keep unresolved design decisions in README and mark existing entries with TODOs;
do not expand them into frameworks. General faults, propagation metrics, restart
and inter-agent verification are not implemented. Phase 2 rollback/detection is out
of scope. Acceptance is the user's real full run and trace inspection. **Do not run
smoke tests or substitute synthetic evidence**, or claim readiness from mock counts.

Prefer the smallest working change. Do not add defensive frameworks, abstractions,
configuration layers, or tests by default. Do not run tests unless requested.
One-off downloads and repairs are process work, not reusable product features:
remove temporary scripts, debug directories, intermediate data and logs when done.
Keep only the final data needed by the main flow. Ask before expanding scope when
a requirement is unclear.

## Final data

The repository-root `corpus/` contains:

- `frames.tsv`: 822 questions, retaining original IDs; 141 and 540 are removed.
- `index.json`: question → document IDs; document ID → title, URL, Markdown filename.
- `doc_0001.md` … `doc_2500.md`: final article bodies and tables.

Question 823 retains its originally annotated Simple English article. Other pages
are normal English Wikipedia. Use the index's source URLs; TSV annotations include
some original malformed links. These are downloaded snapshots, not reconstructed
historical revisions. Keep the same data across comparisons.

The reader has no downloader, cache, repair/exclusion policy files, or data checksum
layer. Do not recreate the removed `.cache/frames/` tree or preparation commands.

## Implementation map

Paths below are under `src/multi_agent_research/` unless stated otherwise:

- `frames.py`: local TSV/index loading, seeded sampling, selected-question Markdown loading.
- `tools/documents.py`: document contracts and question-scoped, paged reading.
- `benchmark.py`: sequential questions, incremental batch manifests, preparation failures and usage.
- `cli.py`: `mar`, corpus directory, sample selection, config/output options.
- `runner.py`: fresh run lifecycle, checkpoints, post-solve grading and final files.
- `runtime.py`: observable model/tool calls, exact document snapshots, usage and exports.
- `schemas.py`: Lead `submit_answer`, worker `complete_task`, reader arguments and state.
- `graphs/research.py`: plan memory, parallel batches, reassessment and final answer.
- `graphs/worker.py`: isolated worker graphs, bounded reading loops and typed failures.
- `grading.py`, `prompts/judge.md`: exact-match then isolated LLM judge.
- `models/adapter.py`: async Chat Completions, explicit endpoint env, SDK retries disabled.
- `tools/memory.py`: artifact-backed Lead plan memory.
- `storage/`, `observability/`: immutable payloads, SQLite events/checkpoints, redaction and usage.
- `viewer.html`, `viewer_export.py`, `viewer.py`: offline graph/QA viewer and optional HTTP serving.
- Root `README.md`, `configs/README.md`: usage and field semantics.

## Behavioral invariants

Keep model/tool calls behind runtime boundaries. Preserve worker isolation, separate
checkpoint threads, parallel `asyncio.gather` batches, assignment-order results,
typed failures, and successful siblings after failures. The Lead saves a plan before
delegation and receives a successful worker before submitting an answer.

Agents receive only the current question's catalog. Out-of-scope document reads
must fail. Workers may return only document IDs read in that assignment. Gold
answers enter only the evaluator after solving, never Lead/worker context. New
Lead/worker prompts must be positive QA instructions, with no report/citation
references or negative comparisons to the old task. Keep upstream prompt references
and licenses unchanged.

Execution completion is distinct from correctness. Exact match extracts one nonempty
unnested brace span, normalizes Unicode/case/whitespace, then compares. Unmatched or
malformed answers go to the independent judge. Judge/API errors leave `correct:null`.
Do not put real FRAMES gold answers in prompt examples.

SQLite events and immutable artifacts are authoritative; browser exports are derived.
Preserve full observable prompts/responses, tool results, document snapshots, parent
IDs, role-specific usage and timing. Dependencies show exposure, not proof of causal
reliance or propagation. Do not infer hidden reasoning from token counts. Checkpoints
support inspection, not recovery/resume. Keep credential redaction and safe exports.

Viewer changes must update **both** `src/multi_agent_research/viewer.html` and
`runs/index.html`. Preserve direct-file use, local assets, Markdown safety, role
colors, archived-run support and separate list/run refresh controls. Retain vendor
licenses and provenance. Credentials and generated traces must stay out of Git.

## Running

Run from the repository root after credential setup:

```bash
uv run mar --config configs/baseline.yaml --sample-size 10 --seed 42
```

`--corpus-dir` defaults to `corpus`; `--question-ids` overrides sampling. Evidence is
always local; model calls use exported `OPENAI_API_KEY` and `OPENAI_BASE_URL`.
`.env` files are not automatically loaded. Use exact model names served by the
chosen endpoint. Do not change model choices in unrelated work.

Open `runs/index.html` directly. `uv run mar-view --runs-dir runs --port 8765` is
optional. Runs contain events, checkpoints, artifacts, `documents.json`, `run.json`,
an answer when produced, and browser exports. Batch manifests are under `runs/batches/`.

The total experiment budget is $50. Use configured rates and returned usage for
cost estimates; estimates are not actual bills or remaining credit. There is no hard
cross-batch dollar cap; parallel calls may exceed a per-question token limit.
