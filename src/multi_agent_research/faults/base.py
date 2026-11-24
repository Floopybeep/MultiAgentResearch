from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr

# Fault injection points
Point = Literal["model_call", "tool_call", "read_document", "delegation"]


@dataclass
class Call:
    agent: str
    role: str
    name: str
    args: dict[str, Any]


class Fault(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: ClassVar[Point]
    _state: dict = PrivateAttr(default_factory=dict)

    async def before(self, call: Call, runtime) -> None:
        pass

    async def after(self, call: Call, result: Any, runtime) -> Any:
        return result
