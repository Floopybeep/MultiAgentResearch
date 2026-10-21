import re
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from importlib.resources import files

import httpx
import pytest

from multi_agent_research.config import RunConfig
from multi_agent_research.demo import DemoFetcher, DemoModel, DemoSearch
from multi_agent_research.runner import run_research
from multi_agent_research.runtime import Runtime
from multi_agent_research.viewer import list_runs, make_handler, read_run


def test_timestamped_directory_and_live_snapshot(tmp_path):
    before = datetime.now(timezone.utc).strftime("%y%m%d_%H%M%S")
    runtime = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    try:
        assert re.fullmatch(r"\d{6}_\d{6}_[a-f0-9]{32}", runtime.root.name)
        assert runtime.root.name.endswith("_" + runtime.run_id)
        after = datetime.now(timezone.utc).strftime("%y%m%d_%H%M%S")
        assert before <= runtime.root.name[:13] <= after
        runtime.event("run.started", "lead", {"query": "test"})
        first = read_run(tmp_path, runtime.root.name)
        assert first["status"] == "unfinished"
        assert len(first["events"]) == 1
        runtime.event("model.response", "lead", {
            "content": "output",
            "usage_metadata": {"input_tokens": 10, "output_tokens": 5},
        })
        refreshed = read_run(tmp_path, runtime.root.name)
        assert len(refreshed["events"]) == 2
        assert refreshed["usage"]["output_tokens"] == 5
        assert list_runs(tmp_path)[0]["directory"] == runtime.root.name
        # Reader did not write final artifacts or change recorded events.
        assert not (runtime.root / "run.json").exists()
    finally:
        runtime.close()


async def test_completed_demo_and_legacy_runs(tmp_path):
    result = await run_research(
        "Research alpha.", RunConfig(output_dir=tmp_path),
        DemoModel(), DemoSearch(), DemoFetcher(),
    )
    name = result["output_dir"].split("/")[-1]
    run = read_run(tmp_path, name)
    assert run["status"] == "completed"
    assert run["usage"] == result["usage"]
    assert any(e["event_type"] == "citation.validated" for e in run["events"])
    legacy = tmp_path / result["run_id"]
    (tmp_path / name).rename(legacy)
    assert read_run(tmp_path, legacy.name)["status"] == "completed"
    assert len(list_runs(tmp_path)) == 1


def test_unavailable_payload_and_path_rejection(tmp_path):
    runtime = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    try:
        runtime.event("run.started", "lead", {"query": "test"})
        runtime.viewer_export.wait()
        artifact = next(runtime.artifacts.root.iterdir())
        artifact.unlink()
        run = read_run(tmp_path, runtime.root.name)
        assert run["warnings"]
        assert "unavailable" in run["events"][0]["payload"]
        for name in ("../outside", "/etc/passwd", "index.html"):
            with pytest.raises(ValueError):
                read_run(tmp_path, name)
        link = tmp_path / ("a" * 32)
        link.symlink_to(runtime.root, target_is_directory=True)
        with pytest.raises(ValueError):
            read_run(tmp_path, link.name)
    finally:
        runtime.close()


def test_http_refresh_and_no_arbitrary_file_serving(tmp_path):
    html = files("multi_agent_research").joinpath("viewer.html").read_text()
    (tmp_path / "index.html").write_text(html)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime = None
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}") as client:
            assert client.get("/").text == html
            assert client.get("/api/runs").json() == []
            runtime = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
            runtime.event("run.started", "lead", {"query": "<script>untrusted</script>"})
            assert len(client.get("/api/runs").json()) == 1
            response = client.get("/api/run", params={"name": runtime.root.name})
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["query"] == "<script>untrusted</script>"
            runtime.event("model.error", "lead", {"type": "CancelledError"})
            assert len(client.get("/api/run", params={
                "name": runtime.root.name,
            }).json()["events"]) == 2
            assert client.get("/api/run", params={"name": "../secret"}).status_code == 400
            assert client.get("/.env").status_code == 404
            assert client.get("/" + runtime.root.name + "/events.sqlite").status_code == 404
    finally:
        if runtime:
            runtime.close()
        server.shutdown()
        thread.join()
        server.server_close()


