"""Diagnostic-only checks of the actual inputs and outputs at Lead and Worker boundaries."""

import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, StrictBool

from . import prompts


class VerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified: StrictBool
    diagnostic: str


def latest_model_input(runtime, agent: str) -> list[dict[str, Any]]:
    """The messages of the agent's latest model call in this run, from its model.request event."""
    row = runtime.db.connection.execute(
        "SELECT body FROM events WHERE json_extract(body, '$.event_type') = 'model.request'"
        " AND json_extract(body, '$.agent_id') = ? AND json_extract(body, '$.run_id') = ?"
        " ORDER BY sequence DESC LIMIT 1",
        (agent, runtime.run_id),
    ).fetchone()
    if row is None:
        return []
    return runtime.artifacts.get(json.loads(row[0])["payload_ref"])["messages"]


async def verify_boundary(
    runtime, agent: str, boundary: str, actual_output: Any, *, parents: list[str],
) -> dict[str, Any]:
    """Check `actual_output` against the agent's actual latest model input; diagnosis only."""
    verifier = f"{agent}-{boundary}-verifier"
    started = time.monotonic()
    runtime.event("verification.started", verifier, {"boundary": boundary}, parents)
    diagnostic: dict[str, Any] = {"verified": None, "diagnostic": "", "error": None}
    try:
        response = await runtime.call_model("verifier", verifier, [
            SystemMessage(content=prompts.load("verifier")),
            HumanMessage(content=json.dumps({
                "boundary": boundary, "actual_input": latest_model_input(runtime, agent),
                "actual_output": actual_output,
            })),
        ], [])
        if response.response_metadata.get("finish_reason") == "length":
            raise ValueError(
                "Verifier response truncated at the output token limit "
                f"(verifier.max_output_tokens={runtime.config.verifier.max_output_tokens}); "
                "increase verifier.max_output_tokens to allow reasoning and a complete JSON verdict"
            )
        if not isinstance(response.content, str):
            raise ValueError("Verifier response must be a JSON string")
        diagnostic.update(VerificationDecision.model_validate_json(response.content).model_dump())
    except Exception as exc:
        diagnostic["error"] = runtime.log.redact(f"{type(exc).__name__}: {exc}")
        diagnostic["diagnostic"] = "Verification unavailable; no consistency verdict was obtained."
    elapsed = time.monotonic() - started
    event = runtime.event("verification", verifier, {"boundary": boundary, **diagnostic},
                          [*parents, *runtime.observed.get(verifier, [])],
                          duration_seconds=elapsed)
    return {"boundary": boundary, "agent": agent, **diagnostic,
            "duration_seconds": elapsed, "event_id": event}


def recorded_verifications(runtime) -> list[dict[str, Any]]:
    """Every verification record of this run, rebuilt from its `verification` events."""
    records = []
    for (body,) in runtime.db.connection.execute(
        "SELECT body FROM events WHERE json_extract(body, '$.event_type') = 'verification'"
        " AND json_extract(body, '$.run_id') = ? ORDER BY sequence", (runtime.run_id,),
    ):
        event = json.loads(body)
        payload = runtime.artifacts.get(event["payload_ref"])
        records.append({
            "boundary": payload["boundary"],
            "agent": event["agent_id"].removesuffix(f"-{payload['boundary']}-verifier"),
            "verified": payload["verified"], "diagnostic": payload["diagnostic"],
            "error": payload["error"], "duration_seconds": event["duration_seconds"],
            "event_id": event["event_id"],
        })
    return records
