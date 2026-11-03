"""QA orchestration checks with scripted model calls and temporary local documents."""

import asyncio
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from multi_agent_research.config import RunConfig
from multi_agent_research.runner import run_qa
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

pytestmark = pytest.mark.asyncio


class ScriptedModel:
    def __init__(self, *, fail_worker=False, judge_error=False):
        self.turns = defaultdict(int)
        self.requests = []
        self.active = self.peak = 0
        self.fail_worker = fail_worker
        self.judge_error = judge_error

    async def invoke(self, role, agent, messages, tools, config):
        self.requests.append((role, agent, list(messages)))
        self.turns[agent] += 1
        turn = self.turns[agent]

        def response(*calls):
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
                for i, (name, args) in enumerate(calls)
            ], usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

        if role == "judge":
            if self.judge_error:
                raise RuntimeError("Simulated judge failure")
            return AIMessage(content='{"correct": false, "reason": "Scripted decision"}')
        if role == "lead":
            if turn == 1:
                return response(("memory_write", {"plan": "Read both documents independently."}))
            if turn == 2:
                return response(*[
                    ("run_blocking_subagent", {"prompt": f"Read doc{i} and report its value."})
                    for i in (1, 2)
                ])
            return response(("submit_answer", {"answer": "{42}"}))
        assert role == "worker"
        doc = "doc1" if agent.endswith("worker1") else "doc2"
        if turn == 1:
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.02)
                if self.fail_worker and doc == "doc2":
                    raise RuntimeError("Simulated worker failure")
            finally:
                self.active -= 1
            return response(("read_document", {"document_id": doc}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [doc],
        }))


async def execute(tmp_path, model=None, reference="42", **limits):
    documents = OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in (1, 2)
    ])
    return await run_qa(
        "What is the value?", RunConfig(output_dir=tmp_path, **limits),
        model or ScriptedModel(), documents, reference_answer=reference,
    )


async def test_qa_parallel_workers_and_audit(tmp_path):
    model = ScriptedModel()
    result = await execute(tmp_path, model)
    assert result["status"] == "completed"
    assert result["grade"]["method"] == "exact_match"
    assert result["grade"]["correct"] is True
    assert result["usage"]["model_calls"] == 7
    assert model.peak == 2
    assert list(result["worker_results"]) == ["batch1-worker1", "batch1-worker2"]
    assert all(r["status"] == "completed" for r in result["worker_results"].values())
    for role, agent, messages in model.requests:
        assert "{{." not in messages[0].content
        if role == "worker":
            payload = json.loads(messages[1].content)
            number = agent[-1]
            assert payload["assignment"] == f"Read doc{number} and report its value."
            assert {d["document_id"] for d in payload["available_documents"]} == {"doc1", "doc2"}
            assert "reference_answer" not in payload
    root = Path(result["output_dir"])
    assert Path(result["answer_path"]).read_text() == "{42}"
    assert json.loads((root / "run.json").read_text())["status"] == "completed"
    assert len(json.loads((root / "documents.json").read_text())) == 2
    assert (root / "viewer-data.js").is_file()
    with sqlite3.connect(root / "events.sqlite") as db:
        events = [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY sequence")]
        records = {k: json.loads(v) for k, v in db.execute("SELECT key, body FROM records")}
    assert set(records["prompts"]) == {"lead", "worker", "judge"}
    ids = {e["event_id"] for e in events}
    assert all(set(e["parent_event_ids"]) <= ids for e in events)
    assert all((root / "artifacts" / (e["payload_ref"] + ".json")).is_file() for e in events)
    kinds = [e["event_type"] for e in events]
    assert kinds.index("answer.submitted") < kinds.index("grade.started")
    with sqlite3.connect(root / "checkpoints.sqlite") as db:
        assert len(db.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()) == 3
    assert result["checkpoint_id"]


@pytest.mark.parametrize("judge_error", [False, True])
async def test_qa_judge_path(tmp_path, judge_error):
    model = ScriptedModel(judge_error=judge_error)
    result = await execute(tmp_path, model, reference="Different reference")
    assert result["status"] == "completed"
    assert result["grade"]["method"] == ("judge_error" if judge_error else "llm_judge")
    assert result["grade"]["correct"] is (None if judge_error else False)
    judge_requests = [messages for role, _, messages in model.requests if role == "judge"]
    assert len(judge_requests) == 1
    assert json.loads(judge_requests[0][1].content)["reference_answer"] == "Different reference"
    assert all("Different reference" not in str(messages)
               for role, _, messages in model.requests if role != "judge")


async def test_qa_failed_worker_preserves_sibling(tmp_path):
    result = await execute(tmp_path, ScriptedModel(fail_worker=True))
    assert result["status"] == "completed"
    assert result["worker_results"]["batch1-worker1"]["status"] == "completed"
    assert result["worker_results"]["batch1-worker2"]["status"] == "failed"


@pytest.mark.parametrize("limits,reason", [
    ({"max_lead_turns": 1}, "lead_turn_limit"),
    ({"max_run_tokens": 1}, "run_token_budget"),
    ({"max_worker_turns": 1, "max_lead_turns": 3}, "lead_turn_limit"),
    ({"max_worker_tool_calls": 1, "max_lead_turns": 3}, "lead_turn_limit"),
])
async def test_qa_budget_failure_does_not_publish_answer(tmp_path, limits, reason):
    result = await execute(tmp_path, **limits)
    assert result["status"] == "budget_exhausted"
    assert result["stop_reason"] == reason
    assert "answer_path" not in result
    assert result["grade"]["method"] == "not_answered"
    if "max_worker_turns" in limits or "max_worker_tool_calls" in limits:
        assert len(result["worker_results"]) == 2
        assert all(r["status"] == "budget_exhausted" for r in result["worker_results"].values())
