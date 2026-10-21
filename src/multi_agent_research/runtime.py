"""Per-run resources and observable model/tool boundaries; no injection or recovery."""

import asyncio
import hashlib
import json
import sqlite3
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import messages_to_dict

from .observability.events import EventLogger, now
from .observability.usage import Usage
from .schemas import SourceDocument
from .storage.artifacts import ArtifactStore
from .storage.database import Database
from .tools.memory import PlanMemory
from .viewer_export import ViewerExport


class BudgetExceeded(RuntimeError):
    pass


class Runtime:
    def __init__(self, config, model, search, fetcher, root: Path | None = None):
        self.config, self.model, self.search, self.fetcher = config, model, search, fetcher
        self.run_id = uuid4().hex
        timestamp = datetime.now(timezone.utc).strftime("%y%m%d_%H%M%S")
        self.root = root or config.output_dir / f"{timestamp}_{self.run_id}"
        self.root.mkdir(parents=True, exist_ok=False)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.db = Database(self.root / "events.sqlite")
        self.log = EventLogger(self.db, self.artifacts, self.run_id)
        self.memory = PlanMemory(self.db, self.artifacts)
        self.usage = Usage()
        self.sources = {}
        self.source_events = {}
        self.observed = {}
        redacted_config = self.log.redact(config.model_dump(mode="json"))
        self.db.record("config", redacted_config)
        self.viewer_export = None
        try:
            self.viewer_export = ViewerExport(self.root, redacted_config)
            self.log.on_event = self.viewer_export.observe
        except (OSError, sqlite3.Error):
            warnings.warn("Browser export unavailable; SQLite logging remains enabled.",
                          RuntimeWarning, stacklevel=2)

    def event(self, kind, agent, payload, parents=(), **metadata):
        event = self.log.emit(kind, agent, payload, parents, **metadata)
        self.observed.setdefault(agent, []).append(event)
        return event

    async def call_model(self, role, agent, messages, tools):
        if self.usage.input_tokens + self.usage.output_tokens >= self.config.max_run_tokens:
            raise BudgetExceeded("run_token_budget")
        config = getattr(self.config, role)
        start = time.monotonic()
        request = self.event(
            "model.request",
            agent,
            {
                "messages": messages_to_dict(messages),
                "tools": [t.model_json_schema() for t in tools],
            },
            self.observed.get(agent, []).copy(),
            model=config.model,
            retry_number=0,
        )
        try:
            response = await asyncio.wait_for(
                self.model.invoke(role, agent, messages, tools, config),
                self.config.call_timeout_seconds,
            )
            self.usage.add(response.usage_metadata, config)
            self.event(
                "model.response",
                agent,
                response.model_dump(mode="json"),
                [request],
                duration_seconds=time.monotonic() - start,
            )
            return response
        except BaseException as exc:
            self.event(
                "model.error",
                agent,
                {"type": type(exc).__name__, "message": str(exc)},
                [request],
                duration_seconds=time.monotonic() - start,
            )
            raise

    async def call_tool(self, agent, call, handler):
        start = time.monotonic()
        request = self.event(
            "tool.request",
            agent,
            call,
            self.observed.get(agent, []).copy(),
            tool_call_id=call["id"],
        )
        try:
            result = await asyncio.wait_for(handler(), self.config.call_timeout_seconds)
            self.event(
                "tool.result",
                agent,
                result,
                [request],
                tool_call_id=call["id"],
                duration_seconds=time.monotonic() - start,
            )
            return result
        except asyncio.CancelledError:
            self.event("tool.cancelled", agent, {}, [request], tool_call_id=call["id"])
            raise
        except Exception as exc:
            result = {"error": type(exc).__name__, "message": self.log.redact(str(exc))}
            self.event(
                "tool.error",
                agent,
                result,
                [request],
                tool_call_id=call["id"],
                duration_seconds=time.monotonic() - start,
            )
            return result

    async def fetch(self, url, agent):
        page = await self.fetcher.fetch(url, self.config.max_download_bytes)
        raw_ref = self.artifacts.put(self.log.redact({"raw": page["raw"]}))
        text = page["text"][: self.config.max_document_chars]
        paragraphs = {
            f"p{i}": p for i, p in enumerate((p.strip() for p in text.splitlines() if p.strip()), 1)
        }
        if not paragraphs:
            raise ValueError("No readable text in fetched document")
        digest = hashlib.sha256(
            json.dumps([url, page["url"], raw_ref, paragraphs], sort_keys=True).encode()
        ).hexdigest()[:16]
        source = SourceDocument(
            source_id=f"s{digest}",
            url=url,
            final_url=page["url"],
            title=page["title"],
            retrieved_at=now(),
            raw_ref=raw_ref,
            paragraphs=paragraphs,
            truncated=len(text) < len(page["text"]),
        )
        # Source snapshots are run-local and contain precisely the delivered evidence.
        self.sources.setdefault(source.source_id, source)
        source = self.sources[source.source_id]
        self.db.record(source.source_id, source.model_dump())
        event = self.event(
            "source.saved", agent, source.model_dump(), self.observed.get(agent, []).copy()
        )
        self.source_events[source.source_id] = event
        return source.model_dump()

    def close(self):
        try:
            if self.viewer_export is not None:
                self.viewer_export.close()
        finally:
            self.db.close()
