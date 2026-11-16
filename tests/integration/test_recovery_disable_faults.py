"""Replaying a delegation checkpoint with and without faults disabled."""

import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from multi_agent_research.config import RunConfig
from multi_agent_research.recovery import recover
from multi_agent_research.runner import run_qa
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3
FAULTS = {
    "connection_drop": ({"enabled": True, "num_delivered": 1}, "connection.dropped"),
    "result_timeout": (
        {"enabled": True, "num_delivered": 1, "timeout_seconds": 0.05}, "result.timed_out",
    ),
}


class ScriptedModel:
    """Turns follow the agent's own message history, so replays behave like live runs."""

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
            return response(("submit_answer", {"answer": "{42}"}))
        document = f"doc{agent[-1]}"
        if turn == 1:
            return response(("read_document", {"document_id": document}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [document],
        }))


def read_events(run_dir):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        return [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]


def after_recovery_start(events):
    start = next(i for i, e in enumerate(events) if e["event_type"] == "recovery.started")
    return events[start:]


async def faulted_attempt(tmp_path, fault):
    settings, _ = FAULTS[fault]
    documents = OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])
    config = RunConfig(output_dir=tmp_path / "runs", **{fault: settings})
    result = await run_qa(
        "What is the value?", config, ScriptedModel(), documents, reference_answer="42"
    )
    attempt = Path(result["output_dir"])
    # The faulted batch's delegation calls all point to the same pre-batch checkpoint.
    point = next(
        e["recovery_point_id"] for e in read_events(attempt)
        if e["event_type"] == "delegation.request" and e.get("batch_id") == 1
    )
    return attempt, point


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", sorted(FAULTS))
async def test_disable_faults_replays_the_batch_cleanly(tmp_path, fault):
    attempt, point = await faulted_attempt(tmp_path, fault)
    _, injection = FAULTS[fault]
    assert sum(e["event_type"] == injection for e in read_events(attempt)) == WORKERS - 1

    result = await recover(attempt, point, model=ScriptedModel(),
                           output_dir=tmp_path / "replay", disable_faults=True)
    assert result["status"] == "completed" and result["faults_disabled"] is True
    replayed = after_recovery_start(read_events(tmp_path / "replay"))
    assert not [e for e in replayed if e["event_type"] == injection]
    delivered = [e for e in replayed if e["event_type"] == "worker.delivered"]
    assert sorted(e["assignment_id"] for e in delivered) == [
        f"batch1-worker{i}" for i in range(1, WORKERS + 1)
    ]
    assert replayed[0]["event_type"] == "recovery.started"
    started = json.loads(
        (tmp_path / "replay" / "artifacts" / f"{replayed[0]['payload_ref']}.json").read_text()
    )
    assert started["faults_disabled"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", sorted(FAULTS))
async def test_default_replay_reinjects_the_same_fault(tmp_path, fault):
    attempt, point = await faulted_attempt(tmp_path, fault)
    _, injection = FAULTS[fault]
    result = await recover(attempt, point, model=ScriptedModel(), output_dir=tmp_path / "replay")
    assert result["faults_disabled"] is False
    replayed = after_recovery_start(read_events(tmp_path / "replay"))
    assert sum(e["event_type"] == injection for e in replayed) == WORKERS - 1


@pytest.mark.asyncio
async def test_source_attempt_is_unchanged(tmp_path):
    attempt, point = await faulted_attempt(tmp_path, "connection_drop")
    before = (attempt / "events.sqlite").read_bytes()
    await recover(attempt, point, model=ScriptedModel(), output_dir=tmp_path / "replay",
                  disable_faults=True)
    assert (attempt / "events.sqlite").read_bytes() == before
