# Prompt provenance and interfaces

`upstream/manifest.json` pins Anthropic Cookbook reference snapshots and hashes.
`upstream/LICENSE` contains their license.

The active prompts are `lead.md`, `worker.md` and `judge.md`. Each run records their
hashes through `prompts.hashes()`.

| Prompt | Input | Tools / output |
| --- | --- | --- |
| Lead | Question, document catalog and returned Worker findings | `memory_write`, `memory_read`, parallel `run_blocking_subagent`, then `submit_answer` with `\boxed{answer}` |
| Worker | Self-contained assignment and document catalog | Paged `read_document`, then `complete_task` with findings, read document IDs and uncertainties |
| Judge | Question, reference answer and candidate response | JSON with boolean `correct` and string `reason` |

The Lead plans, delegates and reassesses in one context. Workers use independent
contexts. The grader calls the Judge after answer submission when exact match
requires semantic evaluation. Format validity, exact match and correctness are
separate result fields.
