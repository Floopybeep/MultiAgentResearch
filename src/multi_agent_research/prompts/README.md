# Prompt provenance and adaptations

Active lead, worker, and citation prompts preserve the full pinned Anthropic
Cookbook guidance with explicit pipeline context. Lead and citation source text
is unchanged; the contradictory worker minimum-call sentence and hard-coded maximum-call
paragraph are adapted. The latter uses `{{.MaxWorkerToolCalls}}` from YAML.

See [the adaptation register](../../../docs/prompt-review/README.md) for each
change and [the exact upstream diff](../../../docs/prompt-review/upstream.diff).
`upstream/manifest.json` pins source hashes and the original license is retained.
Upstream snapshots are never modified.

`{{.CurrentDate}}` and role-budget variables are strictly rendered from a context
fixed at run initialization (UTC date). Unknown variables/expressions fail;
assignments, queries, and evidence are not rendered as templates. Run records
include template hashes, rendered hashes, and context; model requests preserve
the actual messages.

Workers receive `<task>` context. Citations receive `<synthesized_text>` and JSON
`<sources>`, and can return `<exact_text_with_citation>` with an optional preamble.
Only the exact envelope interior is validated and published; raw output remains
in model logs. Bare reports remain supported with identical validation. Ambiguous
or malformed envelopes, trailing prose, text changes, and unknown references fail.
Reserved citation delimiters in drafts fail explicitly. Evidence JSON escapes
angle brackets without changing decoded evidence. The viewer uses the validated
report, with legacy response fallback for older logs.

These adaptations reproduce public guidance within our web-only tool contracts,
not Anthropic's unpublished production implementation. Citation validation checks
text preservation and reference existence, not factual support.
