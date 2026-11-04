"""Accidental read_document failures: targeting, timing and traces, with no API calls."""

import asyncio
import os
import subprocess
import sys
import time

import pytest
from pydantic import ValidationError

from multi_agent_research.config import RunConfig, ToolFailureConfig
from multi_agent_research.observability.trace_reader import FAILURE_INJECTED, TraceReader
from multi_agent_research.runtime import Runtime
from multi_agent_research.tools import tool_failures
from multi_agent_research.tools.documents import LocalDocument, OracleDocuments

PAGE_CHARS = 100
TEXT = "".join(chr(ord("a") + i % 26) for i in range(500))


def build(tmp_path, name="run", **fault):
    """A Runtime over two fixture documents, with the tool timeout shrunk for tests."""
    documents = OracleDocuments([
        LocalDocument(
            document_id=f"doc{i}", title=f"Fixture {i}",
            url=f"https://example.invalid/{i}", text=TEXT,
        )
        for i in (1, 2)
    ])
    config = RunConfig(
        max_document_chars=PAGE_CHARS,
        call_timeout_seconds=0.05,
        tool_failure=fault,
        output_dir=tmp_path / "runs",
    )
    return Runtime(config, None, documents, root=tmp_path / name)


async def through_call_tool(runtime, agent, document_id, offset=0):
    """Exercise the same path graphs/worker.py uses, including call_tool's wait_for."""
    call = {
        "id": f"{agent}-{document_id}-{offset}",
        "name": "read_document",
        "args": {"document_id": document_id, "offset": offset},
    }

    async def handler():
        return await runtime.read_document(document_id, offset, agent=agent)

    return await runtime.call_tool(agent, call, handler)


# --- configuration -----------------------------------------------------------


def test_fault_is_disabled_by_default_and_old_configs_still_load():
    assert RunConfig().tool_failure.enabled is False
    for path in ("configs/baseline.yaml", "configs/baseline-pinned.yaml"):
        assert RunConfig.load(path).tool_failure.enabled is False
    # The fault config must stay loadable in whichever experimental condition it
    # is parked in. Neither `enabled` nor `mode` is pinned here: both are the
    # knobs the smoke tests turn. The delta between conditions is asserted by
    # test_the_two_smoke_conditions_differ_only_in_enabled instead.
    smoke = RunConfig.load("configs/faults-tool-read-denial.yaml").tool_failure
    assert smoke.mode in ("immediate", "timeout")
    assert smoke.document_ids and smoke.offsets      # a target is configured
    assert smoke.max_failures == 1 and smoke.persistent is False


def test_the_two_smoke_conditions_differ_only_in_enabled():
    """The clean and fault runs must be one flipped flag apart, nothing else."""
    import copy

    import yaml

    raw = yaml.safe_load(open("configs/faults-tool-read-denial.yaml"))
    # Set both conditions explicitly, so the check holds whichever one the file
    # is currently parked in.
    clean_raw = copy.deepcopy(raw)
    clean_raw["tool_failure"]["enabled"] = False
    faulted_raw = copy.deepcopy(raw)
    faulted_raw["tool_failure"]["enabled"] = True
    clean = RunConfig.model_validate(clean_raw).model_dump(mode="json")
    faulted = RunConfig.model_validate(faulted_raw).model_dump(mode="json")

    assert [k for k in clean if clean[k] != faulted[k]] == ["tool_failure"]
    assert [
        k for k in clean["tool_failure"]
        if clean["tool_failure"][k] != faulted["tool_failure"][k]
    ] == ["enabled"]
    # And the clean condition is the pinned baseline plus an inert fault block.
    pinned = RunConfig.load("configs/baseline-pinned.yaml").model_dump(mode="json")
    assert [k for k in pinned if pinned[k] != clean[k]] == ["tool_failure"]


def test_timeout_margin_must_exceed_one_so_the_fault_cannot_be_disarmed():
    with pytest.raises(ValidationError):
        ToolFailureConfig(timeout_margin=1.0)
    assert tool_failures.delay_seconds(ToolFailureConfig(timeout_margin=1.5), 60) == 90


