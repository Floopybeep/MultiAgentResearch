"""Atomic, browser-loadable derivatives of the authoritative SQLite/artifact logs."""

import json
import os
import sqlite3
import tempfile
import warnings
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from statistics import mean, median

from .observability.usage import sum_usage


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
        content = vendor.joinpath(name).read_text(encoding="utf-8")
        if not destination.exists() or destination.read_text(encoding="utf-8") != content:
            atomic_write(destination, content)
    html = files("multi_agent_research").joinpath("viewer.html").read_text(encoding="utf-8")
    path = root / "index.html"
    if not path.exists() or path.read_text(encoding="utf-8") != html:
        atomic_write(path, html)


def intervention_summary(results):
    """Break out verifier work and extra full-restart attempts without double counting."""
    executed = [r for r in results if r.get("status") != "preparation_failed"]
    attempts = [a for r in executed for a in r.get("attempts", [r])]
    verifier_known = all("verifications" in a for a in attempts)
    checks = [v for a in attempts for v in a.get("verifications", [])]
    verifier_usages = [(r.get("usage_by_role") or r.get("usage", {}).get("by_role", {}))
                       .get("verifier") for r in executed]
    verifier_usage = (sum_usage(verifier_usages)
                      if all(u is not None for u in verifier_usages) else {})
    retry_known = all("attempts" in r for r in executed)
    retries = [a for r in executed for a in r.get("attempts", [])[1:]]
    retried = [r for r in executed if len(r.get("attempts", [])) > 1]
    retry_usage = (sum_usage(a.get("usage", {}) for a in retries) if retry_known else {})
    durations = [a.get("elapsed_seconds", a.get("duration_seconds")) for a in retries]
    return {
        "verifier_statistics": {
            **verifier_usage,
            "checks": len(checks) if verifier_known else None,
            "passed": sum(v.get("verified") is True for v in checks) if verifier_known else None,
            "failed": sum(v.get("verified") is False for v in checks) if verifier_known else None,
            "unresolved": sum(v.get("verified") is None for v in checks)
                          if verifier_known else None,
            "elapsed_seconds": sum(v["duration_seconds"] for v in checks)
                if verifier_known and all(v.get("duration_seconds") is not None for v in checks)
                else None,
        },
        "retry_statistics": {
            **retry_usage,
            "questions": len(retried) if retry_known else None,
            "attempts": len(retries) if retry_known else None,
            "correct": sum(r.get("correct") is True for r in retried) if retry_known else None,
            "incorrect": sum(r.get("correct") is False for r in retried) if retry_known else None,
            "ungraded": sum(r.get("correct") is None for r in retried) if retry_known else None,
            "elapsed_seconds": sum(durations)
                if retry_known and all(d is not None for d in durations) else None,
        },
    }


def group_summary(path, traces):
    """Combine the saved selection with the latest per-attempt trace summaries."""
    manifest = json.loads((path / "batch.json").read_text(encoding="utf-8"))
    results = {str(r["question_id"]): r for r in manifest["results"]}
    questions = []
    for question in manifest["questions"]:
        question_id = str(question["question_id"])
        prefix = f"{path.name}/questions/{question_id}/"
        attempts = sorted((t for t in traces if t["directory"].startswith(prefix)),
                          key=lambda t: t["directory"])
        result = results.get(question_id, {})
        trace = attempts[-1] if attempts else {}
        questions.append({
            **question, "directory": trace.get("directory"),
            "status": result.get("status", trace.get("status", "pending")),
            "correct": result.get("correct", trace.get("correct")),
            "error": result.get("error"),
        })
    durations = [r.get("elapsed_seconds", r.get("duration_seconds"))
                 for r in manifest["results"]]
    durations = [value for value in durations if isinstance(value, (int, float))]
    summary = {
        **manifest.get("summary", {}),
        **intervention_summary(manifest["results"]),
        "timed_questions": len(durations),
        "average_duration_seconds": mean(durations) if durations else None,
        "median_duration_seconds": median(durations) if durations else None,
        "min_duration_seconds": min(durations) if durations else None,
        "max_duration_seconds": max(durations) if durations else None,
        "wall_duration_seconds": manifest.get("duration_seconds"),
        "preparation_failed": sum(r.get("status") == "preparation_failed"
                                  for r in manifest["results"]),
    }
    return {
        "directory": path.name, "started_at": manifest.get("started_at"),
        "status": manifest["status"], "query": f"{len(questions)} questions",
        "questions": questions, "config": manifest["config"],
        "summary": summary,
    }


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
        groups = []
        for path in sorted(root.glob("*/batch.json")):
            group = group_summary(path.parent, runs)
            write_data(root, f"{path.parent.name}/viewer-data.js", group)
            groups.append(group)
        runs = [r for r in runs if "/" not in r["directory"]] + groups
        runs.sort(key=lambda r: r.get("started_at") or r["directory"], reverse=True)
        write_data(root, "viewer-manifest.js", runs)


