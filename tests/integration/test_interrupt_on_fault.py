"""WP2: tool_failure.interrupt_on_fault stops the run at the faulted batch (ScriptedModel only)."""

import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from multi_agent_research import selective
from multi_agent_research.config import RunConfig, ToolFailureConfig
from multi_agent_research.runner import run_qa
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

WORKERS = 3
FAULTED = "batch1-worker2"
HEALTHY = ["batch1-worker1", "batch1-worker3"]


class ScriptedModel:
    """Workers read until one read succeeds, then complete; the Lead delegates once."""

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


def tool_fault(mode="immediate", **extra):
    # One transient denial of doc2, so exactly one tool.failure_injected in batch 1.
    return {"enabled": True, "mode": mode, "document_ids": ["doc2"],
            "max_failures": 1, "persistent": False, **extra}


async def execute(tmp_path, **settings):
    config = RunConfig(output_dir=tmp_path / "runs", call_timeout_seconds=0.05, **settings)
    return await run_qa("What is the value?", config, ScriptedModel(), documents(),
                        reference_answer="42")


def read_events(run_dir):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        return [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]


def kinds(result):
    return [f["event_type"] for f in result["injected_faults"]]


# T1
def test_interrupt_on_fault_config():
    assert ToolFailureConfig().interrupt_on_fault == "never"
    assert RunConfig.load("configs/baseline.yaml").tool_failure.interrupt_on_fault == "never"
    smoke = RunConfig.load("configs/faults-tool-read-denial.yaml").tool_failure
    assert smoke.interrupt_on_fault == "never"
    assert ToolFailureConfig(interrupt_on_fault="batch").interrupt_on_fault == "batch"
    with pytest.raises(ValidationError):
        ToolFailureConfig(interrupt_on_fault="worker")
    with pytest.raises(ValidationError):
        ToolFailureConfig(not_a_field=True)


# T2
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["immediate", "timeout"])
async def test_batch_interrupt_stops_before_the_lead_reassesses(tmp_path, mode):
    result = await execute(tmp_path, always_verify=False,
                           tool_failure=tool_fault(mode, interrupt_on_fault="batch"))
    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "fault_injected"
    assert kinds(result) == ["tool.failure_injected"]
    assert result["injected_faults"][0]["agent"] == FAULTED
    for agent in HEALTHY:
        assert result["worker_results"][agent]["status"] == "completed"
    events = read_events(result["output_dir"])
    delivered = {e["assignment_id"] for e in events if e["event_type"] == "worker.delivered"}
    assert set(HEALTHY) <= delivered
    # One batch, no answer, and the Lead made only its plan and delegation calls.
    assert {e.get("batch_id") for e in events if e["event_type"] == "delegation.request"} == {1}
    assert result["answer"] is None
    assert not [e for e in events if e["event_type"] == "answer.submitted"]
    lead_calls = [e for e in events
                  if e["event_type"] == "model.request" and e["agent_id"] == "lead"]
    assert len(lead_calls) == 2
    # Expected interactions: no in-process restart; graded as not_answered.
    assert result["restarted"] is False and len(result["attempts"]) == 1
    assert result["grade"]["method"] == "not_answered"


# T3
@pytest.mark.asyncio
async def test_other_fault_classes_do_not_interrupt(tmp_path):
    result = await execute(
        tmp_path,
        tool_failure={"enabled": False, "interrupt_on_fault": "batch"},
        connection_drop={"enabled": True, "num_delivered": 1},
    )
    # The run-global list holds a teammate's fault, yet the run continues to an answer.
    assert "connection.dropped" in kinds(result)
    assert "tool.failure_injected" not in kinds(result)
    assert result["status"] == "completed"
    assert result["stop_reason"] == "submit_answer"
    assert result["answer"] == "{42}"


# T4
@pytest.mark.asyncio
async def test_never_leaves_a_tool_fault_run_uninterrupted(tmp_path):
    result = await execute(tmp_path, tool_failure=tool_fault())
    assert kinds(result) == ["tool.failure_injected"]
    assert result["status"] == "completed"
    assert result["stop_reason"] == "submit_answer"
    assert result["answer"] == "{42}"
    assert result["restarted"] is False


# T5
@pytest.mark.asyncio
async def test_full_restart_is_unchanged(tmp_path):
    result = await execute(tmp_path, full_restart=True, tool_failure=tool_fault())
    first, second = result["attempts"]
    assert first["config"]["tool_failure"]["interrupt_on_fault"] == "never"
    assert first["status"] == "interrupted"
    assert first["stop_reason"] == "fault_injected"
    assert result["restarted"] is True
    assert result["restart_reason"] == "fault_injected"
    assert second["status"] == "completed" and not second["fault_injected"]


# T6
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["immediate", "timeout"])
async def test_interrupted_attempt_feeds_selective_recovery(tmp_path, mode):
    result = await execute(tmp_path, always_verify=False,
                           tool_failure=tool_fault(mode, interrupt_on_fault="batch"))
    assert result["status"] == "interrupted"
    # The attempt directory itself, never a recover() branch.
    attempt = Path(result["output_dir"])
    sites = selective.find_tool_fault_sites(attempt)
    assert len(sites) == 1
    assert sites[0]["agent_id"] == FAULTED
    assert sites[0]["recovery_point_id"]
    cache = selective.sibling_cache(attempt, batch=1, exclude=FAULTED)
    assert sorted(cache) == HEALTHY
