import asyncio
import hashlib
import random
from typing import Literal

from pydantic import Field, PrivateAttr

from ..schemas import WorkerResult
from .base import Fault


class BatchSelection(Fault):
    """Hits the assignments past the first `num_delivered` of batch `batch`."""

    batch: int = Field(default=1, gt=0)
    num_delivered: int = Field(default=1, ge=0)
    select: Literal["last", "random"] = "last"
    seed: int = 0
    persistent: bool = False  # also hit later batches

    def selected(self, call) -> bool:
        batch, size = call.args["batch"], call.args["batch_size"]
        if batch < self.batch or (batch > self.batch and not self.persistent):
            return False
        count = max(size - self.num_delivered, 0)
        positions = list(range(size))
        if self.select == "last":
            return call.args["position"] in positions[size - count:]
        return call.args["position"] in random.Random(f"{self.seed}:{batch}").sample(positions, count)


class ConnectionDropFault(BatchSelection):
    """The assignment is never delivered; the worker does not start."""

    point = "delegation"

    async def before(self, call, runtime):
        # Without persistent, a retried send of the same assignment goes through.
        if not self.selected(call) or (call.agent in self._state and not self.persistent):
            return
        self._state[call.agent] = self._state.get(call.agent, 0) + 1
        runtime.faults.fire(self, call, {"document_id": call.args["document_id"]})
        raise ConnectionError("Connection to worker lost; assignment was not delivered")


class ResultTimeoutFault(BatchSelection):
    """The worker runs, but the Lead waits out the deadline and receives a timeout."""

    point = "delegation"
    timeout_seconds: float = Field(default=180, gt=0)  # counted from dispatch
    _started: dict = PrivateAttr(default_factory=dict)  # dispatch times; not in snapshots

    async def before(self, call, runtime):
        self._started.setdefault(call.agent, asyncio.get_running_loop().time())

    async def after(self, call, result, runtime):
        if not self.selected(call):
            return result
        elapsed = asyncio.get_running_loop().time() - self._started[call.agent]
        runtime.faults.fire(self, call, {
            "timeout_seconds": self.timeout_seconds, "late": elapsed > self.timeout_seconds,
            "original_result_ref": runtime.artifacts.put(runtime.log.redact(result.model_dump())),
        })
        await asyncio.sleep(max(self.timeout_seconds - elapsed, 0))
        return WorkerResult(assignment_id=call.agent, status="failed", stop_reason="TimeoutError: ")


class DroppedResultFault(Fault):
    """A completed worker result is lost before delivery."""

    point = "delegation"
    assignment_ids: list[str] = Field(default_factory=list)  # empty: every assignment
    probability: float = Field(default=1.0, ge=0, le=1)
    seed: int = 0

    async def after(self, call, result, runtime):
        if result.status != "completed":
            return result
        if self.assignment_ids and call.agent not in self.assignment_ids:
            return result
        # Keyed draws do not depend on dispatch scheduling or completion order.
        digest = hashlib.sha256(f"{self.seed}:{call.agent}".encode()).digest()
        if (int.from_bytes(digest[:8], "big") >> 11) / 2**53 >= self.probability:
            return result
        runtime.faults.fire(self, call, {
            "original_result_ref": runtime.artifacts.put(runtime.log.redact(result.model_dump())),
        })
        return WorkerResult(assignment_id=call.agent, status="failed",
                            stop_reason="worker_result_lost")
