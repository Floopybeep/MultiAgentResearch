"""WP4: the replay cache skips workers whose result is already delivered (ScriptedModel only)."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from multi_agent_research import selective
from multi_agent_research.config import RunConfig
from multi_agent_research.recovery import recover
from multi_agent_research.runner import run_qa
from multi_agent_research.runtime import INJECTION_EVENTS
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3
FAULTED = "batch1-worker2"
HEALTHY = ["batch1-worker1", "batch1-worker3"]


def prompt(i):
    return f"Read doc{i} and report its value."


class ScriptedModel:
    """Workers read until one read succeeds, then complete; the Lead delegates once."""

    order = range(1, WORKERS + 1)
    suffix = ""

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
                    ("run_blocking_subagent",
                     {"prompt": prompt(i) + self.suffix, "document_id": f"doc{i}"})
                    for i in self.order
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


class ReversedLead(ScriptedModel):
    """Same assignments, delegated in reverse, so every worker position shifts."""

    order = range(WORKERS, 0, -1)


def documents():
    return OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])


def tool_fault(mode="immediate"):
    # One transient denial of doc2; always_verify stays off so deliveries are plain dumps.
    return {"enabled": True, "mode": mode, "document_ids": ["doc2"],
            "max_failures": 1, "persistent": False, "interrupt_on_fault": "batch"}


async def execute(tmp_path, model=None, name="runs", **settings):
    config = RunConfig(output_dir=tmp_path / name, call_timeout_seconds=0.05, **settings)
    return await run_qa("What is the value?", config, model or ScriptedModel(), documents(),
                        reference_answer="42")


async def interrupted(tmp_path, mode="immediate"):
    result = await execute(tmp_path, tool_failure=tool_fault(mode))
    assert result["status"] == "interrupted"
    return Path(result["output_dir"])


def read_events(run_dir, run_id=None):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        events = [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]
    # recover() copies the source log into the branch; scope to one run's own events.
    return [e for e in events if run_id is None or e["run_id"] == run_id]


def payload(run_dir, event):
    return json.loads((Path(run_dir) / "artifacts" / f"{event['payload_ref']}.json").read_text())


def recorded_config(run_dir):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        [body] = db.execute("SELECT body FROM records WHERE key='config'").fetchone()
    return json.loads(body)


def sibling_cache_for(attempt):
    """The cache for the attempt's faulted batch, excluding the agent the fault sites name."""
    first = selective.earliest_fault_by_agent(selective.find_tool_fault_sites(attempt))
    [(agent, site)] = first.items()
    return selective.sibling_cache(attempt, batch=site["batch"], exclude=agent), agent, site


def of_type(events, kind):
    return [e for e in events if e["event_type"] == kind]


# T1
@pytest.mark.asyncio
async def test_load_cache_round_trips_write_cache(tmp_path):
    attempt = await interrupted(tmp_path)
    cache, agent, site = sibling_cache_for(attempt)
    replayed = await recover(attempt, site["recovery_point_id"], model=ScriptedModel(),
                             output_dir=tmp_path / "worker", disable_faults=True)
    assert replayed["status"] == "completed"
    # Both origins: the healthy siblings plus the faulted worker recovered on its own.
    merged = {**cache, agent: selective.recovered_entry(attempt, tmp_path / "worker", agent)}
    assert sorted(merged) == sorted([*HEALTHY, FAULTED])
    path = tmp_path / "cache.json"
    selective.write_cache(path, merged)
    assert selective.load_cache(path) == merged


def _rename(entry, agent):
    return {**entry, "assignment_id": agent, "delivery": {**entry["delivery"],
                                                          "assignment_id": agent}}


def _delivery(**changes):
    def mutate(cache):
        cache["batch1-worker1"]["delivery"].update(changes)
    return mutate


def _entry(**changes):
    def mutate(cache):
        cache["batch1-worker1"].update(changes)
    return mutate


def _drop_key(cache):
    del cache["batch1-worker1"]["origin"]


def _duplicate(cache):
    first, third = cache["batch1-worker1"], cache["batch1-worker3"]
    third.update(document_id=first["document_id"], assignment_digest=first["assignment_digest"])


def _misfiled(cache):
    cache["batch9-worker9"] = cache.pop("batch1-worker1")


