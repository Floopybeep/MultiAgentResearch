# Failure Propagation and Recovery in Multi-Agent QA

A LangGraph framework for studying failure propagation and recovery in multi-agent
systems, using **FRAMES multi-hop question answering**.

## Architecture

![Agent graph](docs/agent-graph.svg)

- **Lead planning and delegation**: the Lead saves a plan and dispatches parallel
  Worker assignments. Each Worker has an independent context and checkpoint thread.
- **Local document reading**: each question provides a catalog of its annotated
  Wikipedia documents. Workers call `read_document(document_id, offset)` to read
  Markdown text and tables, then return findings, document IDs and uncertainties.
- **Lead reassessment**: the Lead integrates the batch's findings in its existing
  context, delegates another batch or calls `submit_answer` with `{answer}`.
- **Hybrid evaluation**: the evaluator extracts and normalizes the answer for exact
  match, then calls an LLM judge when needed. Results include answer correctness,
  format validity and grading method.
- **Execution trace**: SQLite events and payload artifacts record model calls,
  tool responses, agent handoffs, event dependencies, token usage and timing.

## Data

Dataset: **[zhs039/frames-oracle-corpus](https://huggingface.co/datasets/zhs039/frames-oracle-corpus)**

Download the dataset's `corpus/` subfolder from the project root:

```bash
uvx --from huggingface_hub hf download zhs039/frames-oracle-corpus \
  --repo-type dataset --include "corpus/*" --local-dir .
```

```text
corpus/
├── frames.tsv       # 822 questions, retaining original row IDs
├── index.json       # Question → document IDs; document → title, URL, filename
└── doc_*.md         # 2,500 Wikipedia documents
```

Questions 141 and 540 are excluded because required English articles are
unavailable. Question 823 retains its original Simple English Wikipedia article.

## Run

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and an OpenAI-compatible
endpoint supporting Chat Completions and tool calling. Set the role-specific
model names in `configs/baseline.yaml` to those served by the endpoint.

```bash
uv sync --locked
export OPENAI_API_KEY='your-provider-key'
export OPENAI_BASE_URL='your-provider-base-url'
uv run mar --config configs/baseline.yaml
```

Defaults: 10 questions sampled with seed 42. Use `--sample-size N` to change the
count, `--seed N` to change the sample, or `--question-ids ID...` to select original
question IDs. Questions run sequentially; Worker assignments run in parallel batches.
`--corpus-dir` and `--output-dir` select the data and result directories.

See [`configs/README.md`](configs/README.md) for model settings, resource limits
and CLI options.

## Results and trace viewer

Open **`runs/index.html`** in a browser:

- **QA Results**: answer and reference, grading, token usage and timing, with
  expandable Worker findings and per-role statistics.
- **Agent Output Graph**: agent activity, model messages, tool payloads and handoffs.

Per-question outputs are in `runs/<timestamp_run-id>/`: `run.json`, the submitted
answer, document snapshots, SQLite events, payload artifacts and graph checkpoints.
Batch selections and aggregate results are in `runs/batches/`.

## Phase 1 handoff

English `# TODO:` comments mark the extension points below. Paths are relative to
`src/multi_agent_research/`.

| Area and entry point | Current interface | Design work |
|---|---|---|
| Grading — `grading.py:grade_answer` | Extract one `{...}` span; normalize Unicode, case and whitespace; exact match followed by an LLM judge. Store correctness and format validity separately. | Answer aliases, numbers/units, multi-part answers, partial credit, judge rubric/model and error handling. |
| Tool → Worker injection — `runtime.py:read_document` | Paged response with document ID, text, offsets and next-page position. | Target text or table fields; select timing and fault type; record original and injected responses. |
| Worker → Lead injection — `graphs/research.py:build_research` | Structured findings, document IDs and uncertainties at the delivery boundary. | Target Worker/fact; corruption, malicious content, timeouts and stale results; fault scheduling and paired clean/fault runs. |
| Propagation metrics — `runner.py:run_qa` result construction | Event IDs, parent dependencies, handoff payloads, task outcome, usage and timing. | Exposure, adoption and answer impact; affected stages, wasted work and attribution method. |
| Recovery — `runner.py:run_qa` | One attempt per question, with graph checkpoints. | Oracle-triggered full restart, attempt state and memory reset, inter-agent verification, and combined latency/token/cost accounting. |

The experiment protocol also needs subset selection, repeats/seeds, fault
frequencies and result aggregation rules.
