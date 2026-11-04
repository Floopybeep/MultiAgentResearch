"""Lead-to-Worker connection drops with scripted model calls."""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from multi_agent_research.config import ConnectionDropConfig, RunConfig
from multi_agent_research.runner import run_qa
from multi_agent_research.tools.connection_drop import select_dropped
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3


@pytest.mark.parametrize(
    "settings, batch, dispatched, expected",
    [
        ({}, 1, 3, []),
        ({"enabled": True}, 1, 3, [1, 2]),
        ({"enabled": True, "num_delivered": 0}, 1, 3, [0, 1, 2]),
        ({"enabled": True, "num_delivered": 3}, 1, 3, []),
        ({"enabled": True, "num_delivered": 5}, 1, 3, []),
        ({"enabled": True}, 2, 3, []),
        ({"enabled": True, "persistent": True}, 2, 3, [1, 2]),
        ({"enabled": True, "batch": 2}, 1, 3, []),
        ({"enabled": True, "batch": 2}, 2, 3, [1, 2]),
        ({"enabled": True}, 1, 0, []),
    ],
)
def test_select_dropped(settings, batch, dispatched, expected):
    assert select_dropped(ConnectionDropConfig(**settings), batch, dispatched) == expected


def test_random_selection_is_seeded():
    config = ConnectionDropConfig(enabled=True, select="random", seed=7)
    first = select_dropped(config, 1, 4)
    assert len(first) == 3 and first == sorted(first)
    assert select_dropped(config, 1, 4) == first


@pytest.mark.parametrize(
    "settings", [{"batch": 0}, {"num_delivered": -1}, {"select": "first"}, {"unknown": 1}]
)
def test_invalid_config(settings):
    with pytest.raises(ValidationError):
        ConnectionDropConfig(**settings)


class ScriptedModel:
    """Lead delegates three assignments, then submits once results return."""

    def __init__(self):
        self.turns = defaultdict(int)
        self.workers = []

    async def invoke(self, role, agent, messages, tools, config):
        self.turns[agent] += 1
        turn = self.turns[agent]

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
                    ("run_blocking_subagent", {"prompt": f"Read doc{i} and report its value."})
                    for i in range(1, WORKERS + 1)
                ])
            return response(("submit_answer", {"answer": "{42}"}))
        if turn == 1:
            self.workers.append(agent)
            return response(("read_document", {"document_id": f"doc{agent[-1]}"}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [f"doc{agent[-1]}"],
        }))


async def execute(tmp_path, model_cls=None, **drop):
    documents = OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])
    model = (model_cls or ScriptedModel)()
    config = RunConfig(output_dir=tmp_path, connection_drop=drop)
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

    return result, model, events, payload


@pytest.mark.asyncio
async def test_drop_two_of_three(tmp_path):
    result, model, events, payload = await execute(tmp_path, enabled=True, num_delivered=1)
    assert result["status"] == "completed"
    assert model.workers == ["batch1-worker1"]

    dropped = [e for e in events if e["event_type"] == "connection.dropped"]
    assert [e["assignment_id"] for e in dropped] == ["batch1-worker2", "batch1-worker3"]
    requests = {e["event_id"]: e for e in events if e["event_type"] == "delegation.request"}
    for event in dropped:
        (parent,) = event["parent_event_ids"]
        assert parent in requests
        assert payload(event)["assignment"].startswith("Read doc")

    errors = [
        payload(e) for e in events
        if e["event_type"] == "delegation.result" and "error" in payload(e)
    ]
    assert len(errors) == 2
    assert {e["error"] for e in errors} == {"ConnectionError"}
    started = [e["agent_id"] for e in events if e["event_type"] == "worker.started"]
    assert started == ["batch1-worker1"]


@pytest.mark.asyncio
async def test_disabled_is_baseline(tmp_path):
    _, model, events, _ = await execute(tmp_path)
    assert sorted(model.workers) == [f"batch1-worker{i}" for i in range(1, WORKERS + 1)]
    assert not [e for e in events if e["event_type"].startswith("connection.")]


@pytest.mark.asyncio
async def test_nothing_to_drop(tmp_path):
    _, model, events, _ = await execute(tmp_path, enabled=True, num_delivered=WORKERS)
    assert len(model.workers) == WORKERS
    assert not [e for e in events if e["event_type"] == "connection.dropped"]


class RetryingModel(ScriptedModel):
    """Lead retries in a second batch, then submits."""

    async def invoke(self, role, agent, messages, tools, config):
        if role == "lead" and self.turns[agent] == 2:
            self.turns[agent] += 1
            return AIMessage(content="", tool_calls=[
                {"name": "run_blocking_subagent", "args": {"prompt": f"Retry doc{i}."},
                 "id": f"lead-retry-{i}"}
                for i in (2, 3)
            ], usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        return await super().invoke(role, agent, messages, tools, config)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent, retried", [(False, 2), (True, 1)])
async def test_retry_delivery_depends_on_persistent(tmp_path, persistent, retried):
    _, model, events, _ = await execute(
        tmp_path, RetryingModel, enabled=True, num_delivered=1, persistent=persistent
    )
    second = [w for w in model.workers if w.startswith("batch2-")]
    assert len(second) == retried
    dropped = [e for e in events if e["event_type"] == "connection.dropped"]
    assert len(dropped) == 2 + (2 - retried)
