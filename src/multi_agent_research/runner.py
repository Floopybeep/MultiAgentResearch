import asyncio
import json
import time

from langchain_core.messages import HumanMessage, SystemMessage

from . import prompts
from .graphs.research import build_research
from .observability.events import now
from .runtime import Runtime
from .storage.checkpoints import checkpoint_store


async def run_research(query, config, model, search, fetcher):
    if not query.strip():
        raise ValueError("Query cannot be empty")
    runtime = Runtime(config, model, search, fetcher)
    started = time.monotonic()
    try:
        runtime.db.record("prompts", prompts.hashes())
        runtime.event("run.started", "lead", {"query": query, "prompt_hashes": prompts.hashes()})
        async with checkpoint_store(runtime.root / "checkpoints.sqlite") as saver:
            graph = build_research(runtime, saver)
            try:
                state = await asyncio.wait_for(
                    graph.ainvoke(
                        {
                            "messages": [
                                SystemMessage(
                                    content=prompts.load("lead")
                                    + f"\nCurrent UTC date: {now()[:10]}."
                                    + f"\nLimits: {config.max_lead_turns} lead turns, {config.max_batches} batches, "
                                    f"{config.max_workers_per_batch} workers per batch."
                                ),
                                HumanMessage(content=query),
                            ],
                            "results": {},
                            "batches": 0,
                            "turns": 0,
                        },
                        {
                            "configurable": {"thread_id": runtime.run_id},
                            "recursion_limit": 2 * config.max_lead_turns + 6,
                        },
                    ),
                    config.run_timeout_seconds,
                )
            except Exception as exc:
                state = {
                    "status": "failed",
                    "stop_reason": f"{type(exc).__name__}: {runtime.log.redact(str(exc))}",
                }
                if isinstance(exc, TimeoutError):
                    state = {"status": "budget_exhausted", "stop_reason": "run_timeout"}
            snapshot = await graph.aget_state({"configurable": {"thread_id": runtime.run_id}})
            # Retain completed work if the next node failed or the run timed out.
            if snapshot.values:
                state = {**snapshot.values, **state}
            checkpoint_id = (
                snapshot.config.get("configurable", {}).get("checkpoint_id")
                if snapshot.config
                else None
            )
        result = dict(
            run_id=runtime.run_id,
            output_dir=str(runtime.root),
            status=state.get("status", "failed"),
            stop_reason=state.get("stop_reason"),
            worker_results=state.get("results", {}),
            usage=runtime.usage.as_dict(),
            duration_seconds=time.monotonic() - started,
            checkpoint_id=checkpoint_id,
        )
        for key, filename in (("draft", "draft.md"), ("report", "report.md")):
            if state.get(key):
                (runtime.root / filename).write_text(state[key])
                result[f"{key}_path"] = str(runtime.root / filename)
        (runtime.root / "sources.json").write_text(
            json.dumps({k: s.model_dump() for k, s in runtime.sources.items()}, indent=2)
        )
        runtime.event(
            "run.finished", "system", result, [ids[-1] for ids in runtime.observed.values() if ids]
        )
        runtime.db.record("run", result)
        (runtime.root / "run.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        runtime.close()
