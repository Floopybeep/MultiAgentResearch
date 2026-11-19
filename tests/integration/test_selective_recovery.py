"""WP1: read-only fault-to-checkpoint lookups over a real offline attempt (ScriptedModel)."""

import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from multi_agent_research import selective
from multi_agent_research.config import RunConfig
from multi_agent_research.recovery import list_recovery_points
from multi_agent_research.runner import run_qa
from multi_agent_research.runtime import Runtime
from multi_agent_research.tools import tool_failures
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3
FAULTED = "batch1-worker2"


def prompt(i):
    return f"Read doc{i} and report its value."


class ScriptedModel:
    """Workers read until one read succeeds, then complete; replays behave like live runs."""

    async def invoke(self, role, agent, messages, tools, config):
        turn = 1 + sum(isinstance(m, AIMessage) for m in messages)

        def response(*calls):
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
                for i, (name, args) in enumerate(calls)
            ], usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

        if role == "judge":
            return AIMessage(content='{"correct": true, "reason": "Scripted decision"}')
        if role == "lead":
            if turn == 1:
                return response(("memory_write", {"plan": "Read every document."}))
            if turn == 2:
                return response(*[
                    ("run_blocking_subagent", {"prompt": prompt(i), "document_id": f"doc{i}"})
                    for i in range(1, WORKERS + 1)
                ])
            return response(("submit_answer", {"answer": "{42}"}))
        document = f"doc{agent[-1]}"
        read = any(isinstance(m, ToolMessage) and "document_id" in json.loads(m.content)
                   for m in messages)
        if not read:
            return response(("read_document", {"document_id": document}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [document],
        }))


def documents():
    return OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])


def fault(mode):
    # One transient denial of doc2: batch1-worker2 retries and then completes.
    return {"enabled": True, "mode": mode, "document_ids": ["doc2"],
            "max_failures": 1, "persistent": False}


async def attempt(tmp_path, mode="immediate"):
    config = RunConfig(output_dir=tmp_path / "runs", call_timeout_seconds=0.05,
                       tool_failure=fault(mode))
    result = await run_qa("What is the value?", config, ScriptedModel(), documents(),
                          reference_answer="42")
    return Path(result["output_dir"])


def read_events(run_dir):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        return [{**json.loads(body), "sequence": seq} for seq, body in db.execute(
            "SELECT sequence, body FROM events ORDER BY sequence"
        )]


def payload(run_dir, event):
    return json.loads((Path(run_dir) / "artifacts" / f"{event['payload_ref']}.json").read_text())


def test_assignment_digest_is_sha256_of_utf8_prompt():
    import hashlib
    text = "Lies doc1 — Wert?"
    assert selective.assignment_digest(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert selective.assignment_digest(text) != selective.assignment_digest(text + " ")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["immediate", "timeout"])
async def test_fault_site_resolves_the_failed_read(tmp_path, mode):
    run = await attempt(tmp_path, mode)
    events = read_events(run)
    [injected] = [e for e in events if e["event_type"] == "tool.failure_injected"]
    [request] = [e for e in events if e["event_id"] == injected["parent_event_ids"][-1]]

    assert selective.find_tool_fault_sites(run) == [{
        "agent_id": FAULTED, "document_id": "doc2", "offset": 0, "mode": mode, "batch": 1,
        "recovery_point_id": request["recovery_point_id"],
        "tool_call_id": request["tool_call_id"], "event_sequence": injected["sequence"],
    }]
    [point] = [p for p in list_recovery_points(run, agent=FAULTED)
               if p["recovery_point_id"] == request["recovery_point_id"]]
    assert point["call_name"] == "read_document" and point["graph"]["kind"] == "worker"


@pytest.mark.asyncio
async def test_sibling_cache_reuses_only_healthy_completed_workers(tmp_path):
    run = await attempt(tmp_path)
    events = read_events(run)
    delivered = {e["assignment_id"]: e for e in events if e["event_type"] == "worker.delivered"}
    # The faulted worker completed after its retry, yet is still not reusable.
    assert payload(run, delivered[FAULTED])["status"] == "completed"

    cache = selective.sibling_cache(run, 1, exclude="none")
    assert sorted(cache) == ["batch1-worker1", "batch1-worker3"]
    for i in (1, 3):
        agent = f"batch1-worker{i}"
        assert cache[agent] == {
            "assignment_id": agent, "document_id": f"doc{i}",
            "assignment_digest": selective.assignment_digest(prompt(i)),
            "delivery": payload(run, delivered[agent]), "origin": "sibling",
            "source_run_id": delivered[agent]["run_id"],
            "source_event_id": delivered[agent]["event_id"],
        }
        assert "verification" not in cache[agent]["delivery"]
    assert sorted(selective.sibling_cache(run, 1, exclude="batch1-worker1")) == ["batch1-worker3"]
    assert selective.sibling_cache(run, 2, exclude=FAULTED) == {}