CORRUPTIONS = {
    "missing key": (_drop_key, "exactly the ReplayEntry keys"),
    "extra key": (_entry(note="x"), "exactly the ReplayEntry keys"),
    "unknown origin": (_entry(origin="restart"), "unknown origin"),
    "uppercase digest": (_entry(assignment_digest="A" * 64), "64 lowercase hex"),
    "short digest": (_entry(assignment_digest="a" * 63), "64 lowercase hex"),
    "non-hex digest": (_entry(assignment_digest="g" * 64), "64 lowercase hex"),
    "non-string digest": (_entry(assignment_digest=7), "non-string"),
    # WorkerResult forbids extras, so pydantic refuses this one before _plain compares.
    "verified delivery": (_delivery(verification={"verified": True}), "WorkerResult"),
    "non-dump delivery": (_delivery(document_ids="doc1"), "WorkerResult"),
    "failed delivery": (_delivery(status="failed"), "did not complete"),
    "foreign delivery": (_delivery(assignment_id="batch1-worker3"), "belongs to"),
    "duplicate assignment": (_duplicate, "Duplicate"),
    "misfiled entry": (_misfiled, "wrong assignment_id"),
}


# T2
@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", list(CORRUPTIONS))
async def test_load_cache_rejects_each_malformed_entry(tmp_path, corruption):
    mutate, message = CORRUPTIONS[corruption]
    cache, _, _ = sibling_cache_for(await interrupted(tmp_path))
    mutate(cache)
    # Written raw: write_cache would refuse it before load_cache ever saw it.
    path = tmp_path / "cache.json"
    path.write_text(json.dumps(cache))
    with pytest.raises(ValueError, match=message):
        selective.load_cache(path)


@pytest.mark.asyncio
async def test_write_cache_refuses_before_writing(tmp_path):
    cache, _, _ = sibling_cache_for(await interrupted(tmp_path))
    cache["batch1-worker1"]["origin"] = "restart"
    with pytest.raises(ValueError, match="unknown origin"):
        selective.write_cache(tmp_path / "cache.json", cache)
    assert not (tmp_path / "cache.json").exists()


# T3
@pytest.mark.asyncio
async def test_lookup_matches_the_assignment_not_the_agent_name(tmp_path):
    cache, _, _ = sibling_cache_for(await interrupted(tmp_path))
    moved = {"batch2-worker7": _rename(cache["batch1-worker1"], "batch2-worker7")}
    assert selective.cache_lookup(moved, "doc1", prompt(1)) == moved["batch2-worker7"]
    assert selective.cache_lookup(moved, "doc1", prompt(1)[:-1] + "!") is None
    assert selective.cache_lookup(moved, "doc3", prompt(1)) is None


# T4
@pytest.mark.asyncio
async def test_lookup_raises_on_an_ambiguous_match(tmp_path):
    cache, _, _ = sibling_cache_for(await interrupted(tmp_path))
    # Built in memory: load_cache would already have refused this pair.
    twin = {**cache, "batch2-worker1": _rename(cache["batch1-worker1"], "batch2-worker1")}
    with pytest.raises(ValueError, match="2 cache entries match"):
        selective.cache_lookup(twin, "doc1", prompt(1))


def test_earliest_fault_groups_by_agent_and_orders_by_sequence():
    def site(agent, sequence):
        return selective.FaultSite(agent_id=agent, document_id="d", offset=0, mode="immediate",
                                   batch=1, recovery_point_id=f"{agent}@{sequence}",
                                   tool_call_id="c", event_sequence=sequence)
    # Interleaved and out of order: worker2's earliest site is not first in the list.
    sites = [site("batch1-worker2", 40), site("batch1-worker1", 30),
             site("batch1-worker2", 20), site("batch1-worker1", 50)]
    first = selective.earliest_fault_by_agent(sites)
    assert {a: s["event_sequence"] for a, s in first.items()} == {
        "batch1-worker1": 30, "batch1-worker2": 20}


