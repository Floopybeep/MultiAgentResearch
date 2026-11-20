"""Online delegation recovery: retry lost assignments, retrieve withheld results."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

import multi_agent_research.graphs.research as research
from multi_agent_research.config import RunConfig
from multi_agent_research.runner import run_qa
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3
ON = {"enabled": True}
OFF = {"enabled": False}
DROP = {"enabled": True, "num_delivered": 1}
TIMEOUT = {"enabled": True, "num_delivered": 1, "timeout_seconds": 0.05}


class ScriptedModel:
    """Turns follow each agent's message history; `failing` Workers raise on every call."""

    def __init__(self, failing=()):
        self.failing = set(failing)

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
                     {"prompt": f"Read doc{i} and report its value.", "document_id": f"doc{i}"})
                    for i in range(1, WORKERS + 1)
                ])
            return response(("submit_answer", {"answer": r"\boxed{42}"}))
        if agent in self.failing:
            raise RuntimeError("Simulated worker failure")
        document = f"doc{agent[-1]}"
        if turn == 1:
            return response(("read_document", {"document_id": document}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [document],
        }))


async def run(tmp_path, model=None, **settings):
    documents = OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])
    settings.setdefault("delegation_recovery", ON)
    config = RunConfig(output_dir=tmp_path / "runs", **settings)
    result = await run_qa("What is the value?", config, model or ScriptedModel(), documents,
                          reference_answer="42")
    return result, Path(result["output_dir"])


def events(run_dir, kind):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        found = [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]
    return [e for e in found if e["event_type"] == kind]


def payload(run_dir, event):
    return json.loads((Path(run_dir) / "artifacts" / f"{event['payload_ref']}.json").read_text())


def delivered(run_dir):
    return {e["assignment_id"]: payload(run_dir, e) for e in events(run_dir, "worker.delivered")}


def test_off_by_default_and_under_other_strategies():
    config = RunConfig()
    assert config.delegation_recovery.enabled is False
    assert config.strategy == "baseline"
    assert RunConfig(delegation_recovery=ON).strategy == "delegation-recovery"
    # Full restart and always verify always start from unrecovered faults.
    for other in ("full_restart", "always_verify"):
        assert RunConfig(**{other: True}).delegation_recovery.enabled is False
        assert RunConfig(delegation_recovery={"enabled": True},
                         **{other: True}).delegation_recovery.enabled is False
    with pytest.raises(ValidationError):
        RunConfig(delegation_recovery={"max_retries": -1})


@pytest.mark.asyncio
async def test_dropped_assignments_are_retried_in_place(tmp_path):
    result, run_dir = await run(tmp_path, connection_drop=DROP)
    assert result["status"] == "completed"
    assert len(events(run_dir, "connection.dropped")) == WORKERS - 1
    retried = events(run_dir, "delegation.retried")
    assert sorted(e["assignment_id"] for e in retried) == [
        f"batch1-worker{i}" for i in range(2, WORKERS + 1)
    ]
    # Every assignment reaches a Worker in the same batch; nothing is re-delegated.
    assert {k: v["status"] for k, v in delivered(run_dir).items()} == {
        f"batch1-worker{i}": "completed" for i in range(1, WORKERS + 1)
    }
    assert len(events(run_dir, "worker.finished")) == WORKERS
    assert not [e for e in events(run_dir, "delegation.result")
                if payload(run_dir, e).get("error")]


@pytest.mark.asyncio
async def test_persistent_drops_exhaust_retries(tmp_path):
    result, run_dir = await run(
        tmp_path, connection_drop={**DROP, "persistent": True},
        delegation_recovery={**ON, "max_retries": 2},
    )
    assert result["status"] == "completed"
    lost = WORKERS - 1
    assert len(events(run_dir, "connection.dropped")) == 3 * lost
    assert len(events(run_dir, "delegation.retried")) == 2 * lost
    errors = [payload(run_dir, e) for e in events(run_dir, "delegation.result")
              if payload(run_dir, e).get("error")]
    assert [e["error"] for e in errors] == ["ConnectionError"] * lost


@pytest.mark.asyncio
async def test_withheld_results_are_retrieved_without_rerunning(tmp_path):
    result, run_dir = await run(tmp_path, result_timeout=TIMEOUT)
    assert result["status"] == "completed"
    assert len(events(run_dir, "result.timed_out")) == WORKERS - 1
    retrieved = events(run_dir, "result.retrieved")
    assert len(retrieved) == WORKERS - 1
    finished = {e["event_id"]: e for e in events(run_dir, "worker.finished")}
    for event in retrieved:
        source = finished[payload(run_dir, event)["worker_finished_event"]]
        assert source["agent_id"] == event["assignment_id"]
    assert all(v["status"] == "completed" for v in delivered(run_dir).values())
    assert len(finished) == WORKERS


