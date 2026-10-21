"""Append-only events with redacted payload artifacts and explicit dependency edges."""

import os
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class EventLogger:
    def __init__(self, db, artifacts, run_id):
        self.db, self.artifacts, self.run_id = db, artifacts, run_id
        self.on_event = None
        self.secrets = [
            v
            for k, v in os.environ.items()
            if any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
            and len(v) >= 8
        ]

    def redact(self, value):
        if isinstance(value, dict):
            return {
                k: "[REDACTED]"
                if any(
                    x in str(k).lower() for x in ("api_key", "authorization", "password", "secret")
                )
                else self.redact(v)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
        return value

    def emit(self, kind, agent, payload, parents=(), **metadata):
        payload = self.redact(payload)
        ref = self.artifacts.put(payload)
        event = dict(
            event_id=uuid4().hex,
            run_id=self.run_id,
            attempt_id=self.run_id,
            agent_id=agent,
            event_type=kind,
            timestamp=now(),
            payload_ref=ref,
            parent_event_ids=list(parents),
            **self.redact(metadata),
        )
        self.db.event(event)
        if self.on_event is not None:
            self.on_event(event, payload)
        return event["event_id"]
