from pydantic import Field

from .base import Fault


class TokenBudgetFault(Fault):
    """Caps a worker's total output tokens across its model calls."""

    point = "model_call"
    max_output_tokens: int = Field(gt=0)  # per worker
    assignment_ids: list[str] = Field(default_factory=list)  # empty: every worker

    def targets(self, call) -> bool:
        return call.role == "worker" and (not self.assignment_ids or call.agent in self.assignment_ids)

    async def before(self, call, runtime):
        if not self.targets(call):
            return
        used = self._state.get(call.agent, 0)
        if used >= self.max_output_tokens:
            from ..runtime import BudgetExceeded  # runtime imports the fault registry
            runtime.faults.fire(self, call, {"output_tokens": used})
            raise BudgetExceeded("worker_token_budget")
        config = call.args["model_config"]
        if self.max_output_tokens - used < config.max_output_tokens:
            call.args["model_config"] = config.model_copy(
                update={"max_output_tokens": self.max_output_tokens - used})

    async def after(self, call, response, runtime):
        if not self.targets(call):
            return response
        used = self._state.get(call.agent, 0)
        tokens = (response.usage_metadata or {}).get("output_tokens") or 0
        self._state[call.agent] = used + tokens
        # The budget bound this call (a tie with the configured cap counts) and cut it short.
        cap = call.args["model_config"].max_output_tokens
        if cap == self.max_output_tokens - used and response.response_metadata.get("finish_reason") == "length":
            runtime.faults.fire(self, call, {"max_output_tokens": cap})
        return response


class ToolBudgetFault(Fault):
    """Caps a worker's tool calls; complete_task always goes through."""

    point = "tool_call"
    max_tool_calls: int = Field(ge=0)  # per worker, excluding complete_task
    assignment_ids: list[str] = Field(default_factory=list)  # empty: every worker

    async def before(self, call, runtime):
        if (call.role != "worker" or call.name == "complete_task"
                or (self.assignment_ids and call.agent not in self.assignment_ids)):
            return
        used = self._state.get(call.agent, 0)
        if used >= self.max_tool_calls:
            from ..runtime import BudgetExceeded  # runtime imports the fault registry
            runtime.faults.fire(self, call, {"tool_calls": used})
            raise BudgetExceeded("worker_tool_budget")
        self._state[call.agent] = used + 1


class TurnBudgetFault(Fault):
    """Caps how many model turns a worker can take."""
    point = "model_call"
    max_turns: int = Field(ge=0)
    assignment_ids: list[str] = Field(default_factory=list)

    async def before(self, call, runtime):
        if call.role != "worker" or (self.assignment_ids and call.agent not in self.assignment_ids):
            return
        used = self._state.get(call.agent, 0)
        if used >= self.max_turns:
            from ..runtime import BudgetExceeded
            runtime.faults.fire(self, call, {"turns": used})
            raise BudgetExceeded("worker_turn_budget")
        self._state[call.agent] = used + 1
