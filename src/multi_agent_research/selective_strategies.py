"""Six named recoveries from a tool-faulted attempt, each reporting the same cost ledger.

Every strategy takes a stopped attempt that read_document faults interrupted (normally
via tool_failure.interrupt_on_fault="batch") and returns a StrategyOutcome, so WP6 can
iterate STRATEGIES and compare like with like. The source attempt is never written:
each strategy works in its own new directory under output_root.

Why tokens_recovery and not tokens_total. recover() restores the source attempt's
final recorded usage into the branch before it replays anything, so a branch's
recorded total is the whole source attempt plus the replay. That total depends on how
much the source attempt spent, not on what the strategy did, and worker_recovery calls
recover() twice, so no single branch total holds its cost at all. tokens_recovery is,
for each branch, its recorded total minus the total recover() restored into it,
summed over the strategy's branches. tokens_total is kept only as the cumulative figure
the final branch recorded.

Counts come from each branch's own run_id for the same reason: the branch's event log
starts as a copy of the source attempt's.
"""

from pathlib import Path
from typing import Awaitable, Callable, TypedDict

from . import selective
from .recovery import recover


class StrategyOutcome(TypedDict):
    name: str
    status: str
    stop_reason: str | None
    answer: str | None              # None unless the strategy ends with a Lead replay
    workers_executed: int           # worker.started: fresh worker runs, from the top
    workers_reused: int             # worker.reused: assignments served from the cache
    workers_resumed: int            # worker-kind recover(): resumed at the denied read
    worker_model_calls: int
    recover_calls: int
    branch_dirs: list[str]
    tokens_total: int               # recorded by the final branch, source included
    tokens_recovery: int            # spent by this strategy alone; the comparable figure


Strategy = Callable[..., Awaitable[StrategyOutcome]]


def _tokens(run_dir) -> int:
    total = selective.record(run_dir, "recovery_usage")["total"]
    return total["input_tokens"] + total["output_tokens"]


def _faulted_batch(attempt_dir) -> tuple[int, dict[str, selective.FaultSite]]:
    """The one batch the tool faults fell in, and each faulted agent's first site."""
    first = selective.earliest_fault_by_agent(selective.find_tool_fault_sites(attempt_dir))
    batches = sorted({site["batch"] for site in first.values()})
    if not batches:
        raise ValueError(f"No tool.failure_injected in {attempt_dir}")
    if len(batches) > 1:
        # A lead-batch replay resumes before one batch; a fault in a later batch would
        # be replayed from a Lead state that never saw the earlier batch's recovery.
        raise NotImplementedError(
            f"Tool faults span batches {batches}; selective recovery replays one batch"
        )
    return batches[0], first


def _workspace(output_root, name: str) -> Path:
    root = Path(output_root).resolve() / name
    root.mkdir(parents=True, exist_ok=False)  # a reused directory would mix two runs
    return root


class _Ledger:
    """recover() calls made by one strategy, all branched from the same attempt."""

    def __init__(self, name, attempt_dir, model):
        if model is None:
            # recover() would fall back to the live adapter and spend shared budget.
            raise ValueError("Pass an explicit model; None means the live adapter")
        self.name, self.source, self.model = name, Path(attempt_dir).resolve(), model
        self.restored = _tokens(self.source)  # what recover() restores into each branch
        self.results: list[dict] = []

    async def recover(self, point: str, output_dir: Path, **kwargs) -> dict:
        result = await recover(self.source, point, model=self.model,
                               output_dir=output_dir, **kwargs)
        self.results.append(result)
        return result

    def outcome(self, final: dict) -> StrategyOutcome:
        executed = reused = calls = spent = 0
        for result in self.results:
            for event in selective.own_events(result["output_dir"], result["run_id"]):
                kind = event["event_type"]
                executed += kind == "worker.started"
                reused += kind == "worker.reused"
                calls += (kind == "model.request"
                          and selective.WORKER_AGENT.fullmatch(event["agent_id"]) is not None)
            spent += _tokens(result["output_dir"]) - self.restored
        return StrategyOutcome(
            name=self.name, status=final["status"], stop_reason=final.get("stop_reason"),
            answer=final.get("answer"), workers_executed=executed, workers_reused=reused,
            workers_resumed=sum(r["scope"]["kind"] == "worker" for r in self.results),
            worker_model_calls=calls, recover_calls=len(self.results),
            branch_dirs=[r["output_dir"] for r in self.results],
            tokens_total=_tokens(self.results[-1]["output_dir"]), tokens_recovery=spent,
        )


