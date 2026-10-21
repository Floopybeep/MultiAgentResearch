"""Atomic, browser-loadable derivatives of the authoritative SQLite/artifact logs."""

import json
import os
import sqlite3
import tempfile
import warnings
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".viewer-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_data(root, relative, data):
    # Double serialization keeps all log content inside a string, including __proto__.
    # HTML delimiters and line separators are escaped, never executable log content.
    encoded = json.dumps(json.dumps(data, ensure_ascii=True), ensure_ascii=True)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    atomic_write(
        root / relative,
        f"window.__MAR_DATA__[{json.dumps(relative)}] = JSON.parse({encoded});\n",
    )


def install_html(root):
    vendor = files("multi_agent_research").joinpath("vendor", "markdown-it")
    for name in ("markdown-it.min.js", "LICENSE"):
        destination = root / "viewer-assets" / name
        content = vendor.joinpath(name).read_text()
        if not destination.exists() or destination.read_text() != content:
            atomic_write(destination, content)
    html = files("multi_agent_research").joinpath("viewer.html").read_text()
    path = root / "index.html"
    if not path.exists() or path.read_text() != html:
        atomic_write(path, html)


def publish_manifest(root, summary):
    # Serialize manifest publication across concurrent research processes. A reader
    # always sees a complete old/new JS file; one run cannot overwrite another.
    with sqlite3.connect(root / ".viewer-index.sqlite", timeout=10) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS runs (name TEXT PRIMARY KEY, body TEXT)")
        connection.execute("BEGIN IMMEDIATE")
        if summary is not None:
            connection.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?)",
                (summary["directory"], json.dumps(summary)),
            )
        runs = []
        for name, body in connection.execute("SELECT name, body FROM runs").fetchall():
            if (root / name / "events.sqlite").is_file():
                runs.append(json.loads(body))
            else:
                connection.execute("DELETE FROM runs WHERE name=?", (name,))
        runs.sort(key=lambda r: r.get("started_at") or r["directory"], reverse=True)
        write_data(root, "viewer-manifest.js", runs)


def publish_snapshot(root, data):
    """Used by migration; publish payloads before the index that references them."""
    name = data["directory"]
    events = []
    for event in data["events"]:
        metadata = {k: v for k, v in event.items() if k != "payload"}
        write_data(
            root, f"{name}/viewer-payloads/{event['payload_ref']}.js", event["payload"]
        )
        events.append(metadata)
    trace = {**data, "events": events}
    write_data(root, f"{name}/viewer-data.js", trace)
    publish_manifest(root, {k: v for k, v in trace.items() if k not in ("events", "config")})


class ViewerExport:
    """Write each payload once and update only the small trace index per event."""

    def __init__(self, run_path, config):
        self.root = run_path.parent
        self.name = run_path.name
        self.data = {
            "directory": self.name, "query": "", "started_at": None, "updated_at": None,
            "status": "unfinished", "stop_reason": None, "config": config, "warnings": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "model_calls": 0},
            "events": [],
        }
        self.pending_payloads = {}
        self.warned = False
        install_html(self.root)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="viewer-export")

    def observe(self, event, payload):
        # Keep derived-file I/O off the agent event loop. This queue preserves order.
        self.executor.submit(self._observe, event, payload)

    def wait(self):
        """Wait until all already-queued events have been exported."""
        self.executor.submit(lambda: None).result()

    def close(self):
        self.executor.shutdown(wait=True)

    def _observe(self, event, payload):
        # Called only after the redacted authoritative event has been committed.
        self.data["events"].append(event)
        self.pending_payloads[event["payload_ref"]] = payload
        kind = event["event_type"]
        self.data["updated_at"] = event["timestamp"]
        if kind == "run.started":
            self.data.update(query=payload.get("query", ""), started_at=event["timestamp"])
        elif kind == "model.response":
            usage = payload.get("usage_metadata") or {}
            self.data["usage"]["model_calls"] += 1
            for key in ("input_tokens", "output_tokens"):
                self.data["usage"][key] += usage.get(key, 0)
        elif kind == "run.finished":
            for key in ("status", "stop_reason", "usage"):
                if key in payload:
                    self.data[key] = payload[key]
        self.flush()

    def flush(self):
        try:
            for ref, payload in self.pending_payloads.items():
                write_data(self.root, f"{self.name}/viewer-payloads/{ref}.js", payload)
            self.pending_payloads.clear()
            write_data(self.root, f"{self.name}/viewer-data.js", self.data)
            publish_manifest(self.root, {
                k: v for k, v in self.data.items() if k not in ("events", "config")
            })
            self.warned = False
        except (OSError, sqlite3.Error):
            # The optional viewer must not turn a successful model call into a failure.
            if not self.warned:
                warnings.warn(
                    "Browser export could not be updated; SQLite/artifact logs remain authoritative.",
                    RuntimeWarning, stacklevel=2,
                )
                self.warned = True


def export_existing(root):
    from .viewer import RUN_NAME, read_run

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    install_html(root)
    exported, errors = [], {}
    for path in sorted(root.iterdir()):
        if RUN_NAME.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
            try:
                publish_snapshot(root, read_run(root, path.name))
                exported.append(path.name)
            except (OSError, ValueError, sqlite3.Error) as exc:
                errors[path.name] = str(exc)
    publish_manifest(root, None)
    return {"exported": exported, "errors": errors}
