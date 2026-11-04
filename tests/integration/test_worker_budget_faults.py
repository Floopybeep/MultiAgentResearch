"""Worker generation and tool-call budget mechanisms, checked with scripted models only."""

import asyncio
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import httpx2
import pytest
import yaml
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from test_pipeline_faults import events
from test_qa_pipeline import ScriptedModel, execute

from multi_agent_research.config import (
    GenerationBudgetFaultConfig,
    RunConfig,
    ToolCallBudgetFaultConfig,
)
from multi_agent_research.fault_injections import select_fault
from multi_agent_research.models.adapter import OpenAIChatCompletionsAdapter
from multi_agent_research.runner import run_qa
from multi_agent_research.schemas import WorkerResult
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

W1, W2 = "batch1-worker1", "batch1-worker2"
GEN_EXHAUSTED = "injected_generation_budget_exhausted"
TOOL_EXHAUSTED = "injected_tool_call_budget_exhausted"
READ = ("read_document", {"document_id": "doc1"})
DONE = ("complete_task", {"findings": "The value is 42.", "document_ids": ["doc1"]})


def step(*calls, output=5, finish="stop"):
    usage = None if output is None else {
        "input_tokens": 10, "output_tokens": output, "total_tokens": 10 + output,
    }
    return calls, usage, finish


class BudgetModel(ScriptedModel):
    """ScriptedModel plus per-worker scripted steps and a record of requested caps."""

    def __init__(self, scripts=None, **kwargs):
        super().__init__(**kwargs)
        self.scripts = scripts or {}
        self.caps = defaultdict(list)

    async def invoke(self, role, agent, messages, tools, config):
        if role == "worker":
            self.caps[agent].append(config.max_output_tokens)
        if role != "worker" or agent not in self.scripts:
            return await super().invoke(role, agent, messages, tools, config)
        self.requests.append((role, agent, list(messages)))
        turn = self.turns[agent]
        self.turns[agent] += 1
        calls, usage, finish = self.scripts[agent][turn]
        return AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
            for i, (name, args) in enumerate(calls)
        ], usage_metadata=usage, response_metadata={"finish_reason": finish})


def generation(**settings):
    return {"worker_budget_faults": {"generation_budget": {"enabled": True, **settings}}}


def tool_budget(**settings):
    return {"worker_budget_faults": {"tool_call_budget": {"enabled": True, **settings}}}


def of(audit, kind, agent=None):
    return [(e, p) for e, p in audit
            if e["event_type"] == kind and (agent is None or e["agent_id"] == agent)]


def tool_requests(audit, agent):
    return [p["name"] for _, p in of(audit, "tool.request", agent)]


def outcome(audit, agent):
    return of(audit, "fault.budget.outcome", agent)[0][1]


def assert_audit_valid(result, audit):
    ids = {e["event_id"] for e, _ in audit}
    assert all(set(e["parent_event_ids"]) <= ids for e, _ in audit)
    for event, _ in audit:
        if event["event_type"].startswith("fault.budget."):
            assert event["assignment_id"] == event["agent_id"]
            assert event["parent_event_ids"]
    for worker in result["worker_results"].values():
        WorkerResult.model_validate(worker)


# Disabled baseline

@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [
    {}, {"worker_budget_faults": {}},
    {"worker_budget_faults": {"generation_budget": {"enabled": False, "max_output_tokens": 1},
                              "tool_call_budget": {"enabled": False, "max_tool_calls": 0}}},
])
async def test_disabled_preserves_baseline(tmp_path, settings):
    model = BudgetModel()
    result = await execute(tmp_path, model, **settings)
    audit = events(result)
    assert result["status"] == "completed"
    assert result["grade"]["method"] == "exact_match"
    assert result["usage"]["model_calls"] == 7
    assert model.peak == 2
    assert dict(model.caps) == {W1: [4096, 4096], W2: [4096, 4096]}
    assert not [e for e, _ in audit if e["event_type"].startswith("fault.")]


@pytest.mark.asyncio
async def test_disabled_natural_truncation_keeps_baseline_flow(tmp_path):
    model = BudgetModel({W1: [step(READ, finish="length"), step(DONE)]})
    result = await execute(tmp_path, model)
    assert result["worker_results"][W1]["status"] == "completed"


# Generation budget