def _attempt_metadata(result, directory, run_directories=None):
    metadata = {
        key: result[key]
        for key in ("strategy", "selected_attempt", "restarted")
        if key in result
    }
    metadata.update(intervention_summary([result]))
    metadata["attempts"] = []
    for attempt in result.get("attempts", []):
        if not attempt.get("output_dir"):
            continue
        usage = attempt.get("usage", {})
        metadata["attempts"].append({
            **{key: attempt.get(key) for key in (
                "attempt_number", "run_id", "status", "faults_enabled", "fault_injected",
                "elapsed_seconds",
            )},
            "directory": (run_directories or {}).get(attempt.get("run_id"),
                directory if attempt.get("run_id") == result.get("run_id") else
                (Path(directory).parent / Path(attempt["output_dir"]).name).as_posix()),
            "model_calls": usage.get("model_calls"),
            "total_tokens": usage.get("total_tokens"),
            "estimated_cost_usd": usage.get("estimated_cost_usd"),
        })
    return metadata


def publish_snapshot(root, data, run_directories=None):
    """Used by migration; publish payloads before the index that references them."""
    name = data["directory"]
    events = []
    attempts = {}
    for event in data["events"]:
        if event["event_type"] == "run.finished":
            attempts.update(_attempt_metadata(event["payload"], name, run_directories))
        metadata = {k: v for k, v in event.items() if k != "payload"}
        write_data(
            root, f"{name}/viewer-payloads/{event['payload_ref']}.js", event["payload"]
        )
        events.append(metadata)
    trace = {**data, **attempts, "events": events}
    write_data(root, f"{name}/viewer-data.js", trace)
    publish_manifest(root, {k: v for k, v in trace.items() if k not in ("events", "config")})


class ViewerExport:
    """Write each payload once and update only the small trace index per event."""

    def __init__(self, run_path, config, viewer_root=None):
        self.root = viewer_root if viewer_root is not None else run_path.parent
        self.name = run_path.relative_to(self.root).as_posix()
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
            self.data.update(_attempt_metadata(payload, self.name))
            for key in ("status", "stop_reason", "usage", "correct"):
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
    snapshots = []
    for database in sorted(root.rglob("events.sqlite")):
        path = database.parent
        name = path.relative_to(root).as_posix()
        if RUN_NAME.fullmatch(name) and not path.is_symlink():
            try:
                snapshots.append(read_run(root, name, include_events=False))
            except (OSError, ValueError, sqlite3.Error) as exc:
                errors[name] = str(exc)
    run_directories = {s["run_id"]: s["directory"] for s in snapshots if s.get("run_id")}
    for snapshot in snapshots:
        name = snapshot["directory"]
        try:
            publish_snapshot(root, read_run(root, name), run_directories)
            exported.append(name)
        except (OSError, ValueError, sqlite3.Error) as exc:
            errors[name] = str(exc)
    publish_manifest(root, None)
    return {"exported": exported, "errors": errors}
