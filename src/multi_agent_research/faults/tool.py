import asyncio
import hashlib
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .base import Fault


class ToolUnavailableError(RuntimeError):
    pass


class ToolFailureFault(Fault):
    """Denies selected pages: the read fails at once, or outlasts the tool timeout."""

    point = "read_document"
    mode: Literal["immediate", "timeout"] = "immediate"
    document_ids: list[str] = Field(default_factory=list)  # empty: any document
    offsets: list[int] = Field(default_factory=list)  # empty: any offset
    max_failures: int | None = Field(default=1, ge=0)  # per question run; None: uncapped
    failure_probability: float = Field(default=1.0, ge=0, le=1)
    persistent: bool = True  # true: denied page stays denied; false: retries after a denial pass (undenied pages redraw)
    timeout_margin: float = Field(default=1.5, gt=1.0)  # times call_timeout_seconds
    seed: int = 0
    allow_total_denial: bool = False

    @field_validator("offsets")
    @classmethod
    def nonnegative_offsets(cls, value):
        if any(offset < 0 for offset in value):
            raise ValueError("offsets must be nonnegative character positions")
        return value

    @model_validator(mode="after")
    def require_total_denial_optin(self):
        if self.max_failures is None and not self.document_ids and not self.allow_total_denial:
            raise ValueError("Uncapped failures over every document deny all evidence; "
                             "set allow_total_denial, or restrict max_failures or document_ids")
        return self

    async def after(self, call, page, runtime):
        document_id, offset = page["document_id"], page["offset"]
        if ((self.document_ids and document_id not in self.document_ids)
                or (self.offsets and offset not in self.offsets)):
            return page
        key = f"{document_id}:{offset}"
        attempts = self._state.setdefault("attempts", {})
        attempts[key] = attempts.get(key, 0) + 1
        denied = self._state.setdefault("denied", [])
        failures = self._state.get("failures", 0)
        if not self.persistent and key in denied:
            return page
        if self.max_failures is not None and failures >= self.max_failures:
            return page
        if not self.selected(runtime, document_id, offset, attempts[key]):
            return page
        self._state["failures"] = failures + 1
        if key not in denied:
            denied.append(key)
        runtime.faults.fire(self, call, {
            "document_id": document_id, "offset": offset, "mode": self.mode,
            "original_artifact_ref": runtime.artifacts.put(runtime.log.redact(page)),
        })
        # Fired before the delay, which the tool timeout cancels.
        if self.mode == "timeout":
            await asyncio.sleep(runtime.config.call_timeout_seconds * self.timeout_margin)
        raise ToolUnavailableError("read_document is unavailable")

    def selected(self, runtime, document_id, offset, attempt):
        if self.failure_probability >= 1.0:
            return True
        if self.failure_probability <= 0.0:
            return False
        # The sorted catalog URLs stand in for the question (IDs may be relabeled);
        urls = sorted(doc.url for doc in runtime.documents.documents.values())
        question = hashlib.sha256("|".join(urls).encode()).hexdigest()
        parts = [str(self.seed), question, document_id, str(offset)]
        if not self.persistent:
            parts.append(str(attempt))
        digest = hashlib.sha256("|".join(parts).encode()).digest()
        return int.from_bytes(digest[:8], "big") < self.failure_probability * 2**64
