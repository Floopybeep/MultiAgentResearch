"""Read-only lookups from a recorded attempt to the checkpoints selective recovery uses.

Covers the read_document tool fault (`tool.failure_injected`) only. Nothing here
writes to a run: events.sqlite is opened with mode=ro and artifacts are only read.
The one write is write_cache, to a path the caller names.
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
DIGEST = re.compile(r"[0-9a-f]{64}")
ORIGINS = frozenset({"sibling", "recovered"})


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
    # mode=ro on a WAL database leaves -shm and -wal files beside it, which a read-only
    # connection cannot remove. No -wal means the writer closed and checkpointed, so the
    # main file is complete and immutable reads it with no sidecars; a live or crashed
    # writer's -wal still gets an ordinary read-only open.
    path = root / "events.sqlite"
    sealed = not path.with_name(path.name + "-wal").exists()
    return closing(sqlite3.connect(f"{path.as_uri()}?{'immutable=1' if sealed else 'mode=ro'}",
                                   uri=True))


def _events(root: Path) -> list[dict]:
    with _connect(root) as db:
        rows = db.execute("SELECT sequence, body FROM events ORDER BY sequence").fetchall()
    return [{**json.loads(body), "sequence": sequence} for sequence, body in rows]


def own_events(run_dir, run_id: str) -> list[dict]:
    """run_id's events alone, in sequence order.

    recover() copies the source log into every branch, so an unfiltered count also
    counts each event of the attempt the branch was taken from.
    """
    return [e for e in _events(Path(run_dir).resolve()) if e["run_id"] == run_id]


def record(run_dir, key: str):
    """One row of a run's records table, e.g. "run", "config" or "recovery_usage"."""
    with _connect(Path(run_dir).resolve()) as db:
        row = db.execute("SELECT body FROM records WHERE key=?", (key,)).fetchone()
    if row is None:
        raise ValueError(f"No {key!r} record in {run_dir}")
    return json.loads(row[0])


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


def earliest_fault_by_agent(sites: list[FaultSite]) -> dict[str, FaultSite]:
    """Each faulted agent's first fault site, the one whose checkpoint predates the rest.

    Sites are run-scoped and interleave agents, so group before choosing. Order by
    event_sequence, never failure_number: that counter is run-wide, so an agent's
    first failure need not be number 1.
    """
    first: dict[str, FaultSite] = {}
    for site in sites:
        held = first.get(site["agent_id"])
        if held is None or site["event_sequence"] < held["event_sequence"]:
            first[site["agent_id"]] = site
    return first


def _valid_entry(key, entry) -> ReplayEntry:
    if not isinstance(entry, dict) or set(entry) != set(ReplayEntry.__annotations__):
        raise ValueError(f"Cache entry {key!r} does not have exactly the ReplayEntry keys")
    for name in ("assignment_id", "document_id", "assignment_digest", "origin",
                 "source_run_id", "source_event_id"):
        if not isinstance(entry[name], str) or not entry[name]:
            raise ValueError(f"Cache entry {key!r} has a non-string or empty {name}")
    if key != entry["assignment_id"]:
        raise ValueError(f"Cache entry {key!r} is filed under the wrong assignment_id")
    if entry["origin"] not in ORIGINS:
        raise ValueError(f"Cache entry {key!r} has unknown origin {entry['origin']!r}")
    if not DIGEST.fullmatch(entry["assignment_digest"]):
        raise ValueError(f"Cache entry {key!r} digest is not 64 lowercase hex characters")
    delivery = _plain(entry["delivery"])
    if delivery["status"] != "completed":
        raise ValueError(f"Cache entry {key!r} delivery did not complete")
    if delivery["assignment_id"] != entry["assignment_id"]:
        raise ValueError(f"Cache entry {key!r} delivery belongs to {delivery['assignment_id']}")
    return entry


def _valid_cache(cache) -> dict[str, ReplayEntry]:
    if not isinstance(cache, dict):
        raise ValueError("Replay cache must be a JSON object of ReplayEntry records")
    seen = set()
    for key, entry in cache.items():
        _valid_entry(key, entry)
        # cache_lookup would raise on a duplicate at dispatch; refuse it at load instead.
        identity = (entry["document_id"], entry["assignment_digest"])
        if identity in seen:
            raise ValueError(f"Duplicate (document_id, assignment_digest) at {key!r}")
        seen.add(identity)
    return cache


def write_cache(path, entries: dict[str, ReplayEntry]) -> None:
    """Serialize a validated replay cache; nothing is written if any entry is invalid."""
    text = json.dumps(_valid_cache(entries), indent=2, sort_keys=True, ensure_ascii=False)
    Path(path).write_text(text, encoding="utf-8")


def load_cache(path) -> dict[str, ReplayEntry]:
    """Read a replay cache, raising ValueError on any entry write_cache would refuse."""
    return _valid_cache(json.loads(Path(path).read_text(encoding="utf-8")))


def cache_lookup(cache: dict[str, ReplayEntry], document_id: str,
                 prompt: str) -> ReplayEntry | None:
    """The entry for this assignment, matched on (document_id, digest of prompt).

    Not on agent name: worker names are positional and can shift between attempts,
    the assignment cannot. `prompt` must be redacted the way EventLogger stored it,
    since cached digests were computed from the logged delegation.request.
    """
    digest = assignment_digest(prompt)
    matches = [e for e in cache.values()
               if e["document_id"] == document_id and e["assignment_digest"] == digest]
    if len(matches) > 1:
        raise ValueError(f"{len(matches)} cache entries match {document_id} / {digest}")
    return matches[0] if matches else None


def reuse(entry: ReplayEntry, assignment_id: str) -> tuple[WorkerResult, dict]:
    """The cached result re-addressed to `assignment_id`, and its worker.reused payload.

    A result delivered at batch1-worker3 must say batch1-worker3, or the Lead files it
    under the wrong worker. The payload is then the only record of the source position.
    """
    result = WorkerResult.model_validate({**entry["delivery"], "assignment_id": assignment_id})
    return result, {
        "assignment_id": assignment_id, "source_assignment_id": entry["assignment_id"],
        "document_id": entry["document_id"], "assignment_digest": entry["assignment_digest"],
        "origin": entry["origin"], "source_run_id": entry["source_run_id"],
        "source_event_id": entry["source_event_id"],
    }
