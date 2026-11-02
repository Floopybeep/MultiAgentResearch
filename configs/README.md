# QA configuration

`mar --config configs/baseline.yaml` loads a validated `RunConfig`. Without the
flag, Python defaults apply. Relative paths resolve from the working directory;
`--output-dir` overrides the configured result directory.

## Models

`lead`, `worker`, and `judge` each accept:

| Field | Python default | Meaning |
| --- | --- | --- |
| `model` | `glm-5.3-flash` | Exact model name served by the endpoint |
| `max_output_tokens` | 4096 (judge: 1024) | Per-call output cap |
| `options` | `{}` | Chat Completions generation options |
| `input_cost_per_million` | unset | USD per million non-cached input tokens |
| `cached_input_cost_per_million` | unset | USD per million cached input tokens |
| `output_cost_per_million` | unset | USD per million output tokens |

Allowed generation options: `temperature`, `top_p`, `seed`, `stop`,
`presence_penalty`, `frequency_penalty`, `reasoning_effort`, `logprobs`,
`top_logprobs`. `RunConfig` validates field names and positive resource limits.

The adapter reads `OPENAI_API_KEY` and `OPENAI_BASE_URL` from the shell environment.
It uses async Chat Completions with `use_responses_api=False` and `max_retries=0`.

## Usage and cost fields

Input tokens include cached input. Given the endpoint's returned usage:

```text
estimated_cost_usd = ((input - cached) * input_rate
                      + cached * cache_rate + output * output_rate) / 1e6
```

`cached` comes from LangChain's `input_token_details.cache_read`. Missing cache
details use the ordinary input rate for that response and set aggregate
`cached_input_tokens` to `null`. Missing usage or required prices set
`estimated_cost_usd` to `null`. A role with zero calls has zero usage and cost.

## Per-question resource limits

| Field | Default | Semantics |
| --- | --- | --- |
| `max_lead_turns` | 20 | Model calls in the planning/reassessment loop |
| `max_worker_turns` | 12 | Model calls per Worker |
| `max_worker_tool_calls` | 20 | Tool calls per Worker, including completion |
| `max_batches` | 6 | Delegation rounds per question |
| `max_workers_per_batch` | 4 | Parallel Workers; excess assignments return errors |
| `max_run_tokens` | 200000 | Reported input + output, all roles including judge |
| `run_timeout_seconds` | 900 | Lead/Worker graph timeout, excluding grading |
| `worker_timeout_seconds` | 180 | Individual Worker graph timeout |
| `call_timeout_seconds` | 60 | Individual model/local tool call timeout |
| `max_document_chars` | 24000 | Characters per reader page; continue at `next_offset` |
| `output_dir` | `runs` | Per-question outputs and batch manifests |

The token limit is checked before model calls against accumulated returned usage.
In-flight parallel calls can exceed the limit. A failed judge call records
`method: judge_error` and `correct: null`.

## CLI settings

| Flag | Default | Meaning |
| --- | --- | --- |
| `--config` | unset | YAML configuration path |
| `--output-dir` | configured value | Override result directory |
| `--corpus-dir` | `corpus` | Directory with `frames.tsv`, `index.json` and articles |
| `--sample-size` | 10 | Number of sampled questions |
| `--seed` | 42 | Local question-sampling seed |
| `--question-ids` | unset | Explicit unique TSV row IDs, overriding sampling |

The dataset contains 822 questions with original IDs. `index.json` maps questions
to document IDs and documents to titles, URLs and Markdown filenames. Each
question's catalog and snapshots contain its indexed articles. Missing files
produce a `preparation_failed` result in the batch manifest.

```bash
uv run mar --config configs/baseline.yaml --sample-size 10 --seed 42
```
