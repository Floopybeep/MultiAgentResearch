"""Batch replay of full-restart runs (eval/delegation_faults/batch_replay.py)."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from multi_agent_research.benchmark import run_frames
from multi_agent_research.config import RunConfig

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "batch_replay", ROOT / "eval" / "delegation_faults" / "batch_replay.py"
)
batch_replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_replay)

WORKERS = 3
CALL_TOKENS = 15
FAULTS = {
    "connection_drop": {"enabled": True, "num_delivered": 1},
    "result_timeout": {"enabled": True, "num_delivered": 1, "timeout_seconds": 0.05},
}


class ScriptedModel:
    """Turns follow each agent's message history, so replays behave like live runs."""

    async def invoke(self, role, agent, messages, tools, config):
        turn = 1 + sum(isinstance(m, AIMessage) for m in messages)

        def response(*calls):
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"{agent}-{turn}-{i}"}
                for i, (name, args) in enumerate(calls)
            ], usage_metadata={"input_tokens": 10, "output_tokens": 5,
                               "total_tokens": CALL_TOKENS})

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
            # Boxed so grading takes the exact-match path, not the LLM judge.
            return response(("submit_answer", {"answer": "The value is \\boxed{42}."}))
        document = f"doc{agent[-1]}"
        if turn == 1:
            return response(("read_document", {"document_id": document}))
        return response(("complete_task", {
            "findings": "The document gives the value 42.", "document_ids": [document],
        }))


def corpus(root):
    root.mkdir(parents=True)
    documents = {f"doc{i}": {"title": f"Fixture {i}", "url": f"https://example.org/{i}",
                             "file": f"doc{i}.md"} for i in range(1, WORKERS + 1)}
    for name in documents:
        (root / f"{name}.md").write_text("The value is 42.", encoding="utf-8")
    (root / "index.json").write_text(json.dumps({
        "documents": documents, "questions": {"1": list(documents)},
    }), encoding="utf-8")
    with (root / "frames.tsv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["", "Prompt", "Answer", "wiki_links", "reasoning_types"])
        writer.writerow(["1", "What is the value?", "42", "[]", "Numerical"])
    return root


async def restarted_run(tmp_path, fault):
    config = RunConfig(output_dir=tmp_path / "runs", full_restart=True,
                       **{fault: FAULTS[fault]})
    await run_frames(config, ScriptedModel(), corpus_dir=corpus(tmp_path / "corpus"),
                     question_ids=["1"])
    (question,) = batch_replay.question_dirs([tmp_path / "runs"])
    return question


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", sorted(FAULTS))
async def test_replay_preserves_the_lead_and_reruns_the_batch(tmp_path, fault):
    question = await restarted_run(tmp_path, fault)
    row = await batch_replay.replay_question(question, model=ScriptedModel())

    assert row["fault"] == fault
    assert row["replay_status"] == "completed" and row["replay_correct"] is True
    assert row["restart_correct"] is True
    # Lead memory_write + delegation turns happen before the pre-batch checkpoint.
    assert row["preserved_tokens"] == 2 * CALL_TOKENS
    ran = 1 if fault == "connection_drop" else WORKERS
    assert row["faulted_attempt_tokens"] == (2 + 2 * ran) * CALL_TOKENS
    assert row["replay_wasted_tokens"] == row["faulted_attempt_tokens"] - 2 * CALL_TOKENS
    assert row["restart_wasted_tokens"] == row["faulted_attempt_tokens"]
    # Replay: every Worker (2 calls each) plus the Lead's submit turn; exact-match grading.
    assert row["replay_tokens"] == (2 * WORKERS + 1) * CALL_TOKENS
    assert row["replay_total_tokens"] < row["restart_total_tokens"]

    events = batch_replay.read_events(row["replay_dir"])
    start = next(i for i, e in enumerate(events) if e["event_type"] == "recovery.started")
    assert not [e for e in events[start:] if e["event_type"] in batch_replay.INJECTION_EVENTS]


@pytest.mark.asyncio
async def test_replays_are_reused_unless_forced(tmp_path):
    question = await restarted_run(tmp_path, "connection_drop")
    first = await batch_replay.replay_question(question, model=ScriptedModel())
    again = await batch_replay.replay_question(question, model=ScriptedModel())
    assert again == first
    forced = await batch_replay.replay_question(question, model=ScriptedModel(), force=True)
    assert forced["replay_dir"] != first["replay_dir"]


@pytest.mark.asyncio
async def test_unfaulted_questions_are_skipped(tmp_path):
    config = RunConfig(output_dir=tmp_path / "runs", full_restart=True)
    await run_frames(config, ScriptedModel(), corpus_dir=corpus(tmp_path / "corpus"),
                     question_ids=["1"])
    (question,) = batch_replay.question_dirs([tmp_path / "runs"])
    assert await batch_replay.replay_question(question, model=ScriptedModel()) is None


@pytest.mark.asyncio
async def test_failed_replays_are_retried(tmp_path):
    question = await restarted_run(tmp_path, "connection_drop")
    first = await batch_replay.replay_question(question, model=ScriptedModel())
    record = Path(first["replay_dir"]) / "batch_replay.json"
    record.write_text(json.dumps({**first, "replay_status": "failed"}), encoding="utf-8")
    retried = await batch_replay.replay_question(question, model=ScriptedModel())
    assert retried["replay_status"] == "completed"
    assert retried["replay_dir"] != first["replay_dir"]
