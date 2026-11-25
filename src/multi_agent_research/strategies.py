"""Fault detection for recovery strategies."""

import re
from dataclasses import dataclass

WORKER = re.compile(r"batch(\d+)-worker\d+")


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
    or as soon as the Lead submits after any fault. Only full_restart detects faults."""
    if runtime.config.recovery != "full_restart":
        return False
    batches = [site.batch for site in sites(runtime)]
    if not batches:
        return False
    if submitting or None in batches:
        return True
    return batches_done >= min(batches) + runtime.config.detect_after
