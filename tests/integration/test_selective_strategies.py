"""WP5: six recovery strategies from one tool-faulted attempt, costed alike (ScriptedModel only)."""

import hashlib
import inspect
import json
import sqlite3
from pathlib import Path
from typing import get_type_hints

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from multi_agent_research import selective, selective_strategies
from multi_agent_research.config import RunConfig
from multi_agent_research.runner import run_qa
from multi_agent_research.runtime import INJECTION_EVENTS
from multi_agent_research.selective_strategies import STRATEGIES, StrategyOutcome
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

NAMES = ["no_recovery", "full_restart", "batch_replay", "batch_replay_cached",
         "worker_recovery", "worker_retry"]
WORKERS = 3
FULL_ANSWER = "{" + "; ".join(f"doc{i} gives the value 42." for i in range(1, WORKERS + 1)) + "}"


class ScriptedModel:
    """Workers read their assigned document until a read succeeds, then complete.

    The Lead's answer joins the findings it was delivered, so a strategy that loses or
    alters a worker result reaches a different answer, not the same constant.
    """

    batches = [[1, 2, 3]]

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
            if turn - 2 < len(self.batches):
                return response(*[
                    ("run_blocking_subagent",
                     {"prompt": f"Read doc{i} and report its value.", "document_id": f"doc{i}"})
                    for i in self.batches[turn - 2]
                ])
            delivered = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
            findings = [d["findings"] for d in delivered
                        if isinstance(d, dict) and d.get("status") == "completed"]
            return response(("submit_answer", {"answer": "{" + "; ".join(findings) + "}"}))
        [assignment] = [m for m in messages if isinstance(m, HumanMessage)]
        document = json.loads(assignment.content)["available_documents"][0]["document_id"]
        read = any(isinstance(m, ToolMessage) and "document_id" in json.loads(m.content)
                   for m in messages)
        if not read:
            return response(("read_document", {"document_id": document}))
        return response(("complete_task", {
            "findings": f"{document} gives the value 42.", "document_ids": [document],
        }))


class TwoBatchLead(ScriptedModel):
    batches = [[1, 2], [3]]


def documents():
    return OracleDocuments([
        LocalDocument(document_id=f"doc{i}", title=f"Fixture {i}",
                      url=f"https://example.org/{i}", text="The value is 42.")
        for i in range(1, WORKERS + 1)
    ])


def denial(mode="immediate", docs=("doc2",), max_failures=None, interrupt="batch"):
    # Defaults mirror configs/faults-tool-read-denial.yaml: persistent, uncapped.
    return {"enabled": True, "mode": mode, "document_ids": list(docs), "persistent": True,
            "max_failures": max_failures, "interrupt_on_fault": interrupt}


async def attempt(tmp_path, model=None, **fault):
    # always_verify off: sibling_cache refuses deliveries that are not plain dumps.
    config = RunConfig(output_dir=tmp_path / "runs", call_timeout_seconds=0.05,
                       always_verify=False, tool_failure=denial(**fault))
    result = await run_qa("What is the value?", config, model or ScriptedModel(), documents(),
                          reference_answer="42")
    return result, Path(result["output_dir"])


async def interrupted(tmp_path, **fault):
    result, run_dir = await attempt(tmp_path, **fault)
    assert (result["status"], result["stop_reason"]) == ("interrupted", "fault_injected")
    return run_dir


async def run_all(run_dir, output_root):
    return {name: await strategy(run_dir, model=ScriptedModel(), output_root=output_root)
            for name, strategy in STRATEGIES.items()}


def read_events(run_dir, run_id):
    with sqlite3.connect(Path(run_dir) / "events.sqlite") as db:
        events = [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM events ORDER BY sequence"
        )]
    return [e for e in events if e["run_id"] == run_id]


def branch_events(branch_dir):
    run_id = json.loads((Path(branch_dir) / "recovery.json").read_text())["run_id"]
    return read_events(branch_dir, run_id)


def of_type(events, kind):
    return [e for e in events if e["event_type"] == kind]


def costs(outcome):
    return (outcome["workers_executed"], outcome["workers_reused"], outcome["workers_resumed"],
            outcome["worker_model_calls"], outcome["recover_calls"], outcome["tokens_recovery"])