def test_total_denial_requires_an_explicit_opt_in():
    with pytest.raises(ValidationError, match="allow_total_denial"):
        ToolFailureConfig(enabled=True, max_failures=None)
    # Opted in, or narrowed to named documents, both validate.
    ToolFailureConfig(enabled=True, max_failures=None, allow_total_denial=True)
    ToolFailureConfig(enabled=True, max_failures=None, document_ids=["doc1"])


def test_offsets_must_be_nonnegative():
    with pytest.raises(ValidationError):
        ToolFailureConfig(offsets=[-1])


# --- 1. disabled behaves like the clean pipeline ------------------------------


@pytest.mark.asyncio
async def test_disabled_fault_returns_the_unchanged_page(tmp_path):
    runtime = build(tmp_path)
    page = await runtime.read_document("doc1", 0)
    assert page == runtime.documents.read("doc1", 0, PAGE_CHARS)
    assert page["text"] == TEXT[:PAGE_CHARS]
    assert runtime.tool_failure_state.failures == 0
    assert runtime.observed == {}


# --- 2, 3, 4. the two modes ---------------------------------------------------


@pytest.mark.asyncio
async def test_immediate_mode_gives_the_worker_a_structured_error(tmp_path):
    runtime = build(tmp_path, enabled=True, mode="immediate", document_ids=["doc1"])
    result = await through_call_tool(runtime, "batch1-worker1", "doc1")
    assert result == {
        "error": "ToolUnavailableError", "message": "read_document is unavailable",
    }
    assert "text" not in result and "document_id" not in result


@pytest.mark.asyncio
async def test_timeout_mode_fires_the_real_wait_for_timeout(tmp_path):
    # delay = 0.05 * 20 = 1.0s, so call_tool's wait_for must interrupt it.
    runtime = build(
        tmp_path, enabled=True, mode="timeout", document_ids=["doc1"], timeout_margin=20,
    )
    started = time.monotonic()
    result = await through_call_tool(runtime, "batch1-worker1", "doc1")
    elapsed = time.monotonic() - started
    assert result == {"error": "TimeoutError", "message": ""}
    assert 0.05 <= elapsed < 0.9, "wait_for must cut the 1.0s delay short"


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_while_a_faulted_read_waits(tmp_path):
    runtime = build(
        tmp_path, enabled=True, mode="timeout", document_ids=["doc1"], timeout_margin=20,
    )
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    beat = asyncio.create_task(ticker())
    result = await through_call_tool(runtime, "batch1-worker1", "doc1")
    beat.cancel()
    assert result["error"] == "TimeoutError"
    assert ticks > 0, "a blocking sleep would starve every other coroutine"
    # doc2 is still readable afterwards, so the loop was never wedged.
    assert (await runtime.read_document("doc2", 0))["text"] == TEXT[:PAGE_CHARS]


# --- 5, 6, 12, 13. targeting --------------------------------------------------


@pytest.mark.asyncio
async def test_only_targeted_documents_fail(tmp_path):
    runtime = build(
        tmp_path, enabled=True, document_ids=["doc1"], max_failures=None,
    )
    with pytest.raises(tool_failures.ToolUnavailableError):
        await runtime.read_document("doc1", 0)
    assert (await runtime.read_document("doc2", 0))["text"] == TEXT[:PAGE_CHARS]


@pytest.mark.asyncio
async def test_only_targeted_offsets_fail(tmp_path):
    runtime = build(
        tmp_path, enabled=True, document_ids=["doc1"], offsets=[100], max_failures=None,
    )
    assert (await runtime.read_document("doc1", 0))["offset"] == 0
    with pytest.raises(tool_failures.ToolUnavailableError):
        await runtime.read_document("doc1", 100)
    assert (await runtime.read_document("doc1", 200))["offset"] == 200