def test_reuse_relabels_and_keeps_provenance():
    delivery = {"assignment_id": "batch1-worker1", "status": "completed", "findings": "42",
                "document_ids": ["doc1"], "uncertainties": [], "stop_reason": "complete_task"}
    entry = selective.ReplayEntry(
        assignment_id="batch1-worker1", document_id="doc1",
        assignment_digest=selective.assignment_digest(prompt(1)), delivery=delivery,
        origin="sibling", source_run_id="run", source_event_id="event")
    result, event = selective.reuse(entry, "batch1-worker3")
    assert result.model_dump() == {**delivery, "assignment_id": "batch1-worker3"}
    assert event == {"assignment_id": "batch1-worker3", "source_assignment_id": "batch1-worker1",
                     "document_id": "doc1", "assignment_digest": entry["assignment_digest"],
                     "origin": "sibling", "source_run_id": "run", "source_event_id": "event"}
    assert entry["delivery"]["assignment_id"] == "batch1-worker1"  # the cache is not mutated
    assert "worker.reused" not in INJECTION_EVENTS


async def replay(attempt, tmp_path, name, cache_path=None):
    result = await recover(attempt, selective.lead_batch_point(attempt, 1), model=ScriptedModel(),
                           output_dir=tmp_path / name, disable_faults=True,
                           replay_cache_path=cache_path)
    return result, read_events(tmp_path / name, result["run_id"])


# T5
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["immediate", "timeout"])
async def test_replay_reruns_only_the_faulted_worker(tmp_path, mode):
    attempt = await interrupted(tmp_path, mode)
    cache, agent, _ = sibling_cache_for(attempt)
    assert agent == FAULTED and sorted(cache) == HEALTHY
    selective.write_cache(tmp_path / "cache.json", cache)

    # Baseline, the measured 3-of-3: without the cache every worker reruns.
    _, uncached = await replay(attempt, tmp_path, "uncached")
    assert sorted(e["agent_id"] for e in of_type(uncached, "worker.started")) == sorted(
        [*HEALTHY, FAULTED])

    result, events = await replay(attempt, tmp_path, "cached", str(tmp_path / "cache.json"))
    assert (result["status"], result["stop_reason"]) == ("completed", "submit_answer")
    assert [e["agent_id"] for e in of_type(events, "worker.started")] == [FAULTED]
    source = {e["assignment_id"]: e for e in of_type(read_events(attempt), "worker.delivered")}
    reused = {e["assignment_id"]: e for e in of_type(events, "worker.reused")}
    assert sorted(reused) == HEALTHY
    delivered = {e["assignment_id"]: e for e in of_type(events, "worker.delivered")}
    by_id = {e["event_id"]: e for e in events}
    for name in HEALTHY:
        body = payload(tmp_path / "cached", reused[name])
        assert body == {
            "assignment_id": name, "source_assignment_id": name, "document_id": f"doc{name[-1]}",
            "assignment_digest": selective.assignment_digest(prompt(int(name[-1]))),
            "origin": "sibling", "source_run_id": source[name]["run_id"],
            "source_event_id": source[name]["event_id"],
        }
        # Content-addressed artifacts: equal refs are byte-identical payloads.
        assert delivered[name]["payload_ref"] == source[name]["payload_ref"]
        assert delivered[name]["parent_event_ids"] == [reused[name]["event_id"]]
    # The faulted worker's result is this replay's own, produced by its own worker run.
    assert FAULTED not in reused
    [parent] = delivered[FAULTED]["parent_event_ids"]
    assert by_id[parent]["agent_id"] == FAULTED and by_id[parent]["event_type"] != "worker.reused"
    assert payload(tmp_path / "cached", delivered[FAULTED])["status"] == "completed"
    assert sorted(result["worker_results"]) == sorted([*HEALTHY, FAULTED])
    assert not [e for e in events if e["event_type"] in INJECTION_EVENTS]
    # Worker model calls: only the faulted worker's, exactly as many as it made uncached.
    def worker_calls(log):
        return sorted(e["agent_id"] for e in of_type(log, "model.request")
                      if e["agent_id"] != "lead")
    assert worker_calls(events) == [a for a in worker_calls(uncached) if a == FAULTED]


