"""Read-only lookups from a recorded attempt to the checkpoints selective recovery uses.

Covers the read_document tool fault (`tool.failure_injected`) only. Nothing here
writes: events.sqlite is opened with mode=ro and artifacts are only read.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict

from .schemas import WorkerResult

FAILURE_INJECTED = "tool.failure_injected"
WORKER_AGENT = re.compile(r"batch(\d+)-worker(\d+)")  # graphs/research.py names workers so


class FaultSite(TypedDict):
    agent_id: str
    document_id: str
    offset: int
    mode: str
    batch: int
    recovery_point_id: str  # the worker's pre-call checkpoint for the failed read
    tool_call_id: str
    event_sequence: int


class ReplayEntry(TypedDict):
    assignment_id: str      # e.g. "batch1-worker2"
    document_id: str
    assignment_digest: str  # assignment_digest(delegation.request payload["args"]["prompt"])
    delivery: dict          # plain WorkerResult dump, as delivered to the Lead
    origin: str             # "sibling" | "recovered"
    source_run_id: str
    source_event_id: str


def assignment_digest(prompt: str) -> str:
    """SHA-256 hexdigest of the exact UTF-8 assignment prompt, with no normalization."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _connect(root: Path):
    return closing(sqlite3.connect(f"{(root / 'events.sqlite').as_uri()}?mode=ro", uri=True))


def _events(root: Path) -> list[dict]:
    with _connect(root) as db:
        rows = db.execute("SELECT sequence, body FROM events ORDER BY sequence").fetchall()
    return [{**json.loads(body), "sequence": sequence} for sequence, body in rows]


def _payload(root: Path, event: dict):
    return json.loads((root / "artifacts" / f"{event['payload_ref']}.json").read_text(encoding="utf-8"))


def _batch(agent_id: str) -> int:
    match = WORKER_AGENT.fullmatch(agent_id)
    if match is None:
        raise ValueError(f"Not a worker agent_id: {agent_id!r}")
    return int(match.group(1))


def _assignment(root: Path, events: list[dict], agent_id: str) -> tuple[str, str]:
    """(document_id, assignment_digest) from the delegation.request that started agent_id.

    The worker's worker.started event has that delegation.request as its parent.
    """
    started = [e for e in events if e["event_type"] == "worker.started" and e["agent_id"] == agent_id]
    if len(started) != 1:
        raise ValueError(f"Expected one worker.started for {agent_id}, found {len(started)}")
    parent_id = started[0]["parent_event_ids"][-1] if started[0]["parent_event_ids"] else None
    request = next((e for e in events if e["event_id"] == parent_id), None)
    if (request is None or request["event_type"] != "delegation.request"
            or request.get("batch_id") != _batch(agent_id)):
        raise ValueError(f"worker.started for {agent_id} does not follow its delegation.request")
    args = _payload(root, request)["args"]
    return args["document_id"], assignment_digest(args["prompt"])


def _plain(delivery: dict) -> dict:
    if WorkerResult.model_validate(delivery).model_dump() != delivery:
        raise ValueError("Delivery is not a plain WorkerResult dump")
    return delivery


def find_tool_fault_sites(run_dir) -> list[FaultSite]:
    """Every tool.failure_injected, resolved to the exact read_document request it failed."""
    root = Path(run_dir).resolve()
    events = _events(root)
    by_id = {e["event_id"]: e for e in events}
    sites = []
    for event in events:
        if event["event_type"] != FAILURE_INJECTED:
            continue
        agent = event["agent_id"]
        batch = _batch(agent)
        parents = event["parent_event_ids"]
        request = by_id.get(parents[-1]) if parents else None
        if (request is None or request["event_type"] != "tool.request"
                or request["agent_id"] != agent
                or _payload(root, request)["name"] != "read_document"):
            raise ValueError(
                f"{FAILURE_INJECTED} {event['event_id']} does not follow a read_document "
                f"tool.request by {agent}"
            )
        payload = _payload(root, event)
        sites.append(FaultSite(
            agent_id=agent, document_id=payload["document_id"], offset=payload["offset"],
            mode=payload["mode"], batch=batch,
            recovery_point_id=request["recovery_point_id"],
            tool_call_id=request["tool_call_id"], event_sequence=event["sequence"],
        ))
    return sites


def sibling_cache(run_dir, batch: int, exclude: str) -> dict[str, ReplayEntry]:
    """Completed deliveries in `batch`, minus `exclude` and every tool-faulted agent."""
    root = Path(run_dir).resolve()
    events = _events(root)
    faulted = {e["agent_id"] for e in events if e["event_type"] == FAILURE_INJECTED}
    cache = {}
    for event in events:
        if event["event_type"] != "worker.delivered" or event.get("batch_id") != batch:
            continue
        agent = event["assignment_id"]
        if agent == exclude or agent in faulted:
            continue
        delivery = _payload(root, event)
        if delivery.get("status") != "completed":
            continue
        if agent in cache:
            raise ValueError(f"Duplicate worker.delivered for {agent} in batch {batch}")
        document_id, digest = _assignment(root, events, agent)
        cache[agent] = ReplayEntry(
            assignment_id=agent, document_id=document_id, assignment_digest=digest,
            delivery=_plain(delivery), origin="sibling",
            source_run_id=event["run_id"], source_event_id=event["event_id"],
        )
    return cache


def lead_batch_point(run_dir, batch: int) -> str:
    """recovery_point_id of the first delegation.request in `batch`.

    Each delegation in a batch has its own recovery-point ID, but all of them
    locate the same pre-batch Lead checkpoint, so replaying any one reruns the batch.
    """
    for event in _events(Path(run_dir).resolve()):
        if event["event_type"] == "delegation.request" and event.get("batch_id") == batch:
            return event["recovery_point_id"]
    raise ValueError(f"No delegation.request for batch {batch}")


def recovered_entry(source_run_dir, branch_dir, agent_id: str) -> ReplayEntry:
    """Entry for a worker replayed by recover(), which emits no worker.delivered."""
    branch = Path(branch_dir).resolve()
    recovery = json.loads((branch / "recovery.json").read_text(encoding="utf-8"))
    result = recovery.get("worker_result") or {}
    if result.get("status") != "completed":
        raise ValueError(f"Recovered worker did not complete: {result.get('status')!r}")
    if result["assignment_id"] != agent_id:
        raise ValueError(f"Branch recovered {result['assignment_id']}, not {agent_id}")
    finished = [e for e in _events(branch) if e["event_type"] == "recovery.finished"]
    if len(finished) != 1:
        raise ValueError(f"Expected one recovery.finished in branch, found {len(finished)}")
    source = Path(source_run_dir).resolve()
    document_id, digest = _assignment(source, _events(source), agent_id)
    return ReplayEntry(
        assignment_id=agent_id, document_id=document_id, assignment_digest=digest,
        delivery=_plain(result), origin="recovered",
        source_run_id=recovery["run_id"], source_event_id=finished[0]["event_id"],
    )


def earliest_lead_point(run_dir) -> str:
    """The Lead's first pre-call checkpoint (call_seq 1)."""
    with _connect(Path(run_dir).resolve()) as db:
        rows = db.execute(
            "SELECT recovery_point_id FROM recovery_points WHERE agent_id='lead' AND call_seq=1"
        ).fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected one lead call_seq=1 recovery point, found {len(rows)}")
    return rows[0][0]