@pytest.mark.asyncio
async def test_an_absent_target_never_fires_and_is_not_an_error(tmp_path):
    runtime = build(tmp_path, enabled=True, document_ids=["doc_absent"], offsets=[4242])
    for document_id in ("doc1", "doc2"):
        assert (await runtime.read_document(document_id, 0))["document_id"] == document_id
    assert runtime.tool_failure_state.failures == 0
    assert runtime.observed == {}


@pytest.mark.asyncio
async def test_a_naturally_failing_read_propagates_without_consuming_a_slot(tmp_path):
    runtime = build(tmp_path, enabled=True, max_failures=1)
    with pytest.raises(ValueError, match="out of range"):
        await runtime.read_document("doc1", 10_000)
    with pytest.raises(ValueError, match="outside this question"):
        await runtime.read_document("doc_missing", 0)
    assert runtime.tool_failure_state.failures == 0
    # The slot survived for a read that would otherwise have succeeded.
    with pytest.raises(tool_failures.ToolUnavailableError):
        await runtime.read_document("doc1", 0)
    assert runtime.tool_failure_state.failures == 1


# --- 7, 8. transient versus persistent ----------------------------------------


@pytest.mark.asyncio
async def test_transient_denies_only_the_first_attempt(tmp_path):
    runtime = build(
        tmp_path, enabled=True, document_ids=["doc1"], persistent=False, max_failures=None,
    )
    with pytest.raises(tool_failures.ToolUnavailableError):
        await runtime.read_document("doc1", 0)
    assert (await runtime.read_document("doc1", 0))["text"] == TEXT[:PAGE_CHARS]
    # Recovery is scoped to the page, so a different offset still fails once.
    with pytest.raises(tool_failures.ToolUnavailableError):
        await runtime.read_document("doc1", 100)
    assert (await runtime.read_document("doc1", 100))["offset"] == 100


@pytest.mark.asyncio
async def test_persistent_keeps_failing_every_attempt(tmp_path):
    runtime = build(
        tmp_path, enabled=True, document_ids=["doc1"], persistent=True, max_failures=None,
    )
    for _ in range(3):
        with pytest.raises(tool_failures.ToolUnavailableError):
            await runtime.read_document("doc1", 0)
    assert runtime.tool_failure_state.failures == 3


@pytest.mark.asyncio
async def test_transient_recovery_is_per_run_so_a_second_agent_inherits_it(tmp_path):
    runtime = build(
        tmp_path, enabled=True, document_ids=["doc1"], persistent=False, max_failures=None,
    )
    with pytest.raises(tool_failures.ToolUnavailableError):
        await runtime.read_document("doc1", 0, agent="batch1-worker1")
    # A re-delegated worker reads the page the first worker was denied.
    page = await runtime.read_document("doc1", 0, agent="batch2-worker1")
    assert page["text"] == TEXT[:PAGE_CHARS]
    assert runtime.tool_failure_state.failures == 1


@pytest.mark.asyncio
async def test_a_persistent_fault_stops_at_a_finite_cap(tmp_path):
    runtime = build(
        tmp_path, enabled=True, document_ids=["doc1"], persistent=True, max_failures=2,
    )
    for _ in range(2):
        with pytest.raises(tool_failures.ToolUnavailableError):
            await runtime.read_document("doc1", 0)
    # The cap is reached, so the page becomes readable again despite persistent.
    assert (await runtime.read_document("doc1", 0))["text"] == TEXT[:PAGE_CHARS]


# --- 9, 10. counting and concurrency ------------------------------------------


@pytest.mark.asyncio
async def test_max_failures_caps_sequential_denials(tmp_path):
    runtime = build(tmp_path, enabled=True, max_failures=3, persistent=True)
    denied = 0
    for offset in (0, 100, 200, 300, 400):
        try:
            await runtime.read_document("doc1", offset)
        except tool_failures.ToolUnavailableError:
            denied += 1
    assert denied == 3
    assert runtime.tool_failure_state.failures == 3


