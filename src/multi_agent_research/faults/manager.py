from copy import deepcopy
from typing import Any

from .base import Call, Fault, Point
from .budget import TokenBudgetFault, ToolBudgetFault, TurnBudgetFault
from .delegation import ConnectionDropFault, DroppedResultFault, ResultTimeoutFault
from .document import DocMisroutingFault, PromptInjectionFault, SilentTruncationFault
from .tool import ToolFailureFault

FAULTS: dict[str, type[Fault]] = {cls.__name__: cls for cls in (
    SilentTruncationFault, DocMisroutingFault, ToolFailureFault, PromptInjectionFault,
    ConnectionDropFault, ResultTimeoutFault, DroppedResultFault,
    TokenBudgetFault, ToolBudgetFault, TurnBudgetFault
)}


class FaultManager:
    def __init__(self, runtime, specs: list[dict]):
        self.runtime = runtime
        self.faults = []
        for spec in specs:
            options = dict(spec)
            self.faults.append(FAULTS[options.pop("type")](**options))

    async def run(self, point: Point, call: Call, real) -> Any:
        active = [f for f in self.faults if f.point == point] if self.runtime.faults_enabled else []
        for fault in active:
            await fault.before(call, self.runtime)
        result = await real(call)
        for fault in reversed(active):
            result = await fault.after(call, result, self.runtime)
        return result

    def fire(self, fault: Fault, call: Call, payload: dict) -> str:
        runtime = self.runtime
        return runtime.event("fault.fired", call.agent, {"fault": type(fault).__name__, **payload},
                             runtime.observed.get(call.agent, []).copy())

    def snapshot_state(self) -> list[dict]:
        return [deepcopy(fault._state) for fault in self.faults]

    def restore_state(self, states: list[dict]) -> None:
        for fault, state in zip(self.faults, states):
            fault._state = deepcopy(state)
