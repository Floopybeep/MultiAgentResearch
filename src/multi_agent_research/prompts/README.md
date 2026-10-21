# Prompt provenance and adaptations

`upstream/manifest.json` pins the Anthropic Cookbook prompt snapshots and their SHA-256
hashes. Their original license is retained in `upstream/LICENSE`. They are reference
material, not executed as-is. The active `lead.md`, `worker.md`, and `citation.md` are
shortened adaptations; every run records their hashes.

Adaptations: web-only tools; explicit plan-memory tools; one reusable worker; no user
clarification; host-enforced budgets; structured completion envelopes; citation markers
with source/paragraph IDs and exact-text validation. Removed internal Workspace tools,
obsolete tool references, inconsistent budget guidance, and unavailable formatting
instructions. Source-content instructions are explicitly untrusted. The citation
model receives all fetched evidence within a configured character cap; exceeding it
fails visibly instead of silently truncating evidence. These choices are not claims
about Anthropic's private production implementation.