@pytest.mark.asyncio
async def test_concurrent_reads_cannot_overrun_the_shared_cap(tmp_path):
    # Slots are reserved before the delay, so eight racing reads still yield two.
    runtime = build(
        tmp_path, enabled=True, mode="timeout", max_failures=2,
        persistent=True, timeout_margin=1.5,
    )
    reads = [
        through_call_tool(runtime, f"batch1-worker{i % 3 + 1}", f"doc{i % 2 + 1}", offset)
        for i, offset in enumerate([0, 100, 200, 300, 0, 100, 200, 300])
    ]
    results = await asyncio.gather(*reads, return_exceptions=True)
    timed_out = [r for r in results if isinstance(r, dict) and r.get("error") == "TimeoutError"]
    assert len(timed_out) == 2
    assert runtime.tool_failure_state.failures == 2
    runtime.close()
    assert len(TraceReader(runtime.root).failures()) == 2


# --- 11. cancellation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_call_cancelled_mid_delay_still_leaves_the_fault_recorded(tmp_path):
    runtime = build(
        tmp_path, enabled=True, mode="timeout", document_ids=["doc1"], timeout_margin=100,
    )
    task = asyncio.create_task(runtime.read_document("doc1", 0, agent="batch1-worker1"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    runtime.close()
    failures = TraceReader(runtime.root).failures()
    assert len(failures) == 1
    assert failures[0]["mode"] == "timeout"
    assert failures[0]["delay_seconds"] == pytest.approx(5.0)


# --- 14. reproducibility ------------------------------------------------------


def test_explicit_targeting_is_deterministic():
    config = ToolFailureConfig(enabled=True, document_ids=["doc1"], failure_probability=1.0)
    state = tool_failures.ToolFailureState()
    for _ in range(5):
        decision = tool_failures.decide(
            config, state, key="qk", document_id="doc1", offset=0,
        )
        assert decision.fail and decision.reason == "selected"


SELECTION_SCRIPT = """
from multi_agent_research.config import ToolFailureConfig
from multi_agent_research.tools.tool_failures import selected
config = ToolFailureConfig(enabled=True, failure_probability=0.5, seed=7)
print("".join(
    "1" if selected(config, key="qk", document_id=f"doc{i}", offset=0, attempt=1) else "0"
    for i in range(64)
))
"""


def test_hash_selection_reproduces_across_processes_and_hash_seeds():
    verdicts = set()
    for hash_seed in ("0", "1", "12345"):
        completed = subprocess.run(
            [sys.executable, "-c", SELECTION_SCRIPT],
            capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
        )
        verdicts.add(completed.stdout.strip())
    assert len(verdicts) == 1, f"PYTHONHASHSEED changed selection: {verdicts}"
    only = verdicts.pop()
    assert set(only) == {"0", "1"}, "a 0.5 probability should select some but not all"


def test_question_key_separates_questions_by_document_set():
    assert tool_failures.question_key(["a", "b"]) == tool_failures.question_key(["b", "a"])
    assert tool_failures.question_key(["a", "b"]) != tool_failures.question_key(["a", "c"])


# --- 15, 16. trace recording and offline resolution ---------------------------


@pytest.mark.asyncio
async def test_the_original_page_is_recorded_but_never_delivered(tmp_path):
    runtime = build(
        tmp_path, enabled=True, mode="immediate", document_ids=["doc1"], offsets=[100],
    )
    result = await through_call_tool(runtime, "batch1-worker1", "doc1", 100)
    assert result["error"] == "ToolUnavailableError"
    runtime.close()

    reader = TraceReader(runtime.root)
    (failure,) = reader.failures()
    assert failure["tool"] == "read_document"
    assert failure["mode"] == "immediate"
    assert failure["document_id"] == "doc1"
    assert failure["offset"] == 100
    assert failure["agent"] == "batch1-worker1"
    assert failure["failure_number"] == 1
    assert failure["attempt"] == 1
    assert failure["persistent"] is True
    assert failure["delay_seconds"] is None

    # The withheld page is recoverable from the trace, though the worker never saw it.
    original = reader.artifacts.get(failure["original_artifact_ref"])
    assert original["text"] == TEXT[100:200]
    delivered = [e["payload"] for e in reader.events("tool.error")]
    assert all("text" not in payload for payload in delivered)


@pytest.mark.asyncio
async def test_the_resolver_reads_requests_retries_and_switches_offline(tmp_path):
    runtime = build(
        tmp_path, enabled=True, mode="immediate", document_ids=["doc1"], max_failures=None,
    )
    await through_call_tool(runtime, "batch1-worker1", "doc1", 0)
    await through_call_tool(runtime, "batch1-worker1", "doc1", 0)  # retry
    await through_call_tool(runtime, "batch1-worker1", "doc2", 0)  # switched document
    runtime.close()

    reader = TraceReader(runtime.root)
    reads = [(agent, doc, offset) for agent, doc, offset, _ in reader.reads()]
    assert reads == [
        ("batch1-worker1", "doc1", 0),
        ("batch1-worker1", "doc1", 0),
        ("batch1-worker1", "doc2", 0),
    ]
    assert len(reader.failures()) == 2
    assert [e["event_type"] for e in reader.events(FAILURE_INJECTED)] == [FAILURE_INJECTED] * 2
    # Stage 4: the worker received an error for the denied reads, a page for doc2.
    assert len(reader.events("tool.error")) == 2
    assert len(reader.events("tool.result")) == 1
    assert reader.records()["config"]["tool_failure"]["enabled"] is True


@pytest.mark.asyncio
async def test_a_configured_fault_that_is_never_reached_records_no_failure(tmp_path):
    runtime = build(tmp_path, enabled=True, document_ids=["doc_absent"])
    await through_call_tool(runtime, "batch1-worker1", "doc1", 0)
    runtime.close()
    reader = TraceReader(runtime.root)
    # Stage 1: configured in the run record, but no fault ever triggered.
    assert reader.records()["config"]["tool_failure"]["enabled"] is True
    assert reader.failures() == []
    assert len(reader.reads()) == 1


# --- end to end through the real worker graph, still offline ------------------


class ScriptedModel:
    """Drives the real Lead/worker graphs with no API calls."""

    def __init__(self):
        self.turns = {}
        self.worker_tool_messages = []

    async def invoke(self, role, agent, messages, tools, config):
        self.turns[agent] = self.turns.get(agent, 0) + 1
        turn = self.turns[agent]

        def response(*calls):
            from langchain_core.messages import AIMessage
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
                for i, (name, args) in enumerate(calls)
            ], usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

        if role == "lead":
            if turn == 1:
                return response(("memory_write", {"plan": "Read doc1, then doc2."}))
            if turn == 2:
                return response(("run_blocking_subagent", {"prompt": "Read doc1 and doc2.", "document_id": "doc1"}))
            return response(("submit_answer", {"answer": r"\boxed{42}"}))

        assert role == "worker"
        self.worker_tool_messages.extend(
            m.content for m in messages if m.__class__.__name__ == "ToolMessage"
        )
        if turn == 1:
            return response(("read_document", {"document_id": "doc1", "offset": 0}))
        if turn == 2:
            return response(("read_document", {"document_id": "doc2", "offset": 0}))
        if turn == 3:
            return response(("read_document", {"document_id": "doc1", "offset": 0}))
        return response(("complete_task", {
            "findings": "doc1 gives the value 42.", "document_ids": ["doc1"],
        }))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_enabled", [False, True])
async def test_worker_cannot_read_another_assignment_after_a_fault(tmp_path, fault_enabled):
    from multi_agent_research.runner import run_qa

    # Distinct bodies make unauthorized content exposure observable.
    bodies = {"doc1": "ASSIGNED-" + TEXT, "doc2": "UNASSIGNED-" + TEXT}
    documents = OracleDocuments([
        LocalDocument(
            document_id=key, title=f"Fixture {key}",
            url=f"https://example.invalid/{key}", text=body,
        )
        for key, body in bodies.items()
    ])
    config = RunConfig(
        max_document_chars=PAGE_CHARS,
        minimum_worker=1,
        output_dir=tmp_path / "runs",
        tool_failure={
            "enabled": fault_enabled, "mode": "immediate",
            "document_ids": ["doc1"], "offsets": [0], "max_failures": 1,
        },
    )
    model = ScriptedModel()
    result = await run_qa("How many?", config, model, documents)

    assert result["status"] == "completed"
    assert any('"error": "PermissionError"' in m for m in model.worker_tool_messages)
    assert not any("UNASSIGNED-" in m for m in model.worker_tool_messages)
    assert any("ASSIGNED-" in m for m in model.worker_tool_messages)
    assert any('"error": "ToolUnavailableError"' in m
               for m in model.worker_tool_messages) == fault_enabled

    reader = TraceReader(result["output_dir"])
    failures = reader.failures()
    assert len(failures) == int(fault_enabled)
    if fault_enabled:
        assert (failures[0]["document_id"], failures[0]["offset"]) == ("doc1", 0)
    # The unauthorized call is logged as an error and never returns article text.
    requests = {e["tool_call_id"]: e["payload"] for e in reader.events("tool.request")}
    errors = [e for e in reader.events("tool.error")
              if e["payload"]["error"] == "PermissionError"]
    assert len(errors) == 1
    assert requests[errors[0]["tool_call_id"]]["args"]["document_id"] == "doc2"
    pages = [e["payload"] for e in reader.events("tool.result")
             if "text" in e["payload"]]
    assert pages and all(page["document_id"] == "doc1" for page in pages)
    worker = reader.events("worker.finished")[0]["payload"]
    assert worker["status"] == "completed"
    assert worker["document_ids"] == ["doc1"]


# --- asynchronous execution invariants ----------------------------------------


@pytest.mark.asyncio
async def test_a_read_that_is_not_denied_is_never_delayed(tmp_path):
    """deny_document must return without suspending, or raise. No delay-then-success."""
    runtime = build(
        tmp_path, enabled=True, mode="timeout", document_ids=["doc1"], timeout_margin=1000,
    )
    # doc2 is not targeted: even in timeout mode the read must not suspend.
    coro = runtime.read_document("doc2", 0)
    with pytest.raises(StopIteration) as stop:
        coro.send(None)
    assert stop.value.value["text"] == TEXT[:PAGE_CHARS]

    # The targeted page suspends once, then raises rather than returning a page.
    coro = runtime.read_document("doc1", 0)
    assert coro.send(None) is not None, "timeout mode must actually suspend"
    coro.close()

    # Driven all the way past a tiny delay, with no wait_for to cancel it, the
    # denial must still raise. A `return` here would be delay-then-success,
    # invisible in the pipeline because wait_for normally cancels first.
    unguarded = build(
        tmp_path, name="unguarded", enabled=True, mode="timeout",
        document_ids=["doc1"], timeout_margin=1.5, max_failures=None,
    )
    unguarded.config.call_timeout_seconds = 0.001
    with pytest.raises(tool_failures.ToolUnavailableError):
        await unguarded.read_document("doc1", 0)


@pytest.mark.asyncio
async def test_injection_check_and_increment_stay_atomic_under_concurrency(tmp_path):
    """The teammate's single injection slot cannot be claimed twice concurrently."""
    runtime = build(tmp_path)
    runtime.config.document_injection.enabled = True
    runtime.config.document_injection.num_docs = 1
    runtime.config.document_injection.prompt = "MARK"
    pages = await asyncio.gather(*(
        runtime.read_document("doc1", offset) for offset in (0, 100, 200, 300)
    ))
    injected = [p for p in pages if p["text"].startswith("MARK")]
    assert len(injected) == 1
    assert runtime.document_injection_count == 1
