"""Offline reading of a recorded run: events joined to their payload artifacts.

Inspection only. Nothing in the solving pipeline imports this module; it opens
the event database read-only and never writes.
"""

import json
import sqlite3
from pathlib import Path

from ..storage.artifacts import ArtifactStore

FAILURE_INJECTED = "tool.failure_injected"
TOOL_REQUEST = "tool.request"
TOOL_RESULT = "tool.result"
TOOL_ERROR = "tool.error"
TOOL_CANCELLED = "tool.cancelled"
WORKER_FINISHED = "worker.finished"


class TraceReader:
    """Resolve `payload_ref` hashes in one run directory to stored artifacts."""

    def __init__(self, root):
        self.root = Path(root)
        self.artifacts = ArtifactStore(self.root / "artifacts")

    def payload(self, event):
        ref = event.get("payload_ref")
        return None if ref is None else self.artifacts.get(ref)

    def events(self, event_type=None, agent=None):
        """Recorded events in insertion order, each with its payload resolved."""
        uri = f"file:{self.root / 'events.sqlite'}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute("SELECT body FROM events ORDER BY sequence").fetchall()
        finally:
            connection.close()
        resolved = []
        for (body,) in rows:
            event = json.loads(body)
            if event_type is not None and event["event_type"] != event_type:
                continue
            if agent is not None and event["agent_id"] != agent:
                continue
            resolved.append({**event, "payload": self.payload(event)})
        return resolved

    def records(self):
        """The `records` table, which holds the redacted run config and catalog."""
        uri = f"file:{self.root / 'events.sqlite'}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute("SELECT key, body FROM records").fetchall()
        finally:
            connection.close()
        return {key: json.loads(body) for key, body in rows}

    def failures(self):
        """Faults that actually triggered, in order; empty means none was reached."""
        return [event["payload"] for event in self.events(FAILURE_INJECTED)]

    def reads(self):
        """Every requested document page: (agent, document_id, offset, event_id).

        Repeats of one triple are retries; distinct document_ids for one agent
        show it switching documents.
        """
        requested = []
        for event in self.events(TOOL_REQUEST):
            call = event["payload"] or {}
            if call.get("name") != "read_document":
                continue
            args = call.get("args") or {}
            requested.append((
                event["agent_id"], args.get("document_id"), args.get("offset", 0),
                event["event_id"],
            ))
        return requested
