"""Fault detection and rollback selection for recovery strategies."""

import hashlib
import re
from dataclasses import dataclass

WORKER = re.compile(r"batch(\d+)-worker\d+")
RESTARTS = ("full_restart", "selective")  # stop a faulted attempt and run a second one


@dataclass
class Site:
    agent: str
    batch: int | None  # None: not attributable to a worker batch
    source: str  # "oracle": a fault.fired event
    event_id: str


def sites(runtime) -> list[Site]:
    found = []
    for fired in runtime.faults.fired:
        match = WORKER.fullmatch(fired["agent"])
        found.append(Site(fired["agent"], int(match[1]) if match else None, "oracle",
                          fired["event_id"]))
    return found


def detected(runtime, batches_done: int, submitting: bool) -> bool:
    """True once `detect_after` batches have joined after the first faulted batch,
    or as soon as the Lead submits after any fault. Only restart strategies detect faults."""
    if runtime.config.recovery not in RESTARTS:
        return False
    batches = [site.batch for site in sites(runtime)]
    if not batches:
        return False
    if submitting or None in batches:
        return True
    return batches_done >= min(batches) + runtime.config.detect_after


def reuse_key(agent: str, document_id: str, prompt: str) -> tuple[str, str, str]:
    return agent, document_id, hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def rollback(runtime) -> tuple[str, dict] | None:
    """The earliest faulted checkpoint (a Worker's pre-batch one, or the Lead's last before
    its fault) and that batch's reusable results; None if a fault has no such checkpoint."""
    events = runtime.db.run_events(runtime.run_id)
    saved = {event["recovery_point_id"]: index for index, event in enumerate(events)
             if event["event_type"] == "checkpoint.saved"}
    found = sites(runtime)
    points = []
    for site in found:
        point = None
        if site.batch is not None:
            for event in events:
                if event["event_type"] == "delegation.request" and event["batch_id"] == site.batch:
                    point = event["recovery_point_id"]
                    break
        elif site.agent == "lead":
            for event in events:
                if event["event_id"] == site.event_id:
                    break
                if event["event_type"] == "checkpoint.saved" and event["agent_id"] == "lead":
                    point = event["recovery_point_id"]
        if point not in saved:
            return None
        points.append((saved[point], point, site.batch))
    if not points:
        return None
    _, point, batch = min(points, key=lambda p: (p[0], p[2] is not None))
    return point, {} if batch is None else _reusable(runtime, events, batch, found)


def _reusable(runtime, events, batch, found) -> dict:
    """Completed results of `batch` from Workers no fault hit, keyed by Worker ID and assignment."""
    faulted = {site.agent for site in found}
    assignments = {e["agent_id"]: runtime.artifacts.get(e["payload_ref"])
                   for e in events if e["event_type"] == "worker.started"}
    reuse = {}
    for event in events:
        agent = event.get("assignment_id")
        if (event["event_type"] != "worker.delivered" or event.get("batch_id") != batch
                or agent in faulted or agent not in assignments):
            continue
        delivery = runtime.artifacts.get(event["payload_ref"])
        if delivery.get("status") != "completed":
            continue
        document_id = assignments[agent]["document_id"]
        key = reuse_key(agent, document_id, assignments[agent]["assignment"])
        source = {"source_assignment_id": agent, "document_id": document_id,
                  "assignment_digest": key[-1], "source_run_id": runtime.run_id,
                  "source_event_id": event["event_id"]}
        reuse[key] = (source, delivery)
    return reuse
