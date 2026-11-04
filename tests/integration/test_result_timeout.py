"""Worker-to-Lead result timeouts with scripted model calls."""

import asyncio
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from multi_agent_research.config import ResultTimeoutConfig, RunConfig
from multi_agent_research.runner import run_qa
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3
TIMEOUT = 2.0
SLOW = 1.0


@pytest.mark.parametrize("settings", [{"timeout_seconds": 0}, {"unknown": 1}])
def test_invalid_config(settings):
    with pytest.raises(ValidationError):
        ResultTimeoutConfig(**settings)


def test_default_deadline_matches_worker_timeout():
    config = RunConfig()
    assert config.result_timeout.timeout_seconds == config.worker_timeout_seconds == 180
    with pytest.raises(ValidationError):
        RunConfig(worker_timeout_seconds=60, result_timeout={"enabled": True, "timeout_seconds": 61})


def test_only_one_delegation_fault():
    with pytest.raises(ValidationError):
        RunConfig(connection_drop={"enabled": True}, result_timeout={"enabled": True})


def usage():
    return {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class ScriptedModel:
    """Lead delegates three assignments, then submits; failing Workers never complete."""

    def __init__(self, failing=(), slow=()):
        self.turns = defaultdict(int)
        self.workers = []
        self.failing = set(failing)
        self.slow = dict(slow)

    def lead(self, agent, turn):
        if turn == 1:
            return [("memory_write", {"plan": "Read every document."})]
        if turn == 2:
            return [
                ("run_blocking_subagent", {"prompt": f"Read doc{i} and report its value.", "document_id": f"doc{i}"})
                for i in range(1, WORKERS + 1)
            ]
        return [("submit_answer", {"answer": r"\boxed{42}"})]

    async def invoke(self, role, agent, messages, tools, config):
        self.turns[agent] += 1
        turn = self.turns[agent]

        def response(calls):
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
                for i, (name, args) in enumerate(calls)
            ], usage_metadata=usage())

        if role == "judge":
            return AIMessage(content='{"correct": true, "reason": "Scripted decision"}')
        if role == "lead":
            return response(self.lead(agent, turn))
        doc = f"doc{agent[-1]}"
        if agent in self.failing:
            raise RuntimeError("Simulated worker failure")
        if turn == 1:
            self.workers.append(agent)
            await asyncio.sleep(self.slow.get(agent, 0))
            return response([("read_document", {"document_id": doc})])
        return response([("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [doc],
        })])


class RetryingModel(ScriptedModel):
    """Lead retries two assignments in a second batch before submitting."""

    def lead(self, agent, turn):
        if turn == 3:
            return [("run_blocking_subagent", {"prompt": f"Retry doc{i}.", "document_id": f"doc{i}"}) for i in (1, 2)]
        return super().lead(agent, turn if turn < 3 else turn - 1)


async def execute(tmp_path, model=None, **timeout):
    documents = OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])
    model = model or ScriptedModel()
    settings = {"timeout_seconds": TIMEOUT, **timeout}
    config = RunConfig(output_dir=tmp_path, result_timeout=settings)
    result = await run_qa(
        "What is the value?", config, model, documents, reference_answer="42"
    )
    root = Path(result["output_dir"])
    with sqlite3.connect(root / "events.sqlite") as db:
        events = [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]

    def payload(event):
        return json.loads((root / "artifacts" / f"{event['payload_ref']}.json").read_text())

    def artifact(ref):
        return json.loads((root / "artifacts" / f"{ref}.json").read_text())

    return result, model, events, payload, artifact


def of_type(events, kind):
    return [e for e in events if e["event_type"] == kind]


