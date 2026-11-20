"""WP1: read-only fault-to-checkpoint lookups over a real offline attempt (ScriptedModel)."""

import json
import shutil
import sqlite3
from contextlib import closing
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


# --- WP3: offset discrimination, persistent denial, forged parent chain.

PAGE = 32  # max_document_chars for the paged fixture, so page 1 starts at character 32
LONG_TEXT = "The value is 42. " * 5  # 85 characters: pages at offsets 0, 32 and 64


class PagingModel(ScriptedModel):
    """Workers page by next_offset and retry a failed read up to `retries` times.

    Past that they stop calling tools (and run out of turns). Lead and judge
    turns are ScriptedModel's.
    """

    def __init__(self, retries=1):
        self.retries = retries

    async def invoke(self, role, agent, messages, tools, config):
        if role != "worker":
            return await super().invoke(role, agent, messages, tools, config)
        turn = 1 + sum(isinstance(m, AIMessage) for m in messages)

        def response(*calls):
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
                for i, (name, args) in enumerate(calls)
            ], usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

        document = f"doc{agent[-1]}"
        calls = {c["id"]: c for m in messages if isinstance(m, AIMessage) for c in m.tool_calls}
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            return response(("read_document", {"document_id": document}))
        last = json.loads(results[-1].content)
        if "error" in last:
            if sum("error" in json.loads(m.content) for m in results) > self.retries:
                return response()
            return response(("read_document", calls[results[-1].tool_call_id]["args"]))
        if last["next_offset"] is not None:
            return response(("read_document",
                             {"document_id": document, "offset": last["next_offset"]}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [document],
        }))


def paged_documents():
    return OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Paged fixture {i}",
                      url=f"https://example.org/paged/{i}", text=LONG_TEXT)
        for i in range(1, WORKERS + 1)
    ])


def read_requests(run_dir, events, agent):
    """agent's read_document tool.requests, keyed by the character offset requested."""
    reads = {}
    for event in events:
        if event["event_type"] != "tool.request" or event["agent_id"] != agent:
            continue
        call = payload(run_dir, event)
        if call["name"] == "read_document":
            reads.setdefault(call["args"].get("offset", 0), []).append(event)
    return reads


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["immediate", "timeout"])
async def test_fault_site_is_the_denied_page_not_the_read_before_it(tmp_path, mode):
    # One transient denial of doc2's page 1 only: the worker retries it, then reads page 2.
    config = RunConfig(output_dir=tmp_path / "runs", call_timeout_seconds=0.05,
                       max_document_chars=PAGE, tool_failure={
                           "enabled": True, "mode": mode, "document_ids": ["doc2"],
                           "offsets": [PAGE], "max_failures": 1, "persistent": False,
                       })
    result = await run_qa("What is the value?", config, PagingModel(), paged_documents(),
                          reference_answer="42")
    run = Path(result["output_dir"])
    events = read_events(run)
    worker = [e for e in events if e["agent_id"] == FAULTED]
    [injected] = [e for e in events if e["event_type"] == "tool.failure_injected"]

    reads = read_requests(run, events, FAULTED)
    assert sorted(reads) == [0, PAGE, 2 * PAGE]
    [page0], [denied, retry] = reads[0], reads[PAGE]
    # The page-0 read really succeeded and really paged, before the injection.
    [page0_result] = [e for e in worker if e["event_type"] == "tool.result"
                      and e["tool_call_id"] == page0["tool_call_id"]]
    body = payload(run, page0_result)
    assert (body["document_id"], body["offset"], body["next_offset"]) == ("doc2", 0, PAGE)
    assert page0["sequence"] < page0_result["sequence"] < denied["sequence"]
    assert page0_result["sequence"] < injected["sequence"]

    [site] = selective.find_tool_fault_sites(run)
    assert (site["agent_id"], site["document_id"], site["offset"]) == (FAULTED, "doc2", PAGE)
    assert site["recovery_point_id"] == denied["recovery_point_id"]
    assert site["tool_call_id"] == denied["tool_call_id"]
    # Neither the successful page-0 read nor the later retry is the recovery point.
    assert len({page0["recovery_point_id"], denied["recovery_point_id"],
                retry["recovery_point_id"]}) == 3
    # The checkpoint itself would replay the page-1 request.
    [point] = [p for p in list_recovery_points(run, agent=FAULTED)
               if p["recovery_point_id"] == site["recovery_point_id"]]
    assert payload(run, {"payload_ref": point["request_ref"]})["args"] == {
        "document_id": "doc2", "offset": PAGE,
    }


