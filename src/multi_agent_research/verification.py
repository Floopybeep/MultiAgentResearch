"""Unprivileged, diagnostic-only checks of actual boundary inputs and outputs."""

import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, StrictBool

from . import prompts
from .runtime import Runtime


class VerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified: StrictBool
    diagnostic: str


async def verify_boundary(
    runtime: Runtime, agent: str, boundary: str, actual_input: Any, actual_output: Any,
    *, parents: list[str],
) -> dict[str, Any]:
    """Return diagnostics only; callers supply observed data, never hidden source state."""
    verifier = f"{agent}-{boundary}-verifier"
    started = time.monotonic()
    runtime.event("verification.started", verifier, {"boundary": boundary}, parents)
    diagnostic: dict[str, Any] = {"verified": None, "diagnostic": "", "error": None}
    try:
        response = await runtime.call_model("verifier", verifier, [
            SystemMessage(content=prompts.load("verifier")),
            HumanMessage(content=json.dumps({
                "boundary": boundary, "actual_input": actual_input,
                "actual_output": actual_output,
            })),
        ], [])
        if not isinstance(response.content, str):
            raise ValueError("Verifier response must be a JSON string")
        diagnostic.update(VerificationDecision.model_validate_json(response.content).model_dump())
    except Exception as exc:
        diagnostic["error"] = runtime.log.redact(f"{type(exc).__name__}: {exc}")
        diagnostic["diagnostic"] = "Verification unavailable; no consistency verdict was obtained."
    elapsed = time.monotonic() - started
    event = runtime.event("verification", verifier, {
        "boundary": boundary, **diagnostic,
    }, [*parents, *runtime.observed.get(verifier, [])], duration_seconds=elapsed)
    record = {
        "boundary": boundary, "agent": agent, **diagnostic,
        "duration_seconds": elapsed, "event_id": event,
    }
    runtime.verifications.append(record)
    return record