@pytest.mark.asyncio
async def test_truncation_blocks_tool_execution_and_keeps_sibling(tmp_path):
    model = BudgetModel({W1: [step(READ, output=3, finish="length")]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=3, target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == ("budget_exhausted", GEN_EXHAUSTED)
    assert worker["findings"] == "" and worker["document_ids"] == []
    assert tool_requests(audit, W1) == []
    assert result["worker_results"][W2]["status"] == "completed"
    assert model.caps[W1] == [3] and model.caps[W2] == [4096, 4096]
    assert of(audit, "model.request", W1)[0][0]["max_output_tokens"] == 3
    # The full truncated response remains in the log even though it was not executed.
    response = of(audit, "model.response", W1)[0][1]
    assert response["tool_calls"][0]["name"] == "read_document"
    assert response["usage_metadata"]["output_tokens"] == 3
    assert response["response_metadata"]["finish_reason"] == "length"
    assert_audit_valid(result, audit)


@pytest.mark.asyncio
async def test_reduced_cap_can_still_succeed(tmp_path):
    model = BudgetModel()
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=100, target_workers=[W1],
    ))
    audit = events(result)
    assert result["worker_results"][W1]["status"] == "completed"
    assert model.caps[W1] == [100, 100] and model.caps[W2] == [4096, 4096]
    decision = of(audit, "fault.budget.decision", W1)[0][1]
    assert decision["selected"] is True and decision["active"] is True
    assert not of(audit, "fault.budget.exhausted")
    assert outcome(audit, W1)["budget_exhausted"] is False
    assert outcome(audit, W1)["generation_active"] is True
    # Activation is recorded without any claim about the answer.
    assert result["grade"]["correct"] is True


@pytest.mark.asyncio
async def test_exact_cumulative_budget_allows_final_completion(tmp_path):
    model = BudgetModel({W1: [step(READ, output=7), step(DONE, output=3)]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=10, budget_scope="per_worker", target_workers=[W1],
    ))
    audit = events(result)
    assert result["worker_results"][W1]["status"] == "completed"
    assert model.caps[W1] == [10, 3]
    usage = [p["cumulative_output_tokens"] for _, p in of(audit, "fault.budget.generation", W1)]
    assert usage == [7, 10]
    assert outcome(audit, W1)["output_tokens"] == 10


