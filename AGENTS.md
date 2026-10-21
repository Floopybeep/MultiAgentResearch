# MultiAgentResearch Repository Overview

## Project Description

MultiAgentResearch is a standalone research framework for studying failure propagation and recovery in multi-agent deep research. The current implementation is a clean LangGraph baseline reproducing Anthropic's **publicly documented Research architecture**, with structured logging and an offline run viewer. It is not an exact copy of Anthropic's unpublished production system.

Fault injection, recovery policies, and comparative evaluation are planned extensions, not implemented baseline features. The fault categories and project plan are documented in `README.md`. The sibling `../open_deep_research/` repository is a reference implementation; this package is developed independently.

## Repository Structure

### Root Directory

- `README.md` - Project plan, architectural decisions, limitations, and execution instructions.
- `AGENTS.md` - Repository overview and guidance for coding agents.
- `pyproject.toml` - Python dependencies, CLI entry points, and test/lint configuration.
- `uv.lock` - Locked dependency versions; update alongside dependency changes.
- `.env.example` - Environment variable names; never put real credentials here.
- `.venv/` - Local virtual environment managed by uv; gitignored.
- `configs/baseline.yaml` - Role-specific models and run/resource limits.
- `configs/README.md` - Configuration field reference, defaults, and semantics.
- `docs/agent-graph.svg` - Pipeline diagram embedded in the README.

### Core Implementation (`src/multi_agent_research/`)

- `cli.py` - `mar` command: query, configuration, output directory, and offline demo selection.
- `runner.py` - Run lifecycle, graph invocation, final status, and output files.
- `runtime.py` - Shared run resources and observable model/tool execution boundaries.
- `config.py` - Validated Pydantic run and model settings.
- `schemas.py` - Graph state, tool arguments, source documents, and worker-result contracts.
- `demo.py` - Scripted model, search, and fetch fixtures for credential-free testing.

### Agent Graphs (`src/multi_agent_research/graphs/`)

- `research.py` - Lead planning, plan-memory tools, parallel batch dispatch/join, reassessment, and draft submission.
- `worker.py` - Isolated worker contexts with bounded search/fetch loops and structured completion.
- `citations.py` - Citation-agent invocation and deterministic output validation.

The lead saves a plan before delegation, waits for a parallel batch of independent workers, and may delegate additional batches before writing the draft in its existing context. Workers run as separate checkpointed graphs joined with `asyncio.gather`; results return in assignment order. The citation agent adds source/paragraph markers without changing the draft. Validation checks text preservation and reference existence, not factual correctness. There is no separate writer or compression agent.

### Models, Tools, and Prompts

- `models/adapter.py` - Async OpenAI Chat Completions through `ChatOpenAI`, with explicit endpoint credentials, `use_responses_api=False`, and SDK retries disabled.
- `tools/search.py` - Tavily search returning titles, URLs, and snippets.
- `tools/fetch.py` - Bounded public HTML/plain-text retrieval and extraction.
- `tools/memory.py` - Lead-accessible plan memory backed by stored artifacts and records.
- `prompts/` - Active lead, worker, and citation prompts.
- `prompts/upstream/` - Pinned Anthropic Cookbook references, provenance manifest, and license. Document adaptations in `prompts/README.md`; keep upstream references intact.

### Storage and Observability

- `storage/artifacts.py` - Content-addressed JSON artifacts with integrity checks.
- `storage/database.py` - SQLite event and run-record persistence.
- `storage/checkpoints.py` - Persistent LangGraph SQLite checkpoints.
- `observability/events.py` - Event IDs, dependencies, payload references, and credential redaction.
- `observability/usage.py` - Reported token usage and optional cost estimates.

Keep model and tool calls behind the runtime's observable boundaries. SQLite and artifact JSON are authoritative; browser exports are derived data. Preserve worker isolation, typed failure results, source provenance, and credential redaction when changing the baseline. Checkpoint persistence currently supports inspection, not a resume/recovery workflow.

### Run Viewer and Outputs

