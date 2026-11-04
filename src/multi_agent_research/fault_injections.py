"""Worker resource faults: deterministic selection and budget decisions.

Counters live in each worker's graph state, never in this module or a shared client.
Selection is independent for each fault and independent of async completion order.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .config import RunConfig, WorkerFaultSelectionConfig

# Generation stop reason -> (WorkerResult status, fault.budget.* event kind).
GENERATION_STOPS = {
    "injected_generation_budget_exhausted": ("budget_exhausted", "exhausted"),
    "worker_output_limit": ("budget_exhausted", "natural_limit"),
    "generation_budget_not_honored": ("failed", "error"),
    "generation_budget_usage_unavailable": ("failed", "error"),
}


def select_fault(config: WorkerFaultSelectionConfig, fault_type: str,
                 question_key: str, assignment_id: str) -> dict[str, Any]:
    key = json.dumps([config.seed, fault_type, question_key, assignment_id])
    digest = hashlib.sha256(key.encode()).digest()
    draw = (int.from_bytes(digest[:8], "big") >> 11) / 2**53
    targeted = not config.target_workers or assignment_id in config.target_workers
    return {"fault_type": fault_type, "selected": config.enabled and targeted
            and draw < config.probability, "targeted": targeted, "draw": draw,
            "probability": config.probability, "seed": config.seed,
            "question_key": question_key}


@dataclass(frozen=True)
class WorkerBudgetFaults:
    config: RunConfig
    generation_active: bool = False
    tools_active: bool = False

    @classmethod
    def for_worker(cls, runtime, agent: str) -> "WorkerBudgetFaults":
        cfg = runtime.config
        settings = cfg.worker_budget_faults
        active = {}
        for name in ("generation_budget", "tool_call_budget"):
            fault = getattr(settings, name)
            decision = select_fault(fault, name, runtime.question_key, agent)
            if name == "generation_budget":
                severity = {"max_output_tokens": fault.max_output_tokens,
                            "budget_scope": fault.budget_scope,
                            "first_call_max_output_tokens":
                                min(fault.max_output_tokens, cfg.worker.max_output_tokens)}
                reduced = (fault.budget_scope == "per_worker"
                           or fault.max_output_tokens < cfg.worker.max_output_tokens)
            else:
                severity = {"max_tool_calls": fault.max_tool_calls,
                            "effective_max_tool_calls":
                                min(fault.max_tool_calls, cfg.max_worker_tool_calls)}
                reduced = fault.max_tool_calls < cfg.max_worker_tool_calls
            active[name] = decision["selected"] and reduced
            if fault.enabled:
                runtime.event(
                    "fault.budget.decision", agent,
                    {**decision, "active": active[name], "severity": severity},
                    runtime.observed.get(agent, []).copy(), assignment_id=agent,
                )
        return cls(cfg, active["generation_budget"], active["tool_call_budget"])

    def generation_limit(self, consumed: int) -> int:
        base = self.config.worker.max_output_tokens
        if not self.generation_active:
            return base
        fault = self.config.worker_budget_faults.generation_budget
        remaining = fault.max_output_tokens
        if fault.budget_scope == "per_worker":
            remaining -= consumed
        return max(0, min(base, remaining))

    def inspect_generation(self, response, consumed: int) -> tuple[int, str | None]:
        """Return updated reported usage and a stop reason, not an invented answer."""
        if not self.generation_active:
            return consumed, None
        fault = self.config.worker_budget_faults.generation_budget
        per_worker = fault.budget_scope == "per_worker"
        allowed = self.generation_limit(consumed)
        outgoing = (response.usage_metadata or {}).get("output_tokens")
        known = type(outgoing) is int and outgoing >= 0
        total = consumed + outgoing if known else consumed
        # An overrun means the requested severity was not applied, even on finish_reason=length.
        if known and outgoing > allowed:
            return total, "generation_budget_not_honored"
        if response.response_metadata.get("finish_reason") == "length":
            # A tie with the configured cap counts as injected: the injected budget also binds.
            injected_cap = fault.max_output_tokens - (consumed if per_worker else 0)
            if injected_cap <= self.config.worker.max_output_tokens:
                return total, "injected_generation_budget_exhausted"
            return total, "worker_output_limit"
        if per_worker and not known:
            return total, "generation_budget_usage_unavailable"
        return total, None

    @property
    def tool_limit(self) -> int:
        if self.tools_active:
            return min(self.config.max_worker_tool_calls,
                       self.config.worker_budget_faults.tool_call_budget.max_tool_calls)
        return self.config.max_worker_tool_calls

    def log(self, runtime, agent: str, kind: str, payload: dict[str, Any]) -> None:
        if (self.config.worker_budget_faults.generation_budget.enabled
                or self.config.worker_budget_faults.tool_call_budget.enabled):
            runtime.event(
                f"fault.budget.{kind}", agent, payload,
                runtime.observed.get(agent, []).copy(), assignment_id=agent,
            )
