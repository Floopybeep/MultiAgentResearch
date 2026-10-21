"""Read-only, loopback-only run viewer. SQLite is read in one snapshot per refresh."""

import argparse
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .viewer_export import export_existing

RUN_NAME = re.compile(r"(?:\d{6}_\d{6}_)?[a-f0-9]{32}")


def run_path(root, name):
    if not RUN_NAME.fullmatch(name):
        raise ValueError("Invalid run directory")
    path = root / name
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Run does not exist")
    return path


def read_run(root, name, include_events=True):
    path = run_path(root, name)
    db_path = path / "events.sqlite"
    if db_path.is_symlink():
        raise ValueError("Symlinked databases are not supported")
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("BEGIN")
        events = [
            json.loads(row[0])
            for row in connection.execute("SELECT body FROM events ORDER BY sequence")
        ]
        records = {
            key: json.loads(body)
            for key, body in connection.execute(
                "SELECT key, body FROM records WHERE key IN ('run', 'config')"
            )
        }
    finally:
        connection.close()
    warnings = []
    for event in events:
        if not include_events and event["event_type"] not in {
            "run.started", "run.finished", "model.response",
        }:
            continue
        # Never follow arbitrary references from a log outside its artifacts directory.
        ref = event.get("payload_ref", "")
        artifact = path / "artifacts" / f"{ref}.json"
        try:
            if not re.fullmatch(r"[a-f0-9]{64}", ref) or not artifact.resolve().is_relative_to(
                path.resolve()
            ):
                raise ValueError("Invalid artifact path")
            event["payload"] = json.loads(artifact.read_text())
        except (OSError, ValueError) as exc:
            event["payload"] = {"unavailable": str(exc)}
            warnings.append(f"Missing or unreadable payload for {event['event_id']}")
    started = next((e for e in events if e["event_type"] == "run.started"), {})
    finished = records.get("run")
    if not finished:
        finished = next(
            (e["payload"] for e in reversed(events) if e["event_type"] == "run.finished"), {}
        )
    usage = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
    for event in events:
        if event["event_type"] == "model.response":
            metadata = event["payload"].get("usage_metadata") or {}
            usage["model_calls"] += 1
            for key in ("input_tokens", "output_tokens"):
                usage[key] += metadata.get(key, 0)
    result = {
        "directory": name,
        "query": started.get("payload", {}).get("query", ""),
        "started_at": started.get("timestamp"),
        "updated_at": events[-1]["timestamp"] if events else None,
        # Absence of a finish event cannot distinguish a running job from an interruption.
        "status": finished.get("status", "unfinished"),
        "stop_reason": finished.get("stop_reason"),
        "usage": finished.get("usage", usage),
        "config": records.get("config", {}),
        "warnings": warnings,
    }
    if include_events:
        result["events"] = events
    return result


def list_runs(root):
    runs = []
    for path in root.iterdir():
        if RUN_NAME.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
            try:
                runs.append(read_run(root, path.name, include_events=False))
            except (OSError, ValueError, sqlite3.Error) as exc:
                runs.append({"directory": path.name, "status": "unreadable", "error": str(exc)})
    return sorted(runs, key=lambda r: r.get("started_at") or r["directory"], reverse=True)


def make_handler(root):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            try:
                if parsed.path in ("/", "/index.html"):
                    self.respond(200, (root / "index.html").read_bytes(), "text/html")
                elif parsed.path == "/viewer-assets/markdown-it.min.js":
                    self.respond(200, (root / "viewer-assets" / "markdown-it.min.js").read_bytes(),
                                 "text/javascript")
                elif parsed.path == "/viewer-manifest.js" or re.fullmatch(
                    r"/(?:\d{6}_\d{6}_)?[a-f0-9]{32}/(?:viewer-data\.js|"
                    r"viewer-payloads/[a-f0-9]{64}\.js)", parsed.path
                ):
                    target = root / parsed.path.lstrip("/")
                    if not target.resolve().is_relative_to(root.resolve()):
                        raise ValueError("Invalid export path")
                    self.respond(200, target.read_bytes(), "text/javascript")
                elif parsed.path == "/api/runs":
                    self.respond_json(list_runs(root))
                elif parsed.path == "/api/run":
                    name = parse_qs(parsed.query).get("name", [""])[0]
                    self.respond_json(read_run(root, name))
                else:
                    self.respond(404, b"Not found", "text/plain")
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.respond(400, json.dumps({"error": str(exc)}).encode(), "application/json")

        def respond_json(self, value):
            self.respond(200, json.dumps(value).encode(), "application/json")

        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = args.runs_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Ship the UI with the package and install it in the requested runs directory.
    (root / "index.html").write_text(
        files("multi_agent_research").joinpath("viewer.html").read_text()
    )
    export_existing(root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(root))
    print(f"Run viewer: http://127.0.0.1:{server.server_port} (directory: {root})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
