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
from .faults.base import Call
from .faults.manager import FaultManager
from .observability.events import EventLogger
from .observability.usage import Usage
from .storage.artifacts import ArtifactStore
from .storage.database import Database
from .tools.memory import PlanMemory
from .viewer_export import ViewerExport

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    pass


class ModelCallTimeout(RuntimeError):
    """A single model request timed out, not the overall run."""


class Runtime:
    def __init__(self, config, model, documents, root: Path | None = None,
                 viewer_root: Path | None = None, *, restore: bool = False, prior_tokens: int = 0):
        self.config, self.model, self.documents = config, model, documents
        self.prior_tokens = prior_tokens  # spent by earlier attempts of the same question
        self.run_id = uuid4().hex
        now = datetime.now(timezone.utc)
        self.prompt_context = prompts.context(config, now.date().isoformat())
        timestamp = now.strftime("%y%m%d_%H%M%S")
        self.root = root or config.output_dir / f"{timestamp}_{self.run_id}"
        self.root.mkdir(parents=True, exist_ok=restore)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.db = Database(self.root / "events.sqlite")
        self.log = EventLogger(self.db, self.artifacts, self.run_id)
        self.memory = PlanMemory(self.db, self.artifacts)
        self.usage = Usage()
        self.usage_by_role = {role: Usage() for role in ("lead", "worker", "judge")}
        self.usage.by_role = self.usage_by_role
        self.observed = {}
        self.faults = FaultManager(self, config.faults)
        self.faults_enabled = True
        from .recovery import RecoveryPoints
        self.recovery = RecoveryPoints(self)
        self.db.record("execution_status", "running")
        self.save_usage()
        redacted_config = self.log.redact(config.model_dump(mode="json"))
        self.db.record("config", redacted_config)
        self.viewer_export = None
        try:
            self.viewer_export = ViewerExport(self.root, redacted_config, viewer_root)
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

    async def call_model(self, role, agent, messages, tools, *, model_config=None):
        if role == "judge":
            if tools:
                raise ValueError("Auxiliary model replay supports tool-free requests")
            return await self.recovery.auxiliary_model(
                role, agent, messages,
                model_config if model_config is not None else getattr(self.config, role),
            )
        return await self._call_model(role, agent, messages, tools, model_config=model_config)

    async def _call_model(self, role, agent, messages, tools, *, model_config=None):
        spent = self.prior_tokens + self.usage.input_tokens + self.usage.output_tokens
        if spent >= self.config.max_run_tokens:
            raise BudgetExceeded("run_token_budget")
        config = model_config if model_config is not None else getattr(self.config, role)
        visible_messages = messages_to_dict(messages)
        recovery_point = await self.recovery.before_call(agent, "model", config.model, {
            "role": role, "messages": visible_messages,
            "tools": [t.model_json_schema() for t in tools],
            "model_config": config.model_dump(mode="json"),
        })
        start = time.monotonic()
        request = self.event(
            "model.request",
            agent,
            {
                "messages": visible_messages,
                "tools": [t.model_json_schema() for t in tools],
            },
            self.observed.get(agent, []).copy(),
            model=config.model,
            max_output_tokens=config.max_output_tokens,
            retry_number=0,
            recovery_point_id=recovery_point,
        )
        response = None
        invoked = False

        # Usage is recorded before fault `after` hooks; a fault that raises in `before`
        # made no model call, so it adds no usage.
        async def invoke(call):
            nonlocal response, invoked
            invoked = True
            response = await self.model.invoke(
                role, agent, call.args["messages"], tools, call.args["model_config"])
            self.usage.add(response.usage_metadata, config)
            self.usage_by_role[role].add(response.usage_metadata, config)
            return response

        try:
            try:
                call = Call(agent, role, config.model, {"messages": messages, "model_config": config})
                result = await asyncio.wait_for(
                    self.faults.run("model_call", call, invoke), self.config.call_timeout_seconds,
                )
            except TimeoutError as exc:
                raise ModelCallTimeout(
                    f"{agent}: model call timed out (limit: {self.config.call_timeout_seconds:g}s)"
                ) from exc
            self.event(
                "model.response",
                agent,
                result.model_dump(mode="json"),
                [request],
                duration_seconds=time.monotonic() - start,
            )
            return result
        except BaseException as exc:
            if invoked and response is None:
                self.usage.add(None, config)
                self.usage_by_role[role].add(None, config)
            self.event(
                "model.error",
                agent,
                {"type": type(exc).__name__, "message": str(exc)},
                [request],
                duration_seconds=time.monotonic() - start,
            )
            raise
        finally:
            elapsed = time.monotonic() - start
            self.usage.duration_seconds += elapsed
            self.usage_by_role[role].duration_seconds += elapsed
            self.save_usage()

    async def call_tool(self, role, agent, call, handler):
        recovery_point = await self.recovery.before_call(agent, "tool", call["name"], call)
        start = time.monotonic()
        request = self.event(
            "tool.request",
            agent,
            call,
            self.observed.get(agent, []).copy(),
            tool_call_id=call["id"],
            recovery_point_id=recovery_point,
        )
        try:
            result = await asyncio.wait_for(
                self.faults.run("tool_call", Call(agent, role, call["name"], call["args"]),
                                lambda c: handler()),
                self.config.call_timeout_seconds,
            )
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
        self.db.record("recovery_documents", [item["artifact_ref"] for item in snapshots])
        return snapshots

    def recovery_snapshot(self):
        return {"plan_ref": self.memory.ref, "prompt_context": self.prompt_context,
                "observed": self.observed, "faults": self.faults.snapshot_state()}

    def restore_recovery_snapshot(self, snapshot):
        self.memory.ref = snapshot["plan_ref"]
        self.db.record("plan", {"artifact_ref": self.memory.ref})
        self.prompt_context = snapshot["prompt_context"]
        self.observed = snapshot["observed"]
        self.faults.restore_state(snapshot.get("faults", []))

    def save_usage(self):
        self.db.record("recovery_usage", {
            "total": {k: v for k, v in vars(self.usage).items() if k != "by_role"},
            "roles": {role: {k: v for k, v in vars(usage).items() if k != "by_role"}
                      for role, usage in self.usage_by_role.items()},
            "prior_tokens": self.prior_tokens,
        })

    def restore_usage(self, saved):
        self.prior_tokens = saved.get("prior_tokens", 0)
        for key, value in saved["total"].items():
            setattr(self.usage, key, value)
        for role, values in saved["roles"].items():
            for key, value in values.items():
                setattr(self.usage_by_role[role], key, value)
        self.save_usage()

    async def read_document(self, document_id: str, offset: int, *, agent: str) -> dict[str, Any]:
        async def read(call):
            return self.documents.read(call.args["document_id"], call.args["offset"],
                                       self.config.max_document_chars)

        return await self.faults.run(
            "read_document", Call(agent, "worker", "read_document",
                                  {"document_id": document_id, "offset": offset}), read)

    def close(self):
        try:
            self.save_usage()
            self.db.record("execution_status", "stopped")
            if self.viewer_export is not None:
                self.viewer_export.close()
        finally:
            self.db.close()
