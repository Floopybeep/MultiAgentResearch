"""Pipeline boundary regression tests, using the existing scripted graph fixture."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from test_qa_pipeline import ScriptedModel, execute

from multi_agent_research.config import PipelineFaultConfig, RunConfig
from multi_agent_research.faults.pipeline import PipelineFaultInjector
from multi_agent_research.storage.artifacts import ArtifactStore


def events(result):
    root = Path(result["output_dir"])
    with sqlite3.connect(root / "events.sqlite") as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT body FROM events ORDER BY sequence")]
    return [(e, json.loads((root / "artifacts" / (e["payload_ref"] + ".json")).read_text()))
            for e in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,error,executed", [
    ("dropped_result", "InjectedDroppedWorkerResult", True),
    ("dispatch_failure", "InjectedWorkerDispatchFailure", False),
    ("timeout", "InjectedCommunicationTimeout", True),
])
async def test_fault_boundary(tmp_path, kind, error, executed):
    class DistinctFindingsModel(ScriptedModel):
        async def invoke(self, role, agent, messages, tools, config):
            response = await super().invoke(role, agent, messages, tools, config)
            if role == "worker":
                for call in response.tool_calls:
                    if call["name"] == "complete_task":
                        call["args"]["findings"] = f"Private findings from {agent}"
            return response

    model = DistinctFindingsModel()
    result = await execute(tmp_path, model, pipeline_fault={
        "enabled": True, "fault_type": kind, "assignment_ids": ["batch1-worker1"],
    })
    assert result["status"] == "completed"
    workers = result["worker_results"]
    assert list(workers) == ["batch1-worker1", "batch1-worker2"]
    assert workers["batch1-worker1"]["stop_reason"] == error
    assert workers["batch1-worker1"]["findings"] == ""
    assert workers["batch1-worker1"]["document_ids"] == []
    assert workers["batch1-worker2"]["status"] == "completed"
    assert any(a == "batch1-worker1" for _, a, _ in model.requests) is executed
    assert model.active == 0
    if executed:
        assert model.peak == 2
    audit = events(result)
    injected = [(e, p) for e, p in audit if e["event_type"] == "fault.injected"]
    assert len(injected) == 1
    event, payload = injected[0]
    assert event["assignment_id"] == "batch1-worker1"
    assert event["batch_id"] == 1
    assert payload["worker_executed"] is executed
    assert payload["triggered"] is True
    assert payload["decision"]["selected"] is True
    assert payload["delivered_payload"] == workers["batch1-worker1"]
    assert event["injection_stage"] == ("delivery" if executed else "dispatch")
    if executed:
        root = Path(result["output_dir"])
        original = json.loads((root / "artifacts" /
                               (payload["original_payload_ref"] + ".json")).read_text())
        assert original["status"] == "completed"
        assert original["findings"]
    else:
        assert payload["original_payload_ref"] is None
    ids = {e["event_id"] for e, _ in audit}
    assert all(set(e["parent_event_ids"]) <= ids for e, _ in audit)
    assert any(event["event_id"] in e["parent_event_ids"] for e, _ in audit)
    # Lead context includes only the failed delivery, never the withheld document IDs.
    messages = [m for role, _, m in model.requests if role == "lead"][-1]
    deliveries = [json.loads(m.content) for m in messages if m.type == "tool"
                  and "assignment_id" in m.content]
    assert deliveries[0] == workers["batch1-worker1"]
    assert "Private findings from batch1-worker1" not in str(messages)
    assert "Private findings from batch1-worker2" in str(messages)
    assert result["usage_by_role"]["worker"]["model_calls"] == (4 if executed else 2)
    assert result["checkpoint_id"]
    with sqlite3.connect(Path(result["output_dir"]) / "checkpoints.sqlite") as db:
        threads = [r[0] for r in db.execute("SELECT DISTINCT thread_id FROM checkpoints")]
    assert len(threads) == (3 if executed else 2)
    store = ArtifactStore(Path(result["output_dir"]) / "artifacts")
    for e, _ in audit:
        store.get(e["payload_ref"])
    # The next Lead request explicitly includes the failure and descends from injection.
    ancestors = set()
    for e, payload in audit:
        if e["event_id"] == event["event_id"] or ancestors.intersection(e["parent_event_ids"]):
            ancestors.add(e["event_id"])
        if e["event_type"] == "model.request" and e["agent_id"] == "lead":
            if error in json.dumps(payload):
                assert e["event_id"] in ancestors
    print(json.dumps({"scenario": kind, "question_id": None, "synthetic": True,
                      "target": "batch1-worker1", "triggered": True,
                      "worker_executed": executed, "lead_received_failure": True,
                      "status": result["status"], "correct": result["grade"]["correct"],
                      "duration_seconds": result["duration_seconds"],
                      "usage": result["usage"]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [{"enabled": False}, {"enabled": True, "probability": 0},
                                     {"enabled": True, "assignment_ids": ["batch9-worker1"]}])
async def test_no_injection(tmp_path, settings):
    model = ScriptedModel()
    result = await execute(tmp_path, model, pipeline_fault=settings)
    assert result["usage"]["model_calls"] == 7
    assert model.peak == 2
    assert all(r["status"] == "completed" for r in result["worker_results"].values())
    assert not any(e["event_type"] == "fault.injected" for e, _ in events(result))
    if not settings["enabled"]:
        print(json.dumps({"scenario": "baseline", "question_id": None, "synthetic": True,
                          "status": result["status"], "correct": result["grade"]["correct"],
                          "duration_seconds": result["duration_seconds"],
                          "usage": result["usage"]}))
        assert not any(e["event_type"].startswith("fault.") for e, _ in events(result))


def test_decisions_are_order_independent():
    cfg = PipelineFaultConfig(enabled=True, probability=0.5, seed=17)
    names = [f"batch1-worker{i}" for i in range(100)]
    a = PipelineFaultInjector(cfg)
    b = PipelineFaultInjector(cfg)
    expected = {n: a.decide(n) for n in names}
    assert expected == {n: b.decide(n) for n in reversed(names)}
    assert {d["selected"] for d in expected.values()} == {True, False}
    assert expected != {n: PipelineFaultInjector(cfg.model_copy(update={"seed": 18})).decide(n)
                        for n in names}


@pytest.mark.asyncio
async def test_natural_failure_is_not_relabelled(tmp_path):
    result = await execute(tmp_path, ScriptedModel(fail_worker=True), pipeline_fault={
        "enabled": True, "fault_type": "timeout", "assignment_ids": ["batch1-worker2"],
    })
    assert "RuntimeError" in result["worker_results"]["batch1-worker2"]["stop_reason"]
    assert not any(e["event_type"] == "fault.injected" for e, _ in events(result))


@pytest.mark.asyncio
async def test_external_cancellation_propagates(tmp_path):
    class BlockingModel(ScriptedModel):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.cancelled = set()
            self.started = set()

        async def invoke(self, role, agent, messages, tools, config):
            if role == "worker":
                self.started.add(agent)
                if len(self.started) == 2:
                    self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled.add(agent)
            return await super().invoke(role, agent, messages, tools, config)

    model = BlockingModel()
    task = asyncio.create_task(execute(tmp_path, model, pipeline_fault={
        "enabled": True, "fault_type": "timeout",
    }))
    await asyncio.wait_for(model.entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert model.cancelled == model.started == {"batch1-worker1", "batch1-worker2"}


@pytest.mark.asyncio
async def test_natural_timeout_is_not_injected(tmp_path):
    model = ScriptedModel()
    result = await execute(tmp_path, model, worker_timeout_seconds=0.001,
                           max_lead_turns=3, pipeline_fault={
                               "enabled": True, "fault_type": "timeout",
                           })
    assert result["worker_results"]
    assert all("TimeoutError" in r["stop_reason"]
               for r in result["worker_results"].values())
    assert model.active == 0
    assert not any(e["event_type"] == "fault.injected" for e, _ in events(result))


@pytest.mark.parametrize("probability,selected", [(0, False), (1, True)])
def test_probability_extremes(monkeypatch, probability, selected):
    class MaximumDigest:
        def digest(self):
            return b"\xff" * 32

    monkeypatch.setattr("multi_agent_research.faults.pipeline.hashlib.sha256",
                        lambda _: MaximumDigest())
    decision = PipelineFaultInjector(PipelineFaultConfig(
        enabled=True, probability=probability,
    )).decide("batch1-worker1")
    assert decision["selected"] is selected
    assert 0 <= decision["draw"] < 1


@pytest.mark.parametrize("settings", [
    {"probability": -0.1}, {"probability": 1.1}, {"probability": float("nan")},
    {"fault_type": "unknown"}, {"unexpected": True},
])
def test_invalid_configuration(settings):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PipelineFaultConfig(**settings)


def test_yaml_configuration(tmp_path):
    path = tmp_path / "fault.yaml"
    path.write_text("pipeline_fault:\n  enabled: true\n  fault_type: dispatch_failure\n"
                    "  assignment_ids: [batch2-worker1]\n  probability: 0.5\n  seed: 19\n")
    cfg = RunConfig.load(path)
    assert cfg.pipeline_fault == PipelineFaultConfig(
        enabled=True, fault_type="dispatch_failure", assignment_ids=["batch2-worker1"],
        probability=0.5, seed=19,
    )
    assert not RunConfig().pipeline_fault.enabled


@pytest.mark.asyncio
async def test_completion_order_does_not_change_decisions(tmp_path):
    decisions = []
    completion_orders = []
    for delayed_worker in ("worker1", "worker2"):
        class ReorderedModel(ScriptedModel):
            async def invoke(self, role, agent, messages, tools, config):
                if role == "worker" and agent.endswith(delayed_worker):
                    await asyncio.sleep(0.1)
                return await super().invoke(role, agent, messages, tools, config)

        result = await execute(tmp_path / delayed_worker, ReorderedModel(), pipeline_fault={
            "enabled": True, "fault_type": "dropped_result", "probability": 0.5, "seed": 17,
        }, max_lead_turns=3)
        audit = events(result)
        decisions.append({e["assignment_id"]: p for e, p in audit
                          if e["event_type"] == "fault.decision"})
        completion_orders.append([e["agent_id"] for e, _ in audit
                                  if e["event_type"] == "worker.finished"])
        assert list(result["worker_results"]) == ["batch1-worker1", "batch1-worker2"]
    assert decisions[0] == decisions[1]
    assert completion_orders[0] == list(reversed(completion_orders[1]))