# S1
def test_registry_has_the_six_strategies_with_one_signature():
    assert list(STRATEGIES) == NAMES
    for strategy in STRATEGIES.values():
        assert inspect.iscoroutinefunction(strategy)
        params = inspect.signature(strategy).parameters.values()
        assert [(p.name, p.kind, p.default) for p in params] == [
            ("attempt_dir", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
            # No default model: recover() would fall back to the live adapter.
            ("model", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
            ("output_root", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
        ]
        assert get_type_hints(strategy)["return"] is StrategyOutcome


# S2
@pytest.mark.asyncio
async def test_each_strategy_returns_a_well_formed_outcome(tmp_path):
    outcomes = await run_all(await interrupted(tmp_path), tmp_path / "strategies")
    for name, outcome in outcomes.items():
        assert set(outcome) == set(StrategyOutcome.__annotations__)
        assert outcome["name"] == name
        assert isinstance(outcome["status"], str) and outcome["status"]
        assert isinstance(outcome["stop_reason"], str) and outcome["stop_reason"]
        assert outcome["answer"] is None or isinstance(outcome["answer"], str)
        for key in ("workers_executed", "workers_reused", "workers_resumed",
                    "worker_model_calls", "recover_calls", "tokens_total", "tokens_recovery"):
            assert type(outcome[key]) is int and outcome[key] >= 0, (name, key)
        assert len(outcome["branch_dirs"]) == outcome["recover_calls"]
        assert all((Path(d) / "recovery.json").is_file() for d in outcome["branch_dirs"])
        # Strategies emit nothing of their own; only a faults-on retry may re-inject.
        injected = {e["event_type"] for d in outcome["branch_dirs"] for e in branch_events(d)
                    if e["event_type"] in INJECTION_EVENTS}
        assert injected == ({"tool.failure_injected"} if name == "worker_retry" else set())
    assert outcomes["no_recovery"]["status"] == "interrupted"
    assert outcomes["worker_retry"]["answer"] is None


# (workers_executed, workers_reused, workers_resumed, worker_model_calls, recover_calls,
#  tokens_recovery). Every scripted call costs 15 tokens; recover() never grades.
EXPECTED = {
    "no_recovery": (0, 0, 0, 0, 0, 0),
    # Two resumes: worker2's one call after the read, then the Lead's one reassessment.
    "worker_recovery": (0, 3, 1, 1, 2, 30),
    "batch_replay_cached": (1, 2, 0, 2, 1, 45),
    "batch_replay": (3, 0, 0, 6, 1, 105),
    # The Lead's plan and delegation calls on top of batch_replay.
    "full_restart": (3, 0, 0, 6, 1, 135),
}


# S3
@pytest.mark.asyncio
async def test_finer_recovery_costs_strictly_less(tmp_path):
    run_dir = await interrupted(tmp_path)
    outcomes = await run_all(run_dir, tmp_path / "strategies")
    assert {name: costs(outcomes[name]) for name in EXPECTED} == EXPECTED
    o = outcomes
    for key in ("workers_executed", "tokens_recovery"):
        assert (o["worker_recovery"][key] < o["batch_replay_cached"][key]
                < o["batch_replay"][key] <= o["full_restart"][key]), key
    # The raw total carries the whole source attempt, which is why it is not compared.
    source = o["no_recovery"]["tokens_total"]
    assert source > 0
    for name in ("full_restart", "batch_replay", "batch_replay_cached"):
        assert o[name]["tokens_total"] == source + o[name]["tokens_recovery"]


# S4
@pytest.mark.asyncio
async def test_cheaper_strategies_reach_the_same_answer(tmp_path):
    outcomes = await run_all(await interrupted(tmp_path), tmp_path / "strategies")
    for name in ("batch_replay", "batch_replay_cached", "worker_recovery", "full_restart"):
        assert (outcomes[name]["status"], outcomes[name]["stop_reason"],
                outcomes[name]["answer"]) == ("completed", "submit_answer", FULL_ANSWER), name


# S5
@pytest.mark.asyncio
async def test_worker_retry_fails_again_under_persistent_denial(tmp_path):
    run_dir = await interrupted(tmp_path / "persistent")
    [site] = selective.earliest_fault_by_agent(selective.find_tool_fault_sites(run_dir)).values()
    outcome = await selective_strategies.worker_retry(
        run_dir, model=ScriptedModel(), output_root=tmp_path / "persistent" / "strategies")
    assert outcome["status"] != "completed"
    [branch] = outcome["branch_dirs"]
    again = of_type(branch_events(branch), "tool.failure_injected")
    assert again, "the retried worker was not denied again"
    assert again[0]["agent_id"] == site["agent_id"]
    first = json.loads((Path(branch) / "artifacts" / f"{again[0]['payload_ref']}.json")
                       .read_text())
    assert (first["document_id"], first["offset"]) == (site["document_id"], site["offset"])


@pytest.mark.asyncio
async def test_worker_retry_completes_when_the_fault_is_capped(tmp_path):
    run_dir = await interrupted(tmp_path, max_failures=1)
    outcome = await selective_strategies.worker_retry(
        run_dir, model=ScriptedModel(), output_root=tmp_path / "strategies")
    assert (outcome["status"], outcome["stop_reason"]) == ("completed", "complete_task")
    # The checkpoint predates the denial, so the replayed read is denied once more and
    # the worker's own re-read is what completes it.
    [branch] = outcome["branch_dirs"]
    assert len(of_type(branch_events(branch), "tool.failure_injected")) == 1


# S6
@pytest.mark.asyncio
async def test_both_fault_modes_cost_the_same(tmp_path):
    by_mode = {}
    for mode in ("immediate", "timeout"):
        run_dir = await interrupted(tmp_path / mode, mode=mode)
        outcomes = await run_all(run_dir, tmp_path / mode / "strategies")
        by_mode[mode] = {name: costs(outcome) for name, outcome in outcomes.items()}
    assert list(by_mode["immediate"]) == NAMES
    assert by_mode["immediate"] == by_mode["timeout"]


# S7
@pytest.mark.asyncio
async def test_worker_recovery_recovers_every_faulted_worker(tmp_path):
    run_dir = await interrupted(tmp_path, docs=("doc2", "doc3"))
    outcome = await selective_strategies.worker_recovery(
        run_dir, model=ScriptedModel(), output_root=tmp_path / "strategies")
    assert (outcome["status"], outcome["answer"]) == ("completed", FULL_ANSWER)
    assert outcome["recover_calls"] == 3
    cache = selective.load_cache(tmp_path / "strategies" / "worker_recovery" / "cache.json")
    assert {agent: entry["origin"] for agent, entry in cache.items()} == {
        "batch1-worker1": "sibling", "batch1-worker2": "recovered",
        "batch1-worker3": "recovered"}
    # Read from the replay's own trace, not from the outcome under test.
    replay = branch_events(outcome["branch_dirs"][-1])
    assert not of_type(replay, "worker.started")
    assert sorted(e["assignment_id"] for e in of_type(replay, "worker.reused")) == sorted(cache)


# S8
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["batch_replay", "batch_replay_cached", "worker_recovery",
                                  "worker_retry"])
async def test_faults_in_two_batches_are_refused(tmp_path, name):
    # interrupt_on_fault="batch" stops at the first faulted batch, so a second faulted
    # batch is reachable only with interruption off.
    result, run_dir = await attempt(tmp_path, TwoBatchLead(), docs=("doc2", "doc3"),
                                    interrupt="never")
    assert result["status"] == "completed"
    assert {s["batch"] for s in selective.find_tool_fault_sites(run_dir)} == {1, 2}
    with pytest.raises(NotImplementedError, match=r"batches \[1, 2\]"):
        await STRATEGIES[name](run_dir, model=ScriptedModel(), output_root=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# S9
@pytest.mark.asyncio
async def test_no_recovery_touches_nothing(tmp_path, monkeypatch):
    run_dir = await interrupted(tmp_path)
    before = tree_digest(run_dir)

    def untouched(*args, **kwargs):
        raise AssertionError("no_recovery called recover()")

    monkeypatch.setattr(selective_strategies, "recover", untouched)
    outcome = await selective_strategies.no_recovery(
        run_dir, model=ScriptedModel(), output_root=tmp_path / "strategies")
    assert (outcome["recover_calls"], outcome["branch_dirs"]) == (0, [])
    assert (outcome["status"], outcome["stop_reason"]) == ("interrupted", "fault_injected")
    assert not (tmp_path / "strategies").exists()
    assert tree_digest(run_dir) == before


# S10
@pytest.mark.asyncio
async def test_faults_on_worker_retry_does_not_reinterrupt(tmp_path, monkeypatch):
    run_dir = await interrupted(tmp_path, max_failures=1)
    built = []

    def research_graph(*args, **kwargs):
        built.append(args)
        raise AssertionError("a worker recovery built the research graph")

    # recover() imports build_research at call time, so this is the one it would use.
    monkeypatch.setattr("multi_agent_research.graphs.research.build_research", research_graph)
    outcome = await selective_strategies.worker_retry(
        run_dir, model=ScriptedModel(), output_root=tmp_path / "strategies")
    assert built == []
    assert (outcome["status"], outcome["stop_reason"]) == ("completed", "complete_task")
    [branch] = outcome["branch_dirs"]
    recovery = json.loads((Path(branch) / "recovery.json").read_text())
    assert (recovery["scope"]["kind"], recovery["faults_disabled"]) == ("worker", False)
    inherited = selective.record(branch, "config")["tool_failure"]
    assert (inherited["enabled"], inherited["interrupt_on_fault"]) == (True, "batch")
    # The finish_node condition would hold here; it is the worker graph that never asks.
    events = branch_events(branch)
    assert of_type(events, "tool.failure_injected")
    assert not of_type(events, "attempt.interrupted")
