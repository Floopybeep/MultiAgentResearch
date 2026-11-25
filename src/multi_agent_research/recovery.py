"""Call-indexed LangGraph replay. Source attempts are immutable during recovery."""

import argparse
import asyncio
import json
import shutil
import sqlite3
from contextlib import closing
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from .storage.checkpoints import checkpoint_store

_boundary = ContextVar("recovery_boundary", default=None)


class ModelState(TypedDict, total=False):
    role: str
    agent: str
    messages: list[Any]
    model_config: dict
    response: Any


def build_model_call(runtime, saver):
    async def execute(state):
        config = type(getattr(runtime.config, state["role"])).model_validate(state["model_config"])
        response = await runtime._call_model(
            state["role"], state["agent"], state["messages"], [], model_config=config,
        )
        return {"response": response}

    graph = StateGraph(ModelState)
    graph.add_node("model", runtime.recovery.node(execute, saver, {"kind": "model"}))
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    return graph.compile(checkpointer=saver)


class RecoveryPoints:
    def __init__(self, runtime):
        self.runtime = runtime
        self.branch_id = "br00"
        self.lineage_id = runtime.run_id
        self.sequences = {}
        runtime.db.connection.executescript("""
            CREATE TABLE IF NOT EXISTS recovery_points (
                recovery_point_id TEXT PRIMARY KEY,
                branch_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                call_seq INTEGER NOT NULL,
                call_name TEXT NOT NULL,
                body TEXT NOT NULL,
                UNIQUE(branch_id, agent_id, call_seq)
            );
            CREATE INDEX IF NOT EXISTS recovery_by_call
                ON recovery_points(agent_id, call_name);
        """)

    def node(self, function, saver, descriptor):
        async def wrapped(state, config: RunnableConfig):
            # LangGraph supplies the enclosing graph's exact checkpoint in this map.
            # The node's checkpoint_ns includes its task suffix, which is not the
            # namespace of the enclosing graph's checkpoint.
            configurable = config["configurable"]
            namespace = configurable.get("checkpoint_ns", "").rpartition("|")[0]
            checkpoint_id = configurable.get("checkpoint_map", {}).get(namespace)
            if not checkpoint_id:
                raise RuntimeError("LangGraph did not supply an enclosing checkpoint ID")
            locator = {"configurable": {
                "thread_id": configurable["thread_id"], "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            # Judge/verifier one-call graphs are invoked without a recursion_limit.
            }, "recursion_limit": config.get("recursion_limit", 25)}
            token = _boundary.set((saver, locator, descriptor))
            try:
                return await function(state)
            finally:
                _boundary.reset(token)
        return wrapped

    async def before_call(self, agent, kind, name, request):
        boundary = _boundary.get()
        if boundary is None:
            raise RuntimeError("Call has no resumable graph boundary")
        saver, locator, descriptor = boundary
        # Never substitute the latest checkpoint: historical replay may have a
        # different head. Sync durability makes this exact checkpoint available.
        if await saver.aget_tuple(locator) is None:
            raise RuntimeError("Pre-call checkpoint has not been persisted")
        seq = self.sequences.get(agent, 0) + 1
        self.sequences[agent] = seq
        point_id = f"{self.lineage_id}/{self.branch_id}/{agent}/call{seq:04d}"
        runtime = self.runtime
        point = {
            "version": 1, "recovery_point_id": point_id,
            "lineage_id": self.lineage_id, "branch_id": self.branch_id,
            "agent_id": agent, "call_seq": seq, "call_kind": kind, "call_name": name,
            "call_id": request.get("id", point_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "graph_config": locator, "graph": descriptor,
            "checkpoint_file": "calls.sqlite" if descriptor["kind"] == "model" else "checkpoints.sqlite",
            "request_ref": runtime.artifacts.put(runtime.log.redact(request)),
            "runtime_snapshot_ref": runtime.artifacts.put(runtime.log.redact(runtime.recovery_snapshot())),
        }
        with runtime.db.connection:
            runtime.db.connection.execute(
                "INSERT INTO recovery_points VALUES (?, ?, ?, ?, ?, ?)",
                (point_id, self.branch_id, agent, seq, name, json.dumps(point)),
            )
        runtime.event("checkpoint.saved", agent, point,
                      runtime.observed.get(agent, [])[-1:], recovery_point_id=point_id)
        return point_id

    async def auxiliary_model(self, role, agent, messages, model_config):
        # Judge/verifier calls are independent operations, outside the QA state
        # machine. They have their own resumable one-call graph.
        async with checkpoint_store(self.runtime.root / "calls.sqlite") as saver:
            graph = build_model_call(self.runtime, saver)
            state = await graph.ainvoke({
                "role": role, "agent": agent, "messages": messages,
                "model_config": model_config.model_dump(mode="json"),
            }, {"configurable": {
                "thread_id": f"{self.runtime.run_id}:{agent}:{uuid4().hex}",
                "checkpoint_ns": "",
            }}, durability="sync")
            return state["response"]


def list_recovery_points(run_dir: Path, *, agent: str | None = None) -> list[dict]:
    with closing(sqlite3.connect(
        f"{(Path(run_dir) / 'events.sqlite').resolve().as_uri()}?mode=ro", uri=True,
    )) as db:
        sql = "SELECT body FROM recovery_points"
        rows = db.execute(sql + (" WHERE agent_id=?" if agent else "") + " ORDER BY rowid",
                          (agent,) if agent else ())
        return [json.loads(row[0]) for row in rows]


def _backup(source, destination):
    with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


async def recover(run_dir: Path, recovery_point_id: str, *, model=None,
                  output_dir: Path | None = None) -> dict:
    """Replay a stopped attempt into a new directory; never overwrite its history.

    Lead points resume the Lead chain. Worker points resume only that worker.
    Parallel delegation points resume the whole batch. Judge points replay only
    their model request. No automatic downstream result replacement.
    """
    from .config import RunConfig
    from .graphs.research import build_research
    from .graphs.worker import build_worker
    from .models.adapter import OpenAIChatCompletionsAdapter
    from .runtime import Runtime
    from .tools.documents import LocalDocument, OracleDocuments

    source = Path(run_dir).resolve()
    with closing(sqlite3.connect(f"{(source / 'events.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        row = db.execute("SELECT body FROM recovery_points WHERE recovery_point_id=?",
                         (recovery_point_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown recovery point: {recovery_point_id}")
        point = json.loads(row[0])
        if point["version"] != 1:
            raise ValueError("Unsupported recovery point version")
        def record(key):
            row = db.execute("SELECT body FROM records WHERE key=?", (key,)).fetchone()
            if row is None:
                raise ValueError(f"Missing recovery record: {key}")
            return json.loads(row[0])
        if record("execution_status") != "stopped":
            raise ValueError("Recovery requires a stopped attempt; stop its execution first")
        config = RunConfig.model_validate(record("config"))
        document_refs = record("recovery_documents")
        usage = record("recovery_usage")
    model = model if model is not None else OpenAIChatCompletionsAdapter()
    branch = "br" + uuid4().hex[:12]
    destination = Path(output_dir) if output_dir else source.parent / f"recovery-{branch}"
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Recovery output must be outside the source attempt directory")
    # Allocate before copying; an existing directory must never be overwritten.
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / "artifacts", destination / "artifacts")
    for name in ("events.sqlite", "checkpoints.sqlite", "calls.sqlite"):
        if (source / name).exists():
            _backup(source / name, destination / name)
    from .storage.artifacts import ArtifactStore
    artifacts = ArtifactStore(destination / "artifacts")
    documents = OracleDocuments([LocalDocument.model_validate(artifacts.get(ref))
                                 for ref in document_refs])
    runtime = Runtime(config, model, documents,
                      root=destination, restore=True)
    runtime.recovery.lineage_id = point["lineage_id"]
    runtime.recovery.branch_id = branch
    descriptor = point["graph"]
    started = asyncio.get_running_loop().time()
    result = None
    try:
        runtime.restore_recovery_snapshot(artifacts.get(point["runtime_snapshot_ref"]))
        runtime.restore_usage(usage)
        runtime.event("recovery.started", "system", {
            "source_dir": str(source), "source_recovery_point": recovery_point_id,
            "branch_id": branch, "scope": descriptor,
        })
        async with checkpoint_store(destination / point["checkpoint_file"]) as saver:
            if descriptor["kind"] == "lead":
                graph = build_research(runtime, saver)
                timeout = config.run_timeout_seconds
            elif descriptor["kind"] == "worker":
                graph = build_worker(runtime, point["agent_id"], saver,
                                     document_id=descriptor["document_id"])
                timeout = config.worker_timeout_seconds
            elif descriptor["kind"] == "model":
                graph = build_model_call(runtime, saver)
                timeout = config.call_timeout_seconds
            else:
                raise ValueError("Unknown recovery graph")
            snapshot = await graph.aget_state(point["graph_config"])
            if not snapshot.next:
                raise ValueError("Recovery point has no pending operation")
            state = await asyncio.wait_for(graph.ainvoke(
                None, point["graph_config"], durability="sync",
            ), timeout)
            result = {
                "status": state.get("status", state.get("result", {}).get("status", "completed")),
                "answer": state.get("answer"), "worker_result": state.get("result"),
                "stop_reason": state.get("stop_reason", state.get("result", {}).get("stop_reason")),
                "worker_results": state.get("results", {}),
                "response": state["response"].model_dump(mode="json") if "response" in state else None,
            }
    except Exception as exc:
        result = {"status": "failed", "error": runtime.log.redact(f"{type(exc).__name__}: {exc}")}
    finally:
        try:
            if result is not None:
                result.update(
                    source_recovery_point=recovery_point_id, branch_id=branch,
                    run_id=runtime.run_id, output_dir=str(destination), scope=descriptor,
                    usage=runtime.usage.as_dict(),
                    duration_seconds=asyncio.get_running_loop().time() - started,
                )
                result = runtime.log.redact(result)
                runtime.event("recovery.finished", "system", result)
                runtime.db.record("recovery", result)
                (destination / "recovery.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                if result.get("answer"):
                    (destination / "answer.txt").write_text(runtime.log.redact(result["answer"]),
                                                            encoding="utf-8")
        finally:
            runtime.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="List pre-call checkpoints or replay a stopped attempt")
    parser.add_argument("run_dir", type=Path, help="Attempt or recovery directory")
    parser.add_argument("--agent", help="Filter the checkpoint list")
    parser.add_argument("--checkpoint", help="Recovery-point ID to replay; omit to list")
    parser.add_argument("--output-dir", type=Path, help="New directory for replay output")
    args = parser.parse_args()
    try:
        if args.checkpoint:
            result = asyncio.run(recover(args.run_dir, args.checkpoint,
                                         output_dir=args.output_dir))
            print(json.dumps(result, indent=2))
            if result["status"] != "completed":
                raise SystemExit(1)
        else:
            for point in list_recovery_points(args.run_dir, agent=args.agent):
                print(f'{point["recovery_point_id"]}\t{point["call_kind"]}\t'
                      f'{point["call_name"]}\t{point["created_at"]}')
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Recovery failed: {exc}\n")


if __name__ == "__main__":
    main()