def test_packaged_html_matches_runs_entry():
    from pathlib import Path

    assert Path("runs/index.html").read_text() == files(
        "multi_agent_research"
    ).joinpath("viewer.html").read_text()


def read_export(path):
    import json

    content = path.read_text()
    serialized = content.split(" = JSON.parse(", 1)[1].removesuffix(");\n")
    return json.loads(json.loads(serialized))


def test_automatic_exports_refresh_and_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-long-value")
    runtime = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    try:
        assert (tmp_path / "index.html").exists()
        runtime.event("run.started", "lead", {"query": "test-secret-long-value"})
        runtime.viewer_export.wait()
        manifest = read_export(tmp_path / "viewer-manifest.js")
        assert manifest[0]["query"] == "[REDACTED]"
        trace = read_export(runtime.root / "viewer-data.js")
        assert len(trace["events"]) == 1
        ref = trace["events"][0]["payload_ref"]
        payload = read_export(runtime.root / "viewer-payloads" / f"{ref}.js")
        assert payload == {"query": "[REDACTED]"}
        runtime.event("model.response", "lead", {
            "content": "generated", "usage_metadata": {"input_tokens": 4, "output_tokens": 2},
        })
        runtime.viewer_export.wait()
        assert len(read_export(runtime.root / "viewer-data.js")["events"]) == 2
        assert read_export(tmp_path / "viewer-manifest.js")[0]["usage"]["output_tokens"] == 2
        runtime.event("run.finished", "system", {"status": "failed", "stop_reason": "test"})
        runtime.viewer_export.wait()
        assert read_export(tmp_path / "viewer-manifest.js")[0]["status"] == "failed"
    finally:
        runtime.close()