@pytest.mark.asyncio
async def test_persistent_denial_survives_the_retry(tmp_path):
    config = RunConfig(output_dir=tmp_path / "runs", call_timeout_seconds=0.05,
                       tool_failure={"enabled": True, "mode": "immediate",
                                     "document_ids": ["doc2"], "max_failures": None,
                                     "persistent": True})
    result = await run_qa("What is the value?", config, PagingModel(retries=1), documents(),
                          reference_answer="42")
    run = Path(result["output_dir"])
    events = read_events(run)
    injected = [e for e in events if e["event_type"] == "tool.failure_injected"]
    bodies = [payload(run, e) for e in injected]

    assert [e["agent_id"] for e in injected] == [FAULTED, FAULTED]
    assert [(b["document_id"], b["offset"]) for b in bodies] == [("doc2", 0)] * 2
    assert [b["failure_number"] for b in bodies] == [1, 2]
    assert [b["attempt"] for b in bodies] == [1, 2]
    # Both reads were denied: the faulted worker never received a page.
    [[first, second]] = read_requests(run, events, FAULTED).values()
    assert not [e for e in events if e["event_type"] == "tool.result"
                and e["agent_id"] == FAULTED and "document_id" in payload(run, e)]

    sites = selective.find_tool_fault_sites(run)
    assert [(s["agent_id"], s["document_id"], s["offset"]) for s in sites] == [
        (FAULTED, "doc2", 0)] * 2
    # Returned in event order: the first site is the first denial, before any retry.
    assert [s["event_sequence"] for s in sites] == [e["sequence"] for e in injected]
    assert [s["recovery_point_id"] for s in sites] == [
        first["recovery_point_id"], second["recovery_point_id"]]
    assert [s["tool_call_id"] for s in sites] == [first["tool_call_id"],
                                                  second["tool_call_id"]]
    assert first["recovery_point_id"] != second["recovery_point_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("forged", ["model.request", "sibling tool.request",
                                    "complete_task tool.request"])
async def test_forged_parent_chain_is_rejected(tmp_path, forged):
    run = await attempt(tmp_path)
    copy = tmp_path / "forged"
    shutil.copytree(run, copy)
    events = read_events(copy)
    [injected] = [e for e in events if e["event_type"] == "tool.failure_injected"]
    candidates = {
        "model.request": [e for e in events if e["event_type"] == "model.request"
                          and e["agent_id"] == FAULTED],
        "sibling tool.request": [e for e in events if e["event_type"] == "tool.request"
                                 and e["agent_id"] == "batch1-worker1"],
        "complete_task tool.request": [
            e for e in events if e["event_type"] == "tool.request"
            and e["agent_id"] == FAULTED and payload(copy, e)["name"] == "complete_task"],
    }[forged]
    target = candidates[0]
    assert target["event_id"] != injected["parent_event_ids"][-1]
    # The untampered copy still resolves, so any later error is the forgery's.
    assert len(selective.find_tool_fault_sites(copy)) == 1

    with closing(sqlite3.connect(copy / "events.sqlite")) as db, db:
        [raw] = db.execute("SELECT body FROM events WHERE event_id = ?",
                           (injected["event_id"],)).fetchone()
        body = json.loads(raw)
        body["parent_event_ids"] = [*body["parent_event_ids"][:-1], target["event_id"]]
        db.execute("UPDATE events SET body = ? WHERE event_id = ?",
                   (json.dumps(body), injected["event_id"]))

    with pytest.raises(ValueError, match="does not follow a read_document tool.request"):
        selective.find_tool_fault_sites(copy)
    assert len(selective.find_tool_fault_sites(run)) == 1  # the source attempt is untouched