- `viewer.html` - Canonical viewer UI with Agent Output Graph and Result Report tabs.
- `viewer_export.py` - Background publication of browser-readable run manifests, event indexes, and payloads; installs viewer assets in the output directory.
- `viewer.py` - SQLite log reader and optional local HTTP viewer server.
- `vendor/markdown-it/` - Bundled offline Markdown renderer, license, and provenance.
- `runs/index.html` - Tracked copy of the viewer; open directly in a browser without a server or folder picker.
- `runs/YYMMDD_hhmmss_<run_id>/` - Generated run directories with UTC timestamps and UUID hex identifiers; gitignored.

Each run contains events, payload artifacts, checkpoints, and, when execution reaches finalization, a summary and source index. Draft and final Markdown reports exist only when produced. The Result Report tab shows validated citation output first, then the lead draft and worker findings. Do not present unvalidated citation output as a final report or infer unrecorded reasoning from token counts.

When editing the viewer, update both `src/multi_agent_research/viewer.html` and `runs/index.html`. Preserve direct-file operation, relative local assets, role colors, and separate list/run refresh controls. Keep generated traces and credentials out of Git. Vendor dependency updates must retain license and provenance information.

### Testing (`tests/`)

- `unit/test_contracts.py` - Schemas, artifacts, citations, memory, and redaction.
- `unit/test_adapter.py` - OpenAI transport, required environment variables, and tool-call compatibility using mock HTTP.
- `unit/test_tools.py` - Mocked search and fetch behavior.
- `unit/test_viewer.py` - Run discovery, browser exports, refresh behavior, and export robustness.
- `unit/test_report_view.py` - Report selection, Markdown rendering, and tabs.
- `integration/test_pipeline.py` - Scripted end-to-end graphs, parallelism, isolation, budgets, and failure handling.

## Key Technologies

- **Python 3.11+ and uv** - Package management and execution.
- **LangGraph and asyncio** - Stateful graphs, isolated workers, and parallel batches.
- **langchain-core and langchain-openai** - Messages, tool schemas, and async model transport.
- **Pydantic and PyYAML** - Validated configuration and structured records.
- **HTTPX and Beautiful Soup** - Search requests, page retrieval, and text extraction.
- **SQLite** - Authoritative events, records, and graph checkpoints.
- **HTML/CSS/JavaScript and markdown-it** - Standalone local run visualization.
- **pytest, pytest-asyncio, and Ruff** - Automated validation. Some JavaScript viewer tests use Node.js and skip if it is unavailable; Node is not required to view runs.

## Development Commands

Run these from the `MultiAgentResearch` directory:

```bash
uv sync --locked
uv run mar --demo --config configs/baseline.yaml
uv run pytest -q
uv run ruff check src tests
uv build
```

Use the offline demo and mocked tests for routine validation; they do not consume model or search credits. Run targeted tests appropriate to changes, and use the integration suite for graph/runtime changes. No LangGraph Studio, mypy, or benchmark runner is currently configured here.

For a live research run, export the required credentials first:

```bash
uv run mar "Your research question" --config configs/baseline.yaml
```

Open `runs/index.html` directly for normal viewing. `uv run mar-view --runs-dir runs --port 8765` remains an optional server, not a prerequisite. For copied legacy logs, the one-time export helper is `multi_agent_research.viewer_export.export_existing(Path("runs"))`.

## Configuration

- Environment: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `TAVILY_API_KEY`. `.env` files are **not** automatically loaded. Never print or persist raw credentials.
- YAML: `configs/baseline.yaml`, loaded with `--config`. Without it, the CLI uses `RunConfig` defaults, which can differ from the checked-in YAML.
- CLI: `--output-dir` overrides the configured output directory. Relative paths resolve from the working directory.
- Roles: `lead`, `worker`, and `citation` each configure the exact endpoint model name, per-call output cap, allowed generation options, and optional input/output prices. Do not replace the user's model choices as part of unrelated work.
- Limits: lead/worker turns, worker tool calls, batches, concurrency, timeouts, download size, extracted text size, citation input size, and reported run tokens. The run-token limit counts input plus output and may be exceeded by in-flight parallel calls.
- Costs: estimates are unavailable unless both token rates are supplied for all roles used. They exclude search charges and cache-specific pricing and are not the provider's billed credit balance.

Consult `configs/README.md` and `config.py` for exact field definitions. Keep configuration documentation and tests aligned with behavioral changes.