@pytest.mark.asyncio
async def test_lead_batch_and_earliest_lead_points(tmp_path):
    run = await attempt(tmp_path)
    requests = [e for e in read_events(run)
                if e["event_type"] == "delegation.request" and e["batch_id"] == 1]
    assert len(requests) == WORKERS
    point_id = selective.lead_batch_point(run, 1)
    assert point_id == requests[0]["recovery_point_id"]
    # Distinct IDs, one shared pre-batch checkpoint: any of them replays the batch.
    points = {p["recovery_point_id"]: p for p in list_recovery_points(run, agent="lead")}
    configs = {json.dumps(points[r["recovery_point_id"]]["graph_config"], sort_keys=True)
               for r in requests}
    assert len(configs) == 1
    with pytest.raises(ValueError):
        selective.lead_batch_point(run, 2)

    earliest = selective.earliest_lead_point(run)
    assert points[earliest]["call_seq"] == 1 and earliest.endswith("/br00/lead/call0001")


@pytest.mark.asyncio
async def test_lookups_do_not_modify_the_attempt(tmp_path):
    run = await attempt(tmp_path)
    before = {p: p.read_bytes() for p in sorted(run.rglob("*")) if p.is_file()}
    [site] = selective.find_tool_fault_sites(run)
    selective.sibling_cache(run, site["batch"], site["agent_id"])
    selective.lead_batch_point(run, site["batch"])
    selective.earliest_lead_point(run)
    after = {p: p.read_bytes() for p in sorted(run.rglob("*")) if p.is_file()}
    # A mode=ro reader of a WAL database still leaves SQLite's empty -wal and -shm
    # index files beside it, as recovery.py's read-only opens do. No data changes.
    added = {p.name for p in after.keys() - before.keys()}
    assert added <= {"events.sqlite-wal", "events.sqlite-shm"}
    assert after.get(run / "events.sqlite-wal", b"") == b""
    assert {p: after[p] for p in before} == before


@pytest.mark.asyncio
async def test_fault_on_a_non_worker_agent_id_raises(tmp_path):
    config = RunConfig(output_dir=tmp_path / "runs", call_timeout_seconds=0.05,
                       tool_failure=fault("immediate"))
    runtime = Runtime(config, None, documents(), root=tmp_path / "run")
    try:
        with pytest.raises(tool_failures.ToolUnavailableError):
            await runtime.read_document("doc2", 0, agent="worker")
    finally:
        runtime.close()
    with pytest.raises(ValueError, match="Not a worker agent_id"):
        selective.find_tool_fault_sites(tmp_path / "run")


# --- uses recover(), which imports OpenAIChatCompletionsAdapter (never instantiated
# here: a ScriptedModel is passed). Run only with explicit approval.


@pytest.mark.asyncio
async def test_recovered_entry_matches_the_sibling_shape(tmp_path):
    from multi_agent_research.recovery import recover

    run = await attempt(tmp_path)
    [site] = selective.find_tool_fault_sites(run)
    result = await recover(run, site["recovery_point_id"], model=ScriptedModel(),
                           output_dir=tmp_path / "replay", disable_faults=True)
    assert result["status"] == "completed"

    entry = selective.recovered_entry(run, tmp_path / "replay", FAULTED)
    [finished] = [e for e in read_events(tmp_path / "replay")
                  if e["event_type"] == "recovery.finished"]
    assert entry == {
        "assignment_id": FAULTED, "document_id": "doc2",
        "assignment_digest": selective.assignment_digest(prompt(2)),
        "delivery": result["worker_result"], "origin": "recovered",
        "source_run_id": result["run_id"], "source_event_id": finished["event_id"],
    }
    sibling = selective.sibling_cache(run, 1, FAULTED)["batch1-worker1"]
    assert entry["delivery"].keys() == sibling["delivery"].keys()
    assert entry.keys() == sibling.keys()

    with pytest.raises(ValueError, match="not batch1-worker1"):
        selective.recovered_entry(run, tmp_path / "replay", "batch1-worker1")
    recovery = tmp_path / "replay" / "recovery.json"
    data = json.loads(recovery.read_text())
    data["worker_result"]["status"] = "budget_exhausted"
    recovery.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="did not complete"):
        selective.recovered_entry(run, tmp_path / "replay", FAULTED)