async def no_recovery(attempt_dir, *, model, output_root) -> StrategyOutcome:
    """The interrupted attempt as it stands: the floor every strategy is measured against."""
    run = selective.record(attempt_dir, "run")
    return StrategyOutcome(
        name="no_recovery", status=run["status"], stop_reason=run["stop_reason"],
        answer=run["answer"], workers_executed=0, workers_reused=0, workers_resumed=0,
        worker_model_calls=0, recover_calls=0, branch_dirs=[],
        tokens_total=_tokens(attempt_dir), tokens_recovery=0,
    )


async def full_restart(attempt_dir, *, model, output_root) -> StrategyOutcome:
    """Replay from the Lead's first call with faults off: the ceiling."""
    ledger = _Ledger("full_restart", attempt_dir, model)
    root = _workspace(output_root, ledger.name)
    result = await ledger.recover(selective.earliest_lead_point(attempt_dir), root / "replay",
                                  disable_faults=True)
    return ledger.outcome(result)


async def _batch_replay(name, attempt_dir, model, output_root, cached) -> StrategyOutcome:
    batch, first = _faulted_batch(attempt_dir)
    ledger = _Ledger(name, attempt_dir, model)
    root = _workspace(output_root, name)
    cache_path = None
    if cached:
        # sibling_cache drops every tool-faulted agent itself; exclude names only one.
        cache_path = root / "cache.json"
        selective.write_cache(cache_path, selective.sibling_cache(attempt_dir, batch,
                                                                  exclude=min(first)))
    result = await ledger.recover(
        selective.lead_batch_point(attempt_dir, batch), root / "replay", disable_faults=True,
        replay_cache_path=None if cache_path is None else str(cache_path),
    )
    return ledger.outcome(result)


async def batch_replay(attempt_dir, *, model, output_root) -> StrategyOutcome:
    """Rerun the whole faulted batch, then the Lead, with faults off."""
    return await _batch_replay("batch_replay", attempt_dir, model, output_root, cached=False)


async def batch_replay_cached(attempt_dir, *, model, output_root) -> StrategyOutcome:
    """Rerun the faulted batch reusing the healthy siblings' deliveries."""
    return await _batch_replay("batch_replay_cached", attempt_dir, model, output_root,
                               cached=True)


async def worker_recovery(attempt_dir, *, model, output_root) -> StrategyOutcome:
    """Resume each faulted worker at its denied read, then replay the batch fully cached.

    The worker branches emit no worker.delivered, so recovered_entry turns each into a
    cache entry; with the siblings' entries every assignment hits and the replay runs
    no worker, only the Lead's reassessment.
    """
    batch, first = _faulted_batch(attempt_dir)
    ledger = _Ledger("worker_recovery", attempt_dir, model)
    root = _workspace(output_root, ledger.name)
    recovered = {}
    for agent, site in sorted(first.items()):
        result = await ledger.recover(site["recovery_point_id"], root / agent,
                                      disable_faults=True)
        if result["status"] != "completed":
            # A missing entry would silently rerun that worker in the replay.
            return ledger.outcome(result)
        recovered[agent] = selective.recovered_entry(attempt_dir, root / agent, agent)
    cache_path = root / "cache.json"
    selective.write_cache(cache_path, {
        **selective.sibling_cache(attempt_dir, batch, exclude=min(first)), **recovered,
    })
    result = await ledger.recover(selective.lead_batch_point(attempt_dir, batch),
                                  root / "replay", disable_faults=True,
                                  replay_cache_path=str(cache_path))
    return ledger.outcome(result)


async def worker_retry(attempt_dir, *, model, output_root) -> StrategyOutcome:
    """Resume each faulted worker at its denied read with faults still on.

    The pre-call checkpoint predates the denial, so the restored fault state denies
    that read again: the retry succeeds only if the worker's own later reads outlast
    the fault (a max_failures cap), and fails again under persistent uncapped denial.
    It ends at the workers, with no Lead replay, so answer is None.
    """
    _, first = _faulted_batch(attempt_dir)
    ledger = _Ledger("worker_retry", attempt_dir, model)
    root = _workspace(output_root, ledger.name)
    for agent, site in sorted(first.items()):
        await ledger.recover(site["recovery_point_id"], root / agent, disable_faults=False)
    failed = [r for r in ledger.results if r["status"] != "completed"]
    return ledger.outcome(failed[0] if failed else ledger.results[-1])


STRATEGIES: dict[str, Strategy] = {
    "no_recovery": no_recovery,
    "full_restart": full_restart,
    "batch_replay": batch_replay,
    "batch_replay_cached": batch_replay_cached,
    "worker_recovery": worker_recovery,
    "worker_retry": worker_retry,
}
