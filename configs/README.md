# Baseline configuration

Run with `uv run mar "Research question" --config configs/baseline.yaml`.
YAML fields are validated; unknown fields are rejected. Paths are relative to the
working directory, not the YAML file. Omitted fields use the defaults below.
The checked-in YAML may override these defaults.

## Agent models

`lead`, `worker`, and `citation` each accept the same settings. The lead plans,
delegates, and writes; every worker uses the worker settings; citation annotates the draft.

| Parameter | Default | Meaning |
|---|---|---|
| `model` | `gpt-6-luna` | Exact model name served by your OpenAI-compatible endpoint. No provider prefix is added or removed. |
| `max_output_tokens` | 4096; citation: 8192 | Positive per-call output token cap. The SDK may transmit it as `max_completion_tokens`; model-specific reasoning tokens may count against it. |
| `options` | `{}` | Supported generation options below. Endpoint/model support is required. |
| `input_cost_per_million` | `null` | Optional nonnegative USD rate per million input tokens for local estimates. |
| `output_cost_per_million` | `null` | Optional nonnegative USD rate per million output tokens for local estimates. |

Allowed `options`:

| Option | Meaning |
|---|---|
| `temperature` | Sampling randomness. |
| `top_p` | Nucleus-sampling probability cutoff. |
| `seed` | Provider-supported sampling seed; does not guarantee reproducibility. |
| `stop` | Stop sequence or sequences. |
| `presence_penalty` | Penalize tokens that have already appeared. |
| `frequency_penalty` | Penalize tokens according to their frequency. |
| `reasoning_effort` | Model-supported reasoning effort level. Does not guarantee reasoning text is returned. |
| `logprobs` | Request output-token log probabilities. |
| `top_logprobs` | Number of alternative token log probabilities to return, when enabled. |

Transport overrides, credentials, and Responses API options are rejected.
Export `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `TAVILY_API_KEY` in your shell.
The program does not automatically load `.env`. Model inference always uses async
OpenAI Chat Completions with SDK retries disabled.

Cost estimates require both rates for every role that makes a call. They exclude
search charges and do not account separately for cache pricing; they are not an
authoritative provider bill or credit balance.

## Execution and resource limits

All numeric limits must be positive. `search_results` must be between 1 and 20.

| Parameter | Default | Meaning |
|---|---:|---|
| `max_lead_turns` | 20 | Maximum lead model calls across the run, including planning and synthesis. |
| `max_worker_turns` | 12 | Maximum model calls per worker assignment. |
| `max_worker_tool_calls` | 20 | Maximum executed tools per worker, including failed calls and `complete_task`. Exhaustion currently returns a budget failure without findings; no final-summary turn is reserved. |
| `max_batches` | 6 | Maximum rounds of worker delegation. After exhaustion the lead receives a tool error and should synthesize existing results. |
| `max_workers_per_batch` | 4 | Maximum parallel workers in a batch. Excess assignments return errors rather than queueing. |
| `max_run_tokens` | 200000 | Global reported input + output usage threshold checked before model calls. Includes repeated context and cached input. In-flight/concurrent calls can exceed it. |
| `run_timeout_seconds` | 900 | Overall graph execution timeout. |
| `worker_timeout_seconds` | 180 | Timeout for each complete worker assignment. |
| `call_timeout_seconds` | 60 | Timeout for an individual model or tool operation. Delegation uses the worker timeout instead. |
| `max_document_chars` | 24000 | Extracted text characters retained per fetched document, before paragraph splitting. Longer text is truncated and flagged. |
| `max_citation_chars` | 160000 | Character limit for the serialized draft + all source records sent to citation. Exceeding it stops the run; there is no automatic chunking. |
| `max_download_bytes` | 2000000 | Maximum decoded response-body bytes per fetched page, before HTML extraction. Larger downloads fail instead of truncating. |
| `search_results` | 5 | Maximum search results requested per Tavily call. |
| `output_dir` | `runs` | Parent directory for run artifacts. `--output-dir` overrides it. |

New run folders use `YYMMDD_hhmmss_<run_id>`, where the timestamp is UTC and
`run_id` is the existing 32-character random UUID hex identifier. Existing run
folders are not renamed. Checkpoint and event IDs continue to use the original run ID.

Open `<output_dir>/index.html` directly in a browser. Each logged event automatically
updates the browser exports; neither `mar-view` nor directory selection is required.
The two refresh buttons reload the run manifest and selected trace respectively.
SQLite remains authoritative. See the main README for export details and legacy-log migration.
