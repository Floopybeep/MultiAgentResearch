# Recorded run examples

Open [`runs/index.html`](runs/index.html) **locally after cloning or downloading
this repository**. No server, Python environment, API credentials or corpus
installation is needed. GitHub's file preview does not execute the HTML viewer.
Keep the entire `examples/runs/` directory together: the HTML loads its relative
manifest, payload scripts and bundled Markdown renderer.

## Included runs

These examples have selected runs starting on **2026-11-04 at or after 01:23 AM
PST (09:23 UTC)**: 13 physical runs, displayed as seven experiments after grouping
six Full Restart pairs. The linked 01:21 AM first attempt of the 01:23 AM Full
Restart run is retained so both attempts remain inspectable. The earlier 01:06 AM
and 01:16 AM baseline examples are excluded.
Use the Agent Output Graph and QA Results tabs exactly as in the local viewer.

| Started (PST) | Strategy | Configured fault | Recorded correct | Total seconds | Selected run directory |
| --- | --- | --- | --- | ---: | --- |
| 01:21:35 | full-restart | document text | yes | 224.6 | `261104_092304_ac7c85c53fc14b5da3f0bf389bbd13e2` |
| 01:26:29 | always-verify | document text | no | 184.5 | `261104_092629_97ddb3b2dbb6427ab964d37424691ea5` |
| 03:10:51 | full-restart | tool failure (immediate) | yes | 144.6 | `261104_111201_577fe363087e4f7897af37f8f2ad80cc` |
| 03:28:13 | full-restart | connection drop (keep 0) | yes | 148.2 | `261104_112841_cd96223e95124b39b3f6c94f7e109c45` |
| 03:33:04 | full-restart | connection drop (keep 1) | yes | 119.0 | `261104_113356_a4401978a35445938d4a6fe4e2eef63a` |
| 03:40:27 | full-restart | result timeout (keep 1) | yes | 149.7 | `261104_114112_12e58925dd3142a5aac4e952179ca6e5` |
| 03:51:36 | full-restart | tool failure (timeout) | yes | 237.5 | `261104_115434_4f0258ada4804eb5919d94167ba2e55a` |

## What these examples demonstrate

- One-article Worker assignments and ordinary Lead reassessment/re-delegation.
- Document poisoning under Full Restart and Always-Verify.
- Full Restart after document-tool failures, connection drops and withheld results.
- A single logical experiment with separate attempt flows and combined accounting.

These are **historical debugging and interface examples, not a controlled or
statistical comparison of strategy effectiveness**. They use the same question
but differ in code version, timeout settings, fault location and configuration.
The recorded Always-Verify run predates the independent verifier model setting;
its original settings and diagnostics are retained. They are not fresh runtime
acceptance results for the final commit series. A missing cost/usage value means
unreported information, not a free call.

## Snapshot contents

The per-run browser indexes and referenced payload scripts are copied unchanged
from existing local exports. The manifest is filtered to these runs, and the
current canonical viewer and its licensed Markdown renderer are included.
Recorded model/tool inputs, outputs and configuration remain visible; no model
calls were rerun to produce this archive. Source article titles and URLs remain
in the traces for attribution.

Raw SQLite databases, checkpoints, original artifact directories and credentials
are not included. The authoritative local traces remain untouched. This is a
read-only browser snapshot: refresh reloads the bundled data, not new experiments.