@pytest.mark.asyncio
async def test_two_of_three_results_time_out(tmp_path):
    result, model, events, payload, artifact = await execute(
        tmp_path, enabled=True, num_delivered=1
    )
    assert result["status"] == "completed"
    assert sorted(model.workers) == [f"batch1-worker{i}" for i in range(1, WORKERS + 1)]
    finished = {e["event_id"]: e for e in of_type(events, "worker.finished")}
    assert len(finished) == WORKERS

    timed_out = of_type(events, "result.timed_out")
    assert [e["assignment_id"] for e in timed_out] == ["batch1-worker2", "batch1-worker3"]
    for event in timed_out:
        (parent,) = event["parent_event_ids"]
        assert finished[parent]["agent_id"] == event["assignment_id"]
        body = payload(event)
        assert body["timeout_seconds"] == TIMEOUT and body["late"] is False
        assert body["worker_status"] == "completed"
        withheld = artifact(body["original_result_ref"])
        assert withheld["status"] == "completed" and withheld["findings"]
        assert withheld == payload(finished[parent])

    # The Lead receives the same failed result as a natural worker timeout.
    delivered = {e["assignment_id"]: payload(e) for e in of_type(events, "worker.delivered")}
    assert delivered["batch1-worker1"]["status"] == "completed"
    for agent in ("batch1-worker2", "batch1-worker3"):
        assert delivered[agent]["status"] == "failed"
        assert delivered[agent]["stop_reason"] == "TimeoutError: "
        assert delivered[agent]["findings"] == ""
    results = [payload(e) for e in of_type(events, "delegation.result")]
    assert not [r for r in results if "error" in r]
    assert result["worker_results"]["batch1-worker2"]["status"] == "failed"


@pytest.mark.asyncio
async def test_deadline_is_counted_from_dispatch(tmp_path):
    model = ScriptedModel(slow={"batch1-worker3": SLOW})
    _, _, events, payload, _ = await execute(tmp_path, model, enabled=True, num_delivered=1)
    durations = {
        payload(e)["assignment_id"]: e["duration_seconds"]
        for e in of_type(events, "delegation.result")
    }
    for agent in ("batch1-worker2", "batch1-worker3"):
        # Counted from dispatch, not from worker completion (which would add SLOW).
        assert TIMEOUT <= durations[agent] < TIMEOUT + SLOW * 0.8


@pytest.mark.asyncio
async def test_late_worker_times_out_on_completion(tmp_path):
    model = ScriptedModel(slow={"batch1-worker3": SLOW})
    _, _, events, payload, _ = await execute(
        tmp_path, model, enabled=True, num_delivered=2, timeout_seconds=SLOW / 3
    )
    (event,) = of_type(events, "result.timed_out")
    assert event["assignment_id"] == "batch1-worker3" and payload(event)["late"] is True


@pytest.mark.asyncio
async def test_failed_worker_is_still_timed_out(tmp_path):
    model = ScriptedModel(failing={"batch1-worker3"})
    _, _, events, payload, artifact = await execute(
        tmp_path, model, enabled=True, num_delivered=1
    )
    timed_out = {e["assignment_id"]: payload(e) for e in of_type(events, "result.timed_out")}
    assert set(timed_out) == {"batch1-worker2", "batch1-worker3"}
    assert timed_out["batch1-worker2"]["worker_status"] == "completed"
    assert timed_out["batch1-worker3"]["worker_status"] == "failed"
    withheld = artifact(timed_out["batch1-worker3"]["original_result_ref"])
    assert withheld["stop_reason"].startswith("RuntimeError")
    delivered = {e["assignment_id"]: payload(e) for e in of_type(events, "worker.delivered")}
    assert delivered["batch1-worker3"]["stop_reason"] == "TimeoutError: "


@pytest.mark.asyncio
async def test_disabled_is_baseline(tmp_path):
    _, model, events, payload, _ = await execute(tmp_path)
    assert len(model.workers) == WORKERS
    assert not of_type(events, "result.timed_out")
    assert all(payload(e)["status"] == "completed" for e in of_type(events, "worker.delivered"))


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent, timeouts", [(False, 0), (True, 1)])
async def test_retry_timeouts_depend_on_persistent(tmp_path, persistent, timeouts):
    _, _, events, _, _ = await execute(
        tmp_path, RetryingModel(), enabled=True, num_delivered=1, persistent=persistent
    )
    second = [e for e in of_type(events, "result.timed_out") if e.get("batch_id") == 2]
    assert len(second) == timeouts