def test_untrusted_payload_is_a_json_string(tmp_path):
    import subprocess

    from multi_agent_research.viewer_export import write_data

    payload = {
        "text": '</script><script>globalThis.compromised=true</script>"); throw Error("oops");',
        "__proto__": {"compromised": True},
        "unicode": "\u2028\u2029",
    }
    write_data(tmp_path, "payload.js", payload)
    script = (tmp_path / "payload.js").read_text()
    assert "<script>" not in script
    assert read_export(tmp_path / "payload.js") == payload
    # Execute the actual wrapper, verifying the text remains inert and prototype-safe.
    import shutil

    if shutil.which("node"):
        result = subprocess.run(
            ["node", "-e", "global.window={__MAR_DATA__:Object.create(null)};"
             + script
             + "if(globalThis.compromised||({}).compromised)process.exit(1);"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr


def test_interleaved_writers_preserve_both_runs(tmp_path):
    one = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    two = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    try:
        one.event("run.started", "lead", {"query": "one"})
        two.event("run.started", "lead", {"query": "two"})
        one.event("model.error", "lead", {"type": "CancelledError"})
        one.viewer_export.wait()
        two.viewer_export.wait()
        manifest = read_export(tmp_path / "viewer-manifest.js")
        assert {r["query"] for r in manifest} == {"one", "two"}
        assert len(read_export(one.root / "viewer-data.js")["events"]) == 2
        assert len(read_export(two.root / "viewer-data.js")["events"]) == 1
    finally:
        one.close()
        two.close()


def test_export_failure_does_not_lose_authoritative_events(tmp_path, monkeypatch):
    import multi_agent_research.viewer_export as export

    runtime = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    original = export.write_data

    def fail(*args):
        raise OSError("disk export unavailable")

    try:
        monkeypatch.setattr(export, "write_data", fail)
        with pytest.warns(RuntimeWarning, match="Browser export"):
            runtime.event("run.started", "lead", {"query": "still logged"})
            runtime.viewer_export.wait()
        assert read_run(tmp_path, runtime.root.name)["query"] == "still logged"
        monkeypatch.setattr(export, "write_data", original)
        runtime.event("model.error", "lead", {"type": "CancelledError"})
        runtime.viewer_export.wait()
        trace = read_export(runtime.root / "viewer-data.js")
        assert len(trace["events"]) == 2
        for event in trace["events"]:
            assert (runtime.root / "viewer-payloads" / f"{event['payload_ref']}.js").exists()
    finally:
        runtime.close()


def test_migration_missing_payloads_and_removed_runs(tmp_path):
    import shutil

    from multi_agent_research.viewer_export import export_existing

    runtime = Runtime(RunConfig(output_dir=tmp_path), None, None, None)
    runtime.event("run.started", "lead", {"query": "legacy"})
    runtime.close()
    legacy = tmp_path / runtime.run_id
    runtime.root.rename(legacy)
    for artifact in (legacy / "artifacts").iterdir():
        artifact.unlink()
    result = export_existing(tmp_path)
    assert result["errors"] == {}
    assert result["exported"] == [legacy.name]
    manifest = read_export(tmp_path / "viewer-manifest.js")
    assert [r["directory"] for r in manifest] == [legacy.name]
    trace = read_export(legacy / "viewer-data.js")
    assert trace["warnings"]
    shutil.rmtree(legacy)
    export_existing(tmp_path)
    assert read_export(tmp_path / "viewer-manifest.js") == []


def test_local_script_loader_refreshes_without_fetch(tmp_path):
    """Exercise browser-independent loader logic with an in-memory DOM/script fixture."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("Node is only needed for the standalone JavaScript loader test")
    html = files("multi_agent_research").joinpath("viewer.html").read_text()
    loader = "// Classic relative scripts" + html.split(
        "// Classic relative scripts", 1
    )[1].split("function showError", 1)[0]
    code = """
const assert=require('node:assert/strict');
global.window={};
global.location={href:'file:///fixture/index.html'};
const exportsByPath=new Map();
global.document={
 createElement:()=>({remove(){}}),
 head:{append(script){
  setTimeout(()=>{
   const path=new URL(script.src).pathname.replace('/fixture/','');
   if(exportsByPath.has(path)){
    window.__MAR_DATA__[path]=structuredClone(exportsByPath.get(path));
    script.onload();
   }else script.onerror();
  },0);
 }}
};
global.fetch=()=>{throw Error('Must not use fetch')};
""" + loader + """
(async()=>{
 exportsByPath.set('viewer-manifest.js',[]);
 assert.deepEqual(await loadData('viewer-manifest.js'),[]);
 const name='a'.repeat(32), ref='b'.repeat(64);
 exportsByPath.set('viewer-manifest.js',[{directory:name}]);
 assert.equal((await loadData('viewer-manifest.js')).length,1);
 exportsByPath.set(name+'/viewer-data.js',{
  warnings:[],events:[{payload_ref:ref}]
 });
 exportsByPath.set(name+'/viewer-payloads/'+ref+'.js',{content:'first'});
 assert.equal((await loadRun(name)).events[0].payload.content,'first');
 const next='c'.repeat(64);
 exportsByPath.set(name+'/viewer-data.js',{
  warnings:[],events:[{payload_ref:ref},{payload_ref:next}]
 });
 exportsByPath.set(name+'/viewer-payloads/'+next+'.js',{content:'second'});
 const refreshed=await loadRun(name);
 assert.equal(refreshed.events.length,2);
 assert.equal(refreshed.events[1].payload.content,'second');
 await assert.rejects(loadRun('../outside'));
 await assert.rejects(loadData('missing.js'),/Cannot load/);
 assert.equal(Object.keys(window.__MAR_DATA__).length,0);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    path = tmp_path / "loader-test.js"
    path.write_text(code)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
