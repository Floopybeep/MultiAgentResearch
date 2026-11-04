"""Per-run resources and observable model, tool and document boundaries."""

import asyncio
import logging
import sqlite3
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import messages_to_dict

from . import prompts
from .observability.events import EventLogger
from .observability.usage import Usage
from .storage.artifacts import ArtifactStore
from .storage.database import Database
from .tools.memory import PlanMemory
from .tools.prompt_injection import inject_document_prompt
from .viewer_export import ViewerExport

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    pass


class Runtime:
    def __init__(self, config, model, documents, root: Path | None = None):
        self.config, self.model, self.documents = config, model, documents
        self.document_injection_count = 0
        self.run_id = uuid4().hex
        now = datetime.now(timezone.utc)
        self.prompt_context = prompts.context(config, now.date().isoformat())
        timestamp = now.strftime("%y%m%d_%H%M%S")
        self.root = root or config.output_dir / f"{timestamp}_{self.run_id}"
        self.root.mkdir(parents=True, exist_ok=False)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.db = Database(self.root / "events.sqlite")
        self.log = EventLogger(self.db, self.artifacts, self.run_id)
        self.memory = PlanMemory(self.db, self.artifacts)
        self.usage = Usage()
        self.usage_by_role = {role: Usage() for role in ("lead", "worker", "judge")}
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
        if kind == "model.request":
            logger.info("[%s] Calling model...", agent)
        elif kind == "model.error":
            logger.info("[%s] Model call failed: %s.", agent, payload["type"])
        elif kind == "worker.finished":
            logger.info("[%s] Worker %s.", agent, payload["status"])
        elif kind == "grade.finished":
            logger.info("[judge] Grading finished (%s).", payload["method"])
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
            self.usage_by_role[role].add(response.usage_metadata, config)
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

    def snapshot_documents(self):
        snapshots = []
        for doc in self.documents.documents.values():
            ref = self.artifacts.put(self.log.redact(doc.model_dump()))
            entry = self.log.redact({**doc.catalog_entry(), "artifact_ref": ref})
            self.db.record(doc.document_id, entry)
            snapshots.append(entry)
        self.event("documents.available", "lead", {"documents": snapshots})
        return snapshots

    def read_document(
        self, document_id: str, offset: int, *, agent: str = "worker",
    ) -> dict[str, Any]:
        original = self.documents.read(document_id, offset, self.config.max_document_chars)
        injection = self.config.document_injection
        if injection.enabled and self.document_injection_count < injection.num_docs:
            injected = inject_document_prompt(original, injection)
            # This synchronous boundary shares one cap across all workers in the run.
            self.document_injection_count += 1
            self.event(
                "document.injected", agent,
                {
                    "document_id": document_id,
                    "offset": offset,
                    "injection_number": self.document_injection_count,
                    "original_artifact_ref": self.artifacts.put(self.log.redact(original)),
                    "injected_artifact_ref": self.artifacts.put(self.log.redact(injected)),
                },
                self.observed.get(agent, []).copy(),
            )
            return injected
        return original

    def close(self):
        try:
            if self.viewer_export is not None:
                self.viewer_export.close()
        finally:
            self.db.close()