@pytest.mark.asyncio
async def test_spent_cumulative_budget_stops_before_next_call(tmp_path):
    model = BudgetModel({W1: [step(READ, output=5)]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=5, budget_scope="per_worker", target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == ("budget_exhausted", GEN_EXHAUSTED)
    assert model.caps[W1] == [5]
    # The read fit the budget, so it ran and remains attributed to this worker.
    assert tool_requests(audit, W1) == ["read_document"]
    assert worker["document_ids"] == ["doc1"]
    assert of(audit, "fault.budget.exhausted", W1)[0][1]["output_tokens"] == 5


@pytest.mark.asyncio
async def test_cumulative_counters_are_per_worker(tmp_path):
    model = BudgetModel()
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=10, budget_scope="per_worker",
    ))
    assert model.peak == 2
    assert model.caps[W1] == model.caps[W2] == [10, 5]
    assert all(r["status"] == "completed" for r in result["worker_results"].values())
    with sqlite3.connect(Path(result["output_dir"]) / "checkpoints.sqlite") as db:
        assert len(db.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,reason,kind", [
    (10000, "worker_output_limit", "natural_limit"),
    (4096, GEN_EXHAUSTED, "exhausted"),
])
async def test_natural_limit_is_distinct_from_injected(tmp_path, budget, reason, kind):
    model = BudgetModel({W1: [step(READ, output=4096, finish="length")]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=budget, budget_scope="per_worker", target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == ("budget_exhausted", reason)
    assert tool_requests(audit, W1) == []
    assert of(audit, f"fault.budget.{kind}", W1)
    assert outcome(audit, W1)["budget_exhausted"] is (reason == GEN_EXHAUSTED)


@pytest.mark.asyncio
async def test_missing_usage_is_not_counted_as_zero(tmp_path):
    model = BudgetModel({W1: [step(READ, output=None)]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=10, budget_scope="per_worker", target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == (
        "failed", "generation_budget_usage_unavailable",
    )
    assert tool_requests(audit, W1) == []
    assert of(audit, "fault.budget.error", W1)
    assert not of(audit, "fault.budget.exhausted")
    assert result["worker_results"][W2]["status"] == "completed"


@pytest.mark.asyncio
async def test_missing_usage_is_harmless_per_call(tmp_path):
    model = BudgetModel({W1: [step(READ, output=None), step(DONE, output=None)]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=10, target_workers=[W1],
    ))
    assert result["worker_results"][W1]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,finish", [
    ("per_call", "stop"), ("per_call", "length"), ("per_worker", "stop"),
])
async def test_provider_cap_violation_is_not_exhaustion(tmp_path, scope, finish):
    model = BudgetModel({W1: [step(DONE, output=5, finish=finish)]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=4, budget_scope=scope, target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == ("failed", "generation_budget_not_honored")
    assert worker["findings"] == ""
    assert tool_requests(audit, W1) == []
    assert of(audit, "fault.budget.error", W1)[0][1]["output_tokens"] == 5
    assert of(audit, "model.response", W1)[0][1]["usage_metadata"]["output_tokens"] == 5
    assert not of(audit, "fault.budget.exhausted")


@pytest.mark.asyncio
async def test_provider_failure_is_not_relabelled(tmp_path):
    result = await execute(tmp_path, BudgetModel(fail_worker=True), **generation(
        max_output_tokens=10, target_workers=[W2],
    ))
    audit = events(result)
    worker = result["worker_results"][W2]
    assert worker["status"] == "failed" and "RuntimeError" in worker["stop_reason"]
    assert not of(audit, "fault.budget.exhausted")
    assert outcome(audit, W2)["budget_exhausted"] is False
    assert outcome(audit, W2)["tool_calls"] is None


@pytest.mark.asyncio
async def test_timeout_is_preserved_under_active_faults(tmp_path):
    class HangingModel(BudgetModel):
        async def invoke(self, role, agent, messages, tools, config):
            if agent == W1:
                await asyncio.sleep(5)
            return await super().invoke(role, agent, messages, tools, config)

    settings = {"worker_budget_faults": {
        "generation_budget": {"enabled": True, "max_output_tokens": 100, "target_workers": [W1]},
        "tool_call_budget": {"enabled": True, "max_tool_calls": 2, "target_workers": [W1]},
    }}
    result = await execute(tmp_path, HangingModel(), **settings, worker_timeout_seconds=0.2)
    audit = events(result)
    assert "TimeoutError" in result["worker_results"][W1]["stop_reason"]
    assert result["worker_results"][W1]["status"] == "failed"
    assert outcome(audit, W1)["budget_exhausted"] is False


@pytest.mark.asyncio
async def test_exhaustion_logs_stay_redacted(tmp_path, monkeypatch):
    secret = "sk-test-credential-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    class LeakyModel(BudgetModel):
        async def invoke(self, role, agent, messages, tools, config):
            response = await super().invoke(role, agent, messages, tools, config)
            if agent == W1:
                response.content = f"partial {secret}"
            return response

    model = LeakyModel({W1: [step(READ, output=3, finish="length")]})
    result = await execute(tmp_path, model, **generation(
        max_output_tokens=3, target_workers=[W1],
    ), max_lead_turns=3)
    response = of(events(result), "model.response", W1)[0][1]
    assert response["content"] == "partial [REDACTED]"


# Production adapter

def completion(body, *, calls, finish, output):
    return httpx2.Response(200, json={
        "id": "chatcmpl-test", "object": "chat.completion", "created": 1, "model": body["model"],
        "choices": [{"index": 0, "finish_reason": finish, "message": {
            "role": "assistant", "content": None,
            "tool_calls": [
                {"id": f"call-{i}", "type": "function",
                 "function": {"name": name, "arguments": arguments}}
                for i, (name, arguments) in enumerate(calls)
            ],
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": output,
                  "total_tokens": 10 + output},
    })


@pytest.fixture
def transport(monkeypatch):
    """Intercept below the OpenAI SDK and above the network; no request leaves the process."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-value")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://endpoint.invalid/v1")
    bodies = []

    def install(reply):
        async def send(self, request, **kwargs):
            body = json.loads(request.content)
            bodies.append(body)
            await asyncio.sleep(0.01)
            response = reply(body)
            response.request = request
            return response

        monkeypatch.setattr(httpx2.AsyncClient, "send", send)
        return bodies

    return install


@pytest.mark.asyncio
async def test_adapter_overrides_are_request_local(transport):
    bodies = transport(lambda body: completion(
        body, calls=[], finish="stop", output=body["max_completion_tokens"],
    ))
    adapter = OpenAIChatCompletionsAdapter()
    base = RunConfig().worker
    small = base.model_copy(update={"max_output_tokens": 7})
    replies = await asyncio.gather(
        adapter.invoke("worker", W1, [("user", "a")], [], small),
        adapter.invoke("worker", W2, [("user", "b")], [], base),
    )
    assert {b["messages"][0]["content"]: b["max_completion_tokens"] for b in bodies} == {
        "a": 7, "b": 4096,
    }
    assert [r.usage_metadata["output_tokens"] for r in replies] == [7, 4096]
    assert list(adapter.models) == ["worker"]
    # The small first call did not lower later requests that use the same cached client.
    await adapter.invoke("worker", W2, [("user", "c")], [], base)
    assert bodies[-1]["max_completion_tokens"] == 4096


@pytest.mark.asyncio
async def test_production_adapter_flow_with_real_response_parsing(tmp_path, transport):
    """Targeted truncated JSON stops; a sibling on the same cached client keeps its cap."""

    def reply(body):
        assignment = json.loads(body["messages"][1]["content"])["assignment"]
        doc = "doc1" if "doc1" in assignment else "doc2"
        if doc == "doc1":
            return completion(body, calls=[("read_document", '{"document_id": "do')],
                              finish="length", output=body["max_completion_tokens"])
        if body["messages"][-1]["role"] == "tool":
            arguments = json.dumps({"findings": "42", "document_ids": ["doc2"]})
            return completion(body, calls=[("complete_task", arguments)], finish="stop", output=5)
        return completion(body, calls=[("read_document", json.dumps({"document_id": doc}))],
                          finish="stop", output=5)

    bodies = transport(reply)
    adapter = OpenAIChatCompletionsAdapter()

    class WorkersThroughAdapter(ScriptedModel):
        async def invoke(self, role, agent, messages, tools, config):
            if role == "worker":
                return await adapter.invoke(role, agent, messages, tools, config)
            return await super().invoke(role, agent, messages, tools, config)

    result = await execute(tmp_path, WorkersThroughAdapter(), **generation(
        max_output_tokens=9, target_workers=[W1],
    ))
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == ("budget_exhausted", GEN_EXHAUSTED)
    assert tool_requests(audit, W1) == []
    assert result["worker_results"][W2]["status"] == "completed"
    caps = sorted(b["max_completion_tokens"] for b in bodies)
    assert caps == [9, 4096, 4096]
    response = of(audit, "model.response", W1)[0][1]
    assert response["tool_calls"] == [] and response["invalid_tool_calls"]
    assert response["response_metadata"]["finish_reason"] == "length"
    assert of(audit, "fault.budget.generation", W1)[0][1]["reported_output_tokens"] == 9


# Tool-call budget

@pytest.mark.asyncio
@pytest.mark.parametrize("limit,status,reason,requests", [
    (0, "budget_exhausted", TOOL_EXHAUSTED, []),
    (1, "budget_exhausted", TOOL_EXHAUSTED, ["read_document"]),
    (2, "completed", "complete_task", ["read_document", "complete_task"]),
    (5, "completed", "complete_task", ["read_document", "complete_task"]),
])
async def test_tool_budget_limits(tmp_path, limit, status, reason, requests):
    model = BudgetModel()
    result = await execute(tmp_path, model, **tool_budget(
        max_tool_calls=limit, target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == (status, reason)
    assert tool_requests(audit, W1) == requests
    assert outcome(audit, W1)["tool_calls"] == len(requests)
    assert len(of(audit, "tool.result", W1)) == len(requests)
    assert result["worker_results"][W2]["status"] == "completed"
    assert tool_requests(audit, W2) == ["read_document", "complete_task"]
    assert outcome(audit, W2)["tool_calls"] == 2
    assert model.peak == 2
    decision = of(audit, "fault.budget.decision", W1)[0][1]
    assert decision["severity"]["effective_max_tool_calls"] == limit
    assert bool(of(audit, "fault.budget.exhausted", W1)) is (status != "completed")
    assert_audit_valid(result, audit)


@pytest.mark.asyncio
async def test_parallel_calls_admit_list_prefix(tmp_path):
    reads = [("read_document", {"document_id": d}) for d in ("doc2", "doc1", "doc2")]
    model = BudgetModel({W1: [step(*reads, DONE)]})
    result = await execute(tmp_path, model, **tool_budget(
        max_tool_calls=2, target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    worker = result["worker_results"][W1]
    assert (worker["status"], worker["stop_reason"]) == ("budget_exhausted", TOOL_EXHAUSTED)
    assert [p["args"]["document_id"] for _, p in of(audit, "tool.request", W1)] == ["doc2", "doc1"]
    assert worker["document_ids"] == ["doc1", "doc2"]
    exhausted = of(audit, "fault.budget.exhausted", W1)[0][1]
    assert exhausted["tool_calls"] == 2
    assert exhausted["blocked_tool_call_ids"] == [f"{W1}-0-2", f"{W1}-0-3"]


@pytest.mark.asyncio
async def test_failed_and_unknown_calls_consume_slots(tmp_path):
    failed = [("read_document", {"document_id": "outside"}), ("no_such_tool", {}),
              ("read_document", {"document_id": "doc1"})]
    scripts = {W1: [step(*failed), step(DONE)]}
    result = await execute(tmp_path, BudgetModel(scripts), **tool_budget(
        max_tool_calls=3, target_workers=[W1],
    ), max_lead_turns=3)
    audit = events(result)
    assert result["worker_results"][W1]["stop_reason"] == TOOL_EXHAUSTED
    assert len(of(audit, "tool.error", W1)) == 2
    assert outcome(audit, W1)["tool_calls"] == 3
    assert "complete_task" not in tool_requests(audit, W1)


@pytest.mark.asyncio
async def test_completion_is_counted_when_it_fits(tmp_path):
    failed = [("read_document", {"document_id": "outside"}), ("no_such_tool", {}),
              ("read_document", {"document_id": "doc1"})]
    scripts = {W1: [step(*failed), step(DONE)]}
    result = await execute(tmp_path, BudgetModel(scripts), **tool_budget(
        max_tool_calls=4, target_workers=[W1],
    ))
    audit = events(result)
    assert result["worker_results"][W1]["status"] == "completed"
    assert outcome(audit, W1)["tool_calls"] == 4 == len(tool_requests(audit, W1))


@pytest.mark.asyncio
async def test_limit_at_or_above_configured_value_is_not_active(tmp_path):
    result = await execute(tmp_path, BudgetModel(), **tool_budget(max_tool_calls=20))
    audit = events(result)
    decisions = [p for _, p in of(audit, "fault.budget.decision")]
    tool_decisions = [p for p in decisions if p["fault_type"] == "tool_call_budget"]
    assert all(p["selected"] and not p["active"] for p in tool_decisions)
    assert all(r["status"] == "completed" for r in result["worker_results"].values())


@pytest.mark.asyncio
async def test_natural_tool_limit_is_not_relabelled(tmp_path):
    result = await execute(tmp_path, BudgetModel(), **tool_budget(
        max_tool_calls=5,
    ), max_worker_tool_calls=1, max_lead_turns=3)
    assert all(r["stop_reason"] == "worker_tool_limit" for r in result["worker_results"].values())
    assert not of(events(result), "fault.budget.exhausted")


# Selection

def decide(fault_type="generation_budget", question="q", agent=W1, **settings):
    config = GenerationBudgetFaultConfig(enabled=True, **settings)
    return select_fault(config, fault_type, question, agent)


@pytest.mark.parametrize("probability,selected", [(0, False), (1, True)])
def test_probability_extremes(probability, selected):
    assert all(
        decide(probability=probability, agent=f"batch1-worker{i}")["selected"] is selected
        for i in range(1, 200)
    )


def test_fractional_probability_is_deterministic_and_proportionate():
    names = [f"batch{b}-worker{w}" for b in range(1, 41) for w in range(1, 26)]
    picks = {n: decide(probability=0.25, agent=n)["selected"] for n in names}
    assert picks == {n: decide(probability=0.25, agent=n)["selected"] for n in reversed(names)}
    assert 0.2 < sum(picks.values()) / len(names) < 0.3


@pytest.mark.parametrize("change", [
    {"question": "other"}, {"fault_type": "tool_call_budget"}, {"seed": 7},
])
def test_selection_inputs_change_draws(change):
    assert decide()["draw"] != decide(**change)["draw"]
    assert decide()["draw"] == decide()["draw"]


def test_disabled_and_untargeted_are_never_selected():
    config = GenerationBudgetFaultConfig(enabled=False)
    assert select_fault(config, "generation_budget", "q", W1)["selected"] is False
    decision = decide(target_workers=[W2])
    assert decision["targeted"] is False and decision["selected"] is False


@pytest.mark.asyncio
async def test_integrated_probability_extremes_and_fraction(tmp_path):
    states = {}
    for probability in (0, 0.5, 1):
        result = await execute(tmp_path / str(probability), BudgetModel(), **tool_budget(
            max_tool_calls=2, probability=probability, seed=3,
        ))
        decisions = [p for _, p in of(events(result), "fault.budget.decision")]
        states[probability] = [p["selected"] for p in decisions]
        assert all(p["active"] == p["selected"] for p in decisions)
    assert states[0] == [False, False] and states[1] == [True, True]
    expected = [decide("tool_call_budget", "What is the value?", w, probability=0.5,
                       seed=3)["selected"] for w in (W1, W2)]
    assert states[0.5] == expected


@pytest.mark.asyncio
async def test_completion_order_does_not_change_budget_decisions(tmp_path):
    decisions, orders = [], []
    settings = {"worker_budget_faults": {
        "generation_budget": {"enabled": True, "probability": 0.5, "seed": 11,
                              "max_output_tokens": 100},
        "tool_call_budget": {"enabled": True, "probability": 0.5, "seed": 11,
                             "max_tool_calls": 2},
    }}
    for delayed in (W1, W2):
        class Delayed(BudgetModel):
            async def invoke(self, role, agent, messages, tools, config):
                if agent == delayed:
                    await asyncio.sleep(0.1)
                return await super().invoke(role, agent, messages, tools, config)

        result = await execute(tmp_path / delayed, Delayed(), **settings)
        audit = events(result)
        decisions.append(sorted(
            ((e["assignment_id"], p["fault_type"], p["draw"], p["selected"])
             for e, p in of(audit, "fault.budget.decision")),
        ))
        orders.append([e["agent_id"] for e, _ in of(audit, "worker.finished")])
    assert decisions[0] == decisions[1]
    assert len(decisions[0]) == 4
    assert orders[0] == list(reversed(orders[1]))


@pytest.mark.asyncio
async def test_question_id_is_the_selection_key(tmp_path):
    documents = OracleDocuments([LocalDocument(document_id=f"doc{i}", title=str(i),
                                               url=f"https://example.org/{i}", text="42")
                                 for i in (1, 2)])
    drawn = []
    for question_id in ("101", "202"):
        result = await run_qa(
            "Same text?",
            RunConfig(output_dir=tmp_path, **tool_budget(max_tool_calls=2, probability=0.5)),
            BudgetModel(), documents, metadata={"question_id": question_id},
        )
        decisions = of(events(result), "fault.budget.decision", W1)
        drawn.append((decisions[0][1]["question_key"], decisions[0][1]["draw"]))
    assert [key for key, _ in drawn] == ["101", "202"]
    assert drawn[0][1] != drawn[1][1]


@pytest.mark.asyncio
async def test_both_faults_are_logged_independently(tmp_path):
    settings = {"worker_budget_faults": {
        "generation_budget": {"enabled": True, "max_output_tokens": 100, "target_workers": [W1]},
        "tool_call_budget": {"enabled": True, "max_tool_calls": 1, "target_workers": [W2]},
    }}
    model = BudgetModel()
    result = await execute(tmp_path, model, **settings, max_lead_turns=3)
    audit = events(result)
    state = {(e["assignment_id"], p["fault_type"]): p["active"]
             for e, p in of(audit, "fault.budget.decision")}
    assert state == {
        (W1, "generation_budget"): True, (W1, "tool_call_budget"): False,
        (W2, "generation_budget"): False, (W2, "tool_call_budget"): True,
    }
    assert result["worker_results"][W1]["status"] == "completed"
    assert result["worker_results"][W2]["stop_reason"] == TOOL_EXHAUSTED
    assert model.caps[W1] == [100, 100] and model.caps[W2] == [4096, 4096]
    exhausted = of(audit, "fault.budget.exhausted")
    assert [(e["agent_id"], p["fault_type"]) for e, p in exhausted] == [(W2, "tool_call_budget")]
    assert_audit_valid(result, audit)


# Coexistence

@pytest.mark.asyncio
async def test_blocked_reads_do_not_consume_document_injection(tmp_path):
    result = await execute(
        tmp_path, BudgetModel(), **tool_budget(max_tool_calls=0, target_workers=[W1]),
        max_lead_turns=3,
        document_injection={"enabled": True, "num_docs": 1, "prompt": "INJECTION_MARKER"},
    )
    audit = events(result)
    injected = of(audit, "document.injected")
    assert [e["agent_id"] for e, _ in injected] == [W2]
    assert "INJECTION_MARKER" in of(audit, "tool.result", W2)[0][1]["text"]


@pytest.mark.asyncio
async def test_exhausted_worker_is_not_relabelled_by_pipeline_fault(tmp_path):
    result = await execute(
        tmp_path, BudgetModel(), **tool_budget(max_tool_calls=1, target_workers=[W1]),
        max_lead_turns=3,
        pipeline_fault={"enabled": True, "fault_type": "dropped_result"},
    )
    workers = result["worker_results"]
    audit = events(result)
    assert workers[W1]["stop_reason"] == TOOL_EXHAUSTED
    assert workers[W2]["stop_reason"] == "InjectedDroppedWorkerResult"
    assert [e["assignment_id"] for e, _ in of(audit, "fault.injected")] == [W2]


@pytest.mark.asyncio
async def test_dispatch_failure_precedes_budget_selection(tmp_path):
    result = await execute(
        tmp_path, BudgetModel(), **generation(max_output_tokens=100),
        pipeline_fault={"enabled": True, "fault_type": "dispatch_failure",
                        "assignment_ids": [W1]},
    )
    audit = events(result)
    assert result["worker_results"][W1]["stop_reason"] == "InjectedWorkerDispatchFailure"
    assert result["worker_results"][W2]["status"] == "completed"
    assert {e["assignment_id"] for e, _ in of(audit, "fault.budget.decision")} == {W2}


# Configuration

def test_yaml_controls_and_baseline_defaults(tmp_path):
    path = tmp_path / "budget.yaml"
    path.write_text(
        "worker_budget_faults:\n"
        "  generation_budget:\n    enabled: true\n    probability: 0.5\n"
        "    max_output_tokens: 256\n    budget_scope: per_worker\n"
        "    target_workers: [batch1-worker1]\n    seed: 7\n"
        "  tool_call_budget:\n    enabled: true\n    max_tool_calls: 0\n"
    )
    faults = RunConfig.load(path).worker_budget_faults
    assert faults.generation_budget == GenerationBudgetFaultConfig(
        enabled=True, probability=0.5, max_output_tokens=256, budget_scope="per_worker",
        target_workers=["batch1-worker1"], seed=7,
    )
    assert faults.tool_call_budget == ToolCallBudgetFaultConfig(enabled=True, max_tool_calls=0)
    baseline = RunConfig.load("configs/baseline.yaml").worker_budget_faults
    assert not baseline.generation_budget.enabled and not baseline.tool_call_budget.enabled
    # Frequency, severity and targeting are all set in the file, not by Python defaults.
    listed = yaml.safe_load(Path("configs/baseline.yaml").read_text())["worker_budget_faults"]
    # A parameter added to a fault later must also be listed in the file, at its default.
    for name, cls in (("generation_budget", GenerationBudgetFaultConfig),
                      ("tool_call_budget", ToolCallBudgetFaultConfig)):
        assert listed[name] == cls().model_dump()


@pytest.mark.parametrize("cls,settings", [
    (GenerationBudgetFaultConfig, {"max_output_tokens": 0}),
    (GenerationBudgetFaultConfig, {"max_output_tokens": "10"}),
    (GenerationBudgetFaultConfig, {"budget_scope": "per_run"}),
    (GenerationBudgetFaultConfig, {"target_workers": ["worker1"]}),
    (GenerationBudgetFaultConfig, {"probability": 1.5}),
    (ToolCallBudgetFaultConfig, {"max_tool_calls": -1}),
    (ToolCallBudgetFaultConfig, {"max_tool_calls": 1.5}),
    (ToolCallBudgetFaultConfig, {"unexpected": True}),
])
def test_invalid_configuration(cls, settings):
    with pytest.raises(ValidationError):
        cls(**settings)


# Every control, set only through a YAML file, must change what happens at runtime.

COST = 50


class CostModel(ScriptedModel):
    """Each worker reply needs COST tokens; a lower cap truncates it as a provider would."""

    def __init__(self):
        super().__init__()
        self.caps = defaultdict(list)

    async def invoke(self, role, agent, messages, tools, config):
        response = await super().invoke(role, agent, messages, tools, config)
        if role == "worker":
            cap = config.max_output_tokens
            self.caps[agent].append(cap)
            output = min(cap, COST)
            response.usage_metadata = {"input_tokens": 10, "output_tokens": output,
                                       "total_tokens": 10 + output}
            response.response_metadata = {"finish_reason": "length" if cap < COST else "stop"}
        return response


async def run_yaml(tmp_path, settings, name="run"):
    """Load settings from a real YAML file, then run the scripted pipeline."""
    directory = tmp_path / name
    directory.mkdir()
    path = directory / "experiment.yaml"
    path.write_text(yaml.safe_dump({"output_dir": str(directory), **settings}))
    documents = OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in (1, 2)
    ])
    model = CostModel()
    result = await run_qa("What is the value?", RunConfig.load(path), model, documents,
                          reference_answer="42")
    return result, model


def yaml_fault(name, **settings):
    return {"worker_budget_faults": {name: settings}}


GENERATION_TOO_LOW = {"max_output_tokens": COST - 1}
TOOLS_TOO_LOW = {"max_tool_calls": 1}
FAULTS = [("generation_budget", GENERATION_TOO_LOW, GEN_EXHAUSTED),
          ("tool_call_budget", TOOLS_TOO_LOW, TOOL_EXHAUSTED)]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,severity,reason", FAULTS)
async def test_config_enabled_switches_the_fault(tmp_path, name, severity, reason):
    off, _ = await run_yaml(tmp_path, yaml_fault(name, enabled=False, **severity), "off")
    on, _ = await run_yaml(tmp_path, {
        **yaml_fault(name, enabled=True, target_workers=[W1], **severity), "max_lead_turns": 4,
    }, "on")
    assert off["worker_results"][W1]["status"] == "completed"
    assert not [e for e, _ in events(off) if e["event_type"].startswith("fault.")]
    assert on["worker_results"][W1]["stop_reason"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("name,severity,reason", FAULTS)
async def test_config_probability_controls_triggering(tmp_path, name, severity, reason):
    never, _ = await run_yaml(tmp_path, yaml_fault(
        name, enabled=True, probability=0, **severity), "never")
    always, _ = await run_yaml(tmp_path, {
        **yaml_fault(name, enabled=True, probability=1, **severity), "max_lead_turns": 4,
    }, "always")
    assert all(r["status"] == "completed" for r in never["worker_results"].values())
    assert all(r["stop_reason"] == reason for r in always["worker_results"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("name,severity,reason", FAULTS)
async def test_config_fractional_probability_and_seed_pick_workers(tmp_path, name, severity, reason):
    question = "What is the value?"
    patterns = set()
    for seed in range(8):
        result, _ = await run_yaml(tmp_path, {
            **yaml_fault(name, enabled=True, probability=0.5, seed=seed, **severity),
            "max_lead_turns": 4,
        }, f"seed{seed}")
        cfg = GenerationBudgetFaultConfig(enabled=True, probability=0.5, seed=seed)
        expected = tuple(select_fault(cfg, name, question, w)["selected"] for w in (W1, W2))
        actual = tuple(result["worker_results"][w]["stop_reason"] == reason for w in (W1, W2))
        assert actual == expected
        patterns.add(actual)
    # The seed really changes who is hit, and 0.5 neither always nor never triggers.
    assert len(patterns) > 1
    assert any(any(p) for p in patterns) and any(not all(p) for p in patterns)


@pytest.mark.asyncio
@pytest.mark.parametrize("cap,status,caps", [
    (COST - 1, "budget_exhausted", [COST - 1]),
    (COST, "completed", [COST, COST]),
    (1000, "completed", [1000, 1000]),
    (5000, "completed", [4096, 4096]),
])
async def test_config_max_output_tokens_sets_cap_and_outcome(tmp_path, cap, status, caps):
    result, model = await run_yaml(tmp_path, {
        **yaml_fault("generation_budget", enabled=True, max_output_tokens=cap,
                     target_workers=[W1]),
        "max_lead_turns": 4,
    })
    assert result["worker_results"][W1]["status"] == status
    assert model.caps[W1] == caps
    assert model.caps[W2] == [4096, 4096]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,status,caps", [
    ("per_call", "completed", [60, 60]),
    ("per_worker", "budget_exhausted", [60, 10]),
])
async def test_config_budget_scope_changes_accounting(tmp_path, scope, status, caps):
    result, model = await run_yaml(tmp_path, {
        **yaml_fault("generation_budget", enabled=True, max_output_tokens=60, budget_scope=scope,
                     target_workers=[W1]),
        "max_lead_turns": 4,
    })
    assert result["worker_results"][W1]["status"] == status
    assert model.caps[W1] == caps


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,status,executed", [
    (0, "budget_exhausted", 0), (1, "budget_exhausted", 1),
    (2, "completed", 2), (3, "completed", 2),
])
async def test_config_max_tool_calls_limits_execution(tmp_path, limit, status, executed):
    result, _ = await run_yaml(tmp_path, {
        **yaml_fault("tool_call_budget", enabled=True, max_tool_calls=limit, target_workers=[W1]),
        "max_lead_turns": 4,
    })
    assert result["worker_results"][W1]["status"] == status
    assert len(tool_requests(events(result), W1)) == executed
    assert result["worker_results"][W2]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,severity,reason", FAULTS)
@pytest.mark.parametrize("targets,hit", [
    ([W1], {W1}), ([W2], {W2}), ([], {W1, W2}), (["batch9-worker1"], set()),
])
async def test_config_target_workers_chooses_who_is_hit(tmp_path, name, severity, reason, targets, hit):
    result, _ = await run_yaml(tmp_path, {
        **yaml_fault(name, enabled=True, target_workers=targets, **severity), "max_lead_turns": 4,
    })
    assert {w for w, r in result["worker_results"].items() if r["stop_reason"] == reason} == hit


@pytest.mark.asyncio
@pytest.mark.parametrize("name,reason", [
    ("generation_budget", None), ("tool_call_budget", TOOL_EXHAUSTED),
])
async def test_config_baseline_block_works_by_flipping_enabled(tmp_path, name, reason):
    settings = yaml.safe_load(Path("configs/baseline.yaml").read_text())
    settings["output_dir"] = str(tmp_path)
    block = settings["worker_budget_faults"]
    assert not any(fault["enabled"] for fault in block.values())
    block[name].update(enabled=True, target_workers=[W1])
    settings["max_lead_turns"] = 4
    result, model = await run_yaml(tmp_path, settings)
    worker = result["worker_results"][W1]
    if reason:
        assert worker["stop_reason"] == reason
    else:
        # The listed 128-token cap reaches the request, and this worker fits within it.
        assert worker["status"] == "completed" and model.caps[W1] == [128, 128]