# T6
@pytest.mark.asyncio
async def test_cache_hit_does_not_suppress_a_dropped_connection(tmp_path):
    clean = await execute(tmp_path, name="clean")
    cache = selective.sibling_cache(clean["output_dir"], batch=1, exclude="none")
    assert sorted(cache) == sorted([*HEALTHY, FAULTED])  # every position is cached
    selective.write_cache(tmp_path / "cache.json", cache)

    # select="last" with one delivered drops positions 2 and 3.
    result = await execute(tmp_path, tool_failure={"replay_cache_path": str(tmp_path / "cache.json")},
                           connection_drop={"enabled": True, "num_delivered": 1})
    events = read_events(result["output_dir"])
    dropped = {e["assignment_id"] for e in of_type(events, "connection.dropped")}
    reused = {e["assignment_id"] for e in of_type(events, "worker.reused")}
    assert dropped == {"batch1-worker2", "batch1-worker3"}
    assert not dropped & reused
    # The cache was live for the position the drop let through, so the absence above is real.
    assert reused == {"batch1-worker1"}
    assert [f["event_type"] for f in result["injected_faults"]] == ["connection.dropped"] * 2


# T7
@pytest.mark.asyncio
async def test_no_cache_path_never_touches_the_cache(tmp_path, monkeypatch):
    attempt = await interrupted(tmp_path)

    def untouched(*args, **kwargs):
        raise AssertionError("replay cache consulted with replay_cache_path None")

    monkeypatch.setattr(selective, "load_cache", untouched)
    monkeypatch.setattr(selective, "cache_lookup", untouched)
    result, events = await replay(attempt, tmp_path, "uncached")
    assert result["status"] == "completed"
    assert recorded_config(tmp_path / "uncached")["tool_failure"]["replay_cache_path"] is None
    assert not of_type(events, "worker.reused")
    assert sorted(e["agent_id"] for e in of_type(events, "worker.started")) == sorted(
        [*HEALTHY, FAULTED])


# T8
@pytest.mark.asyncio
async def test_replay_does_not_reinterrupt_under_the_inherited_config(tmp_path):
    attempt = await interrupted(tmp_path)
    cache, _, _ = sibling_cache_for(attempt)
    selective.write_cache(tmp_path / "cache.json", cache)
    result, events = await replay(attempt, tmp_path, "cached", str(tmp_path / "cache.json"))
    inherited = recorded_config(tmp_path / "cached")["tool_failure"]
    assert inherited["interrupt_on_fault"] == "batch"
    assert inherited["replay_cache_path"] == str(tmp_path / "cache.json")
    assert not of_type(events, "tool.failure_injected")
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_shifted_positions_reuse_under_the_new_names(tmp_path):
    clean = await execute(tmp_path, name="clean")
    cache = selective.sibling_cache(clean["output_dir"], batch=1, exclude="none")
    selective.write_cache(tmp_path / "cache.json", copy.deepcopy(cache))
    result = await execute(tmp_path, ReversedLead(),
                           tool_failure={"replay_cache_path": str(tmp_path / "cache.json")})
    assert result["status"] == "completed"
    events = read_events(result["output_dir"])
    assert not of_type(events, "worker.started")
    for position, doc in enumerate(range(WORKERS, 0, -1), start=1):
        name = f"batch1-worker{position}"
        [reused] = [e for e in of_type(events, "worker.reused") if e["assignment_id"] == name]
        body = payload(result["output_dir"], reused)
        assert (body["source_assignment_id"], body["document_id"]) == (
            f"batch1-worker{doc}", f"doc{doc}")
        assert result["worker_results"][name] == {
            **cache[f"batch1-worker{doc}"]["delivery"], "assignment_id": name}
    assert result["injected_faults"] == []


SECRET = "wp4-fixture-secret-value"


class SecretLead(ScriptedModel):
    """Prompts carry a value the Redactor scrubs from every logged payload."""

    suffix = f" Use token {SECRET}."


@pytest.mark.asyncio
async def test_lookup_hashes_the_redacted_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("WP4_FIXTURE_API_KEY", SECRET)
    clean = await execute(tmp_path, SecretLead(), name="clean")
    cache = selective.sibling_cache(clean["output_dir"], batch=1, exclude="none")
    # The cached digest is of the logged prompt, which never held the secret.
    redacted = prompt(1) + " Use token [REDACTED]."
    assert cache["batch1-worker1"]["assignment_digest"] == selective.assignment_digest(redacted)
    selective.write_cache(tmp_path / "cache.json", cache)
    result = await execute(tmp_path, SecretLead(),
                           tool_failure={"replay_cache_path": str(tmp_path / "cache.json")})
    events = read_events(result["output_dir"])
    assert sorted(e["assignment_id"] for e in of_type(events, "worker.reused")) == sorted(
        [*HEALTHY, FAULTED])
    assert not of_type(events, "worker.started")
