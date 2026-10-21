import asyncio
import json
import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from multi_agent_research.config import RunConfig
from multi_agent_research.demo import DemoFetcher, DemoModel, DemoSearch, call
from multi_agent_research.runner import run_research


async def execute(tmp_path, model=None, **kwargs):
    return await run_research(
        "Compare the topics",
        RunConfig(output_dir=tmp_path, **kwargs),
        model or DemoModel(),
        DemoSearch(),
        DemoFetcher(),
    )


def events(result):
    with sqlite3.connect(Path(result["output_dir"]) / "events.sqlite") as db:
        return [
            json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY sequence")
        ]


async def test_two_round_pipeline_and_audit(tmp_path):
    result = await execute(tmp_path)
    assert result["status"] == "completed"
    assert set(result["worker_results"]) == {"batch1-worker1", "batch1-worker2", "batch2-worker1"}
    assert result["usage"]["model_calls"] == 14
    assert result["checkpoint_id"]
    assert "[[cite:" in Path(result["report_path"]).read_text()
    log = events(result)
    ids = {event["event_id"] for event in log}
    assert all(set(event["parent_event_ids"]) <= ids for event in log)
    root = Path(result["output_dir"])
    assert all((root / "artifacts" / (e["payload_ref"] + ".json")).exists() for e in log)
    with sqlite3.connect(root / "checkpoints.sqlite") as db:
        threads = {r[0] for r in db.execute("SELECT DISTINCT thread_id FROM checkpoints")}
    assert len(threads) == 4
    assert any(e["event_type"] == "citation.validated" for e in log)


async def test_workers_are_parallel_and_isolated(tmp_path):
    class InspectModel(DemoModel):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.peak = 0
            self.seen = {}

        async def invoke(self, role, agent_id, messages, tools, config):
            if role == "worker" and agent_id not in self.turns:
                self.seen[agent_id] = [m.content for m in messages if isinstance(m, HumanMessage)]
                self.active += 1
                self.peak = max(self.peak, self.active)
                await asyncio.sleep(0.03)
                self.active -= 1
            return await super().invoke(role, agent_id, messages, tools, config)

    model = InspectModel()
    result = await execute(tmp_path, model)
    assert result["status"] == "completed"
    assert model.peak == 2
    assert model.seen["batch1-worker1"] == ["Research alpha. Fetch the source."]
    assert model.seen["batch1-worker2"] == ["Research beta. Fetch the source."]


async def test_failed_worker_does_not_erase_siblings(tmp_path):
    class FailingModel(DemoModel):
        async def invoke(self, role, agent_id, messages, tools, config):
            if agent_id == "batch1-worker2":
                raise RuntimeError("fixture failure")
            return await super().invoke(role, agent_id, messages, tools, config)

    result = await execute(tmp_path, FailingModel())
    assert result["status"] == "completed"
    assert result["worker_results"]["batch1-worker1"]["status"] == "completed"
    assert result["worker_results"]["batch1-worker2"]["status"] == "failed"
    assert any(e["event_type"] == "model.error" for e in events(result))


async def test_timeout_returns_terminal_worker_result(tmp_path):
    class SlowModel(DemoModel):
        async def invoke(self, role, agent_id, messages, tools, config):
            if agent_id == "batch1-worker2":
                await asyncio.sleep(10)
            return await super().invoke(role, agent_id, messages, tools, config)

    # Leave headroom for real checkpoint/artifact I/O; the slow worker still sleeps 10s.
    result = await execute(tmp_path, SlowModel(), worker_timeout_seconds=1.0)
    assert result["worker_results"]["batch1-worker2"]["status"] == "failed"
    assert "TimeoutError" in result["worker_results"]["batch1-worker2"]["stop_reason"]
    assert result["worker_results"]["batch1-worker1"]["status"] == "completed"


async def test_lead_budget_and_token_budget(tmp_path):
    result = await execute(tmp_path, max_lead_turns=1)
    assert result["status"] == "budget_exhausted"
    assert result["stop_reason"] == "lead_turn_limit"
    assert "report_path" not in result
    result = await execute(tmp_path, max_run_tokens=1)
    assert result["stop_reason"] == "run_token_budget"


async def test_citation_rewrite_fails_without_publishing(tmp_path):
    class BadCitation(DemoModel):
        async def invoke(self, role, agent_id, messages, tools, config):
            if role == "citation":
                return AIMessage(content="An invented report.")
            return await super().invoke(role, agent_id, messages, tools, config)

    result = await execute(tmp_path, BadCitation())
    assert result["status"] == "failed"
    assert "report_path" not in result
    assert Path(result["draft_path"]).exists()


async def test_invalid_tool_args_are_observations(tmp_path):
    class BadTool(DemoModel):
        async def invoke(self, role, agent_id, messages, tools, config):
            if role == "worker" and agent_id not in self.turns:
                self.turns[agent_id] = 0
                return AIMessage(
                    content="", tool_calls=[call("web_fetch", {"wrong": "value"}, "bad")]
                )
            return await super().invoke(role, agent_id, messages, tools, config)

    result = await execute(tmp_path, BadTool())
    assert result["status"] == "completed"
    assert any(e["event_type"] == "tool.error" for e in events(result))


async def test_citation_input_cap(tmp_path):
    result = await execute(tmp_path, max_citation_chars=1)
    assert result["status"] == "budget_exhausted"
    assert result["stop_reason"] == "citation_input_limit"


async def test_worker_budget_is_not_success(tmp_path):
    result = await execute(tmp_path, max_worker_turns=1, max_lead_turns=6)
    assert result["status"] != "completed"
    assert all(r["status"] == "budget_exhausted" for r in result["worker_results"].values())


async def test_run_timeout_is_bounded(tmp_path):
    class SlowLead(DemoModel):
        async def invoke(self, role, agent_id, messages, tools, config):
            await asyncio.sleep(10)

    result = await execute(tmp_path, SlowLead(), run_timeout_seconds=0.1)
    assert result["status"] == "budget_exhausted"
    assert result["stop_reason"] == "run_timeout"


async def test_overflow_workers_are_not_started(tmp_path):
    result = await execute(tmp_path, max_workers_per_batch=1)
    assert result["status"] == "completed"
    assert set(result["worker_results"]) == {"batch1-worker1", "batch2-worker1"}


async def test_completion_requires_a_worker(tmp_path):
    class Premature(DemoModel):
        async def invoke(self, role, agent_id, messages, tools, config):
            return AIMessage(
                content="", tool_calls=[call("complete_task", {"report": "Unsupported."}, 0)]
            )

    result = await execute(tmp_path, Premature(), max_lead_turns=2)
    assert result["status"] == "budget_exhausted"
    assert "report_path" not in result
