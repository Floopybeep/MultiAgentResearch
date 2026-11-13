"""Viewer, prompt and config files are UTF-8 regardless of the platform default encoding."""

import os
import subprocess
import sys
from importlib.resources import files

# Run outside UTF-8 mode, and turn every implicit-encoding text read or write into an
# error, so this fails on any platform rather than only under a Windows code page.
SCRIPT = r"""
import json, sys
from pathlib import Path
import multi_agent_research.viewer as viewer
from multi_agent_research import prompts
from multi_agent_research.config import RunConfig
from multi_agent_research.observability.events import EventLogger
from multi_agent_research.storage.artifacts import ArtifactStore
from multi_agent_research.storage.database import Database
from multi_agent_research.viewer_export import group_summary, install_html

root = Path(sys.argv[1])
TEXT = "café ”quoted” 中文"

install_html(root)
install_html(root)  # Compare-before-write reads the installed copies back.

class Server:
    server_port = 0
    def __init__(self, *args): pass
    def serve_forever(self): raise KeyboardInterrupt
    def server_close(self): pass

viewer.ThreadingHTTPServer = Server
sys.argv = ["mar-view", "--runs-dir", str(root), "--port", "0"]
viewer.main()

name = "a" * 32
path = root / name
path.mkdir()
database = Database(path / "events.sqlite")
EventLogger(database, ArtifactStore(path / "artifacts"), "run").emit(
    "run.started", "lead", {"query": TEXT}, ()
)
database.close()
assert viewer.read_run(root, name)["events"][0]["payload"]["query"] == TEXT

batch = root / "batch"
batch.mkdir()
(batch / "batch.json").write_text(
    json.dumps({"questions": [{"question_id": 1, "query": TEXT}], "results": [],
                "status": "running", "config": {}}, ensure_ascii=False),
    encoding="utf-8",
)
assert group_summary(batch, [])["questions"][0]["query"] == TEXT

assert "user’s" in prompts.load("lead")
config = root / "config.yaml"
config.write_text("document_injection:\n  prompt: " + TEXT + "\n", encoding="utf-8")
assert RunConfig.load(config).document_injection.prompt == TEXT
"""


def test_text_files_are_utf8_outside_utf8_mode(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning",
         "-c", SCRIPT, str(tmp_path)],
        env={**os.environ, "PYTHONUTF8": "0"}, capture_output=True, text=True, encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr

    package = files("multi_agent_research")
    assert (tmp_path / "index.html").read_bytes() == package.joinpath("viewer.html").read_bytes()
    vendor = package.joinpath("vendor", "markdown-it", "markdown-it.min.js")
    assert (tmp_path / "viewer-assets" / "markdown-it.min.js").read_bytes() == vendor.read_bytes()