@pytest.mark.asyncio
async def test_failed_workers_are_not_retrieved(tmp_path):
    model = ScriptedModel(failing={"batch1-worker2"})
    _, run_dir = await run(tmp_path, model=model)
    assert not events(run_dir, "result.retrieved")
    assert delivered(run_dir)["batch1-worker2"]["status"] == "failed"


@pytest.mark.asyncio
async def test_clean_runs_never_trigger_recovery(tmp_path):
    result, run_dir = await run(tmp_path)
    assert result["status"] == "completed"
    assert not events(run_dir, "delegation.retried")
    assert not events(run_dir, "result.retrieved")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection_drop", "result_timeout"])
async def test_disabled_recovery_lets_faults_reach_the_lead(tmp_path, fault):
    settings = DROP if fault == "connection_drop" else TIMEOUT
    _, run_dir = await run(tmp_path, delegation_recovery=OFF, **{fault: settings})
    assert not events(run_dir, "delegation.retried")
    assert not events(run_dir, "result.retrieved")
    failed = [e for e in events(run_dir, "delegation.result")
              if payload(run_dir, e).get("error") or payload(run_dir, e).get("status") == "failed"]
    assert len(failed) == WORKERS - 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ConnectionError, TimeoutError])
async def test_transport_failure_before_worker_starts_is_retried(tmp_path, monkeypatch, error):
    original = research.run_worker
    calls = {}

    async def flaky(runtime, agent, *args, **kwargs):
        calls[agent] = calls.get(agent, 0) + 1
        if agent == "batch1-worker2" and calls[agent] == 1:
            raise error("Transport failed before worker started")
        return await original(runtime, agent, *args, **kwargs)

    monkeypatch.setattr(research, "run_worker", flaky)
    result, run_dir = await run(tmp_path)
    assert result["status"] == "completed"
    assert calls == {"batch1-worker1": 1, "batch1-worker2": 2, "batch1-worker3": 1}
    assert len(events(run_dir, "delegation.retried")) == 1
    assert not events(run_dir, "connection.dropped")
    assert all(value["status"] == "completed" for value in delivered(run_dir).values())


@pytest.mark.asyncio
@pytest.mark.parametrize("started,recovery,expected_calls", [
    (True, ON, 1), (False, OFF, 1),
    (False, {"enabled": True, "max_retries": 0}, 1),
    (False, {"enabled": True, "max_retries": 2}, 3),
])
async def test_transport_retries_respect_start_and_limit(
    tmp_path, monkeypatch, started, recovery, expected_calls,
):
    original = research.run_worker
    calls = 0

    async def disconnected(runtime, agent, *args, **kwargs):
        nonlocal calls
        if agent == "batch1-worker2":
            calls += 1
            if started:
                runtime.event("worker.started", agent, {})
            raise ConnectionError("Transport disconnected")
        return await original(runtime, agent, *args, **kwargs)

    monkeypatch.setattr(research, "run_worker", disconnected)
    _, run_dir = await run(tmp_path, delegation_recovery=recovery)
    assert calls == expected_calls
    assert len(events(run_dir, "delegation.retried")) == expected_calls - 1
    errors = [payload(run_dir, e) for e in events(run_dir, "delegation.result")
              if payload(run_dir, e).get("error")]
    assert len(errors) == 1 and errors[0]["error"] == "ConnectionError"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_summary_separates_recovery_and_counts_only_discarded_work(tmp_path, enabled):
    spec = importlib.util.spec_from_file_location(
        "delegation_summary",
        Path(__file__).resolve().parents[2] / "eval/delegation_faults/summarize.py",
    )
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)
    result, run_dir = await run(
        tmp_path, result_timeout=TIMEOUT, delegation_recovery={"enabled": enabled},
    )
    expected = "delegation-recovery" if enabled else "baseline"
    assert result["strategy"] == expected
    # Historical online runs used the baseline label: their config must disambiguate it.
    result = {**result, "question_id": "1", "strategy": "baseline"}
    row = summary.summarize_result(run_dir.parent, result)
    assert row["strategy"] == expected
    assert row["wasted_tokens"] == (0 if enabled else 60)
    assert row["wasted_worker_tokens"] == row["wasted_tokens"]
    assert bool(summary.no_recovery_rows([row])) is not enabled
