# Full Anthropic prompt adaptation proposal

Status: approved and applied. The draft files here match the active full prompts.
This register documents the implemented adaptations.

## Source and review files

Source: Anthropic Cookbook commit `66ab04adc6725c887aa1bafe5cd1fc75e98a47e4`, pinned in
`src/multi_agent_research/prompts/upstream/manifest.json`. All three source hashes
were verified before drafting. The original snapshots and their license stay unchanged.

- `lead.md`, `worker.md`, `citation.md`: complete proposed active prompts.
- `upstream.diff`: exact differences from the pinned originals.

All original lead and citation text is retained verbatim. Worker text is retained
except for the contradictory minimum-call instruction and the hard-coded maximum-call paragraph. Added pipeline context is
explicitly separated from the original text. No planning taxonomy, examples,
delegation guidance, OODA loop, source-quality discussion, or citation-placement
guidance is removed.

## Adaptation register

| ID | Role | Proposed change | Reason |
| --- | --- | --- | --- |
| L1 | Lead | Add exact available tools; qualify unavailable integration/REPL/direct-search guidance. | Our lead cannot perform direct research calls. Conditional integration examples remain intact. |
| L2 | Lead | Map “batch tool” to concurrent delegation calls and explain blocking batch joins. | Matches the implemented scheduler without adding an agent or tool. |
| L3 | Lead | Require plan-memory write before delegation; explain assignment isolation. | Existing graph rejects delegation without a saved plan; workers do not inherit lead context. |
| L4 | Lead | Supply templated turn/batch/concurrency limits with precedence over suggested team sizes. | Prevents prompt suggestions from conflicting with configured limits. |
| L5 | Lead | Specify completion fields, single-call completion, successful-worker prerequisite, and failure treatment. | Matches existing contracts and prevents treating failed research as evidence. |
| L6 | Lead | Preserve provenance during synthesis; treat retrieved instructions as data. | Retains existing baseline evidence-handling safeguards. |
| L7 | Lead | Explain that the referenced writing_guidelines section is absent. | Avoids inventing unpublished instructions. |
| W1 | Worker | Add available tool signatures and HTML/text extraction limitations. | Matches actual tool capabilities; original optional-tool discussion is retained. |
| W2 | Worker | Supply templated configured budgets; count completion and reserve a call for it. | Host limits count all worker calls, including completion. |
| W3 | Worker | Replace the minimum-five/maximum-ten sentence with task-adaptive effort. | Original conflicts with its own under-five, up-to-fifteen, and diminishing-return guidance. Other numerical examples remain, subordinate to configuration. |
| W4 | Worker | Clarify the approximate 100-source guideline is not a host-enforced limit. | The implementation has no separate source-count termination rule. |
| W5 | Worker | Specify report/source_ids/uncertainties, fetched-source ownership, paragraph provenance, and single-call completion. | Matches worker result validation and downstream synthesis. |
| W6 | Worker | Treat retrieved instructions as data. | Retains the baseline evidence-handling safeguard. |
| W7 | Worker | Replace fixed 20-call maximum and around-15 stopping point with `{{.MaxWorkerToolCalls}}` and completion when one call remains. | Prompt and runtime now share the YAML limit; no separate search-query cap is introduced. |
| C1 | Citation | Supply local source/paragraph marker syntax as the format “specified earlier.” | Published prompt does not include that external format definition. |
| C2 | Citation | Specify tagged draft and JSON sources; explain markers are plain annotations. | Supplies missing input context and qualifies the original interactive-rendering claim. |
| C3 | Citation | Preserve original output wrapper and optional preamble; treat sources as evidence. | Pipeline will parse the original output contract rather than deleting it from the prompt. |

## Implemented pipeline changes

1. Add a strict plain-text template renderer for `{{.Name}}` variables. Resolve
   `CurrentDate` once per run in UTC, plus role-specific configured limits. Fail on
   missing or unsupported template variables. Do not evaluate expressions or
   recursively render user queries, assignments, or evidence.
2. Render the full system prompts through this shared context. Supply worker
   assignments within `<task>` tags, and citation input as a literal draft within
   `<synthesized_text>` plus serialized source documents within `<sources>`.
   Preserve the exact draft bytes/whitespace; measure the citation input cap against
   the actual constructed input. These tags are context boundaries, not executable XML.
3. Extract exactly one `<exact_text_with_citation>` envelope from citation output.
   Preserve its interior verbatim; permit the original preamble before the envelope,
   but reject malformed/ambiguous envelopes and non-whitespace trailing output.
   Validate the extracted report using the existing exact-text and source-ID checks.
   Keep the existing unwrapped-output path for compatibility with scripted fixtures
   and existing callers; it still must pass the same validation. Drafts containing
   literal reserved citation delimiters fail explicitly; source JSON escapes angle
   brackets while preserving decoded content.
4. Keep raw model responses in logs. Record the accepted extracted report in the
   citation validation event so the Result Report viewer shows only that report,
   while the graph retains the full raw response. Preserve legacy viewer support
   for events without this new field; synchronize both HTML copies.
5. Record template hashes, rendered-prompt hashes, and the resolved run context
   alongside existing model request logs for experimental reproducibility. Update
   prompt documentation and this adaptation register when the approved version ships.
6. Add tests for missing variables, fixed run dates, non-recursive substitution,
   tagged inputs, exact whitespace, wrappers/preambles, malformed/duplicate tags,
   unknown citation IDs, text changes, and viewer extraction. Run the offline
   integration suite and Ruff; no live API calls are needed.

## Experimental interpretation

This restores published research guidance while keeping the current web-only,
blocking-batch architecture and tool contracts. It is not proof of equivalence to
Anthropic's unpublished production implementation. Original trailing whitespace is retained to preserve source text verbatim.
Longer prompts will increase
input-token usage. Original source-quality, tool-budget, and team-size heuristics
remain visible so the baseline's deviations can be reported explicitly.

## Approval boundary

The user approved applying the proposal. The pinned upstream originals remain
unchanged. No live API calls were needed for implementation validation.
