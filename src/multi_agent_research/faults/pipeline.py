"""Deterministic pipeline faults; no worker mutation or background tasks."""

import hashlib
from typing import Any

from ..config import PipelineFaultConfig
from ..schemas import WorkerResult


class PipelineFaultInjector:
    def __init__(self, config: PipelineFaultConfig):
        self.config = config

    def decide(self, assignment_id: str) -> dict[str, Any]:
        cfg = self.config
        # Keyed draws do not depend on dispatch scheduling or completion order.
        digest = hashlib.sha256(f"{cfg.seed}:{assignment_id}".encode()).digest()
        # Use 53 bits so float rounding can never turn a draw into 1.0.
        draw = (int.from_bytes(digest[:8], "big") >> 11) / 2**53
        targeted = not cfg.assignment_ids or assignment_id in cfg.assignment_ids
        return {"selected": cfg.enabled and targeted and draw < cfg.probability,
                "targeted": targeted, "draw": draw, "seed": cfg.seed,
                "probability": cfg.probability}

    def log_decision(self, runtime, agent: str, batch: int, parent: str,
                     decision: dict[str, Any]) -> str:
        if not self.config.enabled:
            return parent
        return runtime.event(
            "fault.decision", "pipeline", {**decision, "fault_type": self.config.fault_type},
            [parent], assignment_id=agent, batch_id=batch, injection_stage="dispatch",
        )

    def inject(self, runtime, agent: str, batch: int, parent: str, *,
               worker_executed: bool, original: dict[str, Any] | None = None,
               decision_event: str | None = None) -> tuple[dict[str, Any], str]:
        kind = self.config.fault_type
        errors = {"dropped_result": "InjectedDroppedWorkerResult",
                  "dispatch_failure": "InjectedWorkerDispatchFailure",
                  "timeout": "InjectedCommunicationTimeout"}
        delivered = WorkerResult(assignment_id=agent, status="failed",
                                 stop_reason=errors[kind]).model_dump()
        event = runtime.event(
            "fault.injected", "pipeline",
            {"fault_type": kind, "triggered": True, "decision": self.decide(agent),
             "worker_executed": worker_executed,
             "original_payload_ref": (runtime.artifacts.put(runtime.log.redact(original))
                                      if original is not None else None),
             "delivered_payload": delivered},
            list(dict.fromkeys([parent, decision_event or parent])),
            assignment_id=agent, batch_id=batch,
            injection_stage="delivery" if worker_executed else "dispatch",
        )
        return delivered, event
