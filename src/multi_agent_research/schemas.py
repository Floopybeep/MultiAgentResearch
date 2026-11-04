"""Public QA tool contracts and serializable graph states."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class memory_write(Contract):
    """Persist or update the question-solving plan before delegation."""

    plan: str = Field(min_length=1)


class memory_read(Contract):
    """Read the most recent saved question-solving plan."""


class run_blocking_subagent(Contract):
    """Delegate one self-contained evidence-reading task; independent calls form a parallel batch."""

    prompt: str = Field(min_length=1)


class submit_answer(Contract):
    """Submit the final QA response, with its concise answer enclosed in curly braces."""

    answer: str = Field(min_length=1)


class complete_task(Contract):
    """Return evidence-backed findings, supporting document IDs, and uncertainties to the Lead."""

    findings: str = Field(min_length=1)
    document_ids: list[str] = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)


class read_document(Contract):
    """Read a page of an available local article; use next_offset to continue reading."""

    document_id: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)


class WorkerResult(Contract):
    assignment_id: str
    status: Literal["completed", "failed", "budget_exhausted"]
    findings: str = ""
    document_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    stop_reason: str


class AgentState(TypedDict, total=False):
    messages: list[Any]
    turns: int
    output_tokens: int
    tool_calls: int
    batches: int
    results: dict[str, dict]
    answer: str
    status: str
    stop_reason: str
    documents: list[str]
    result: dict


def merge_results(left: dict, right: dict) -> dict:
    for key in left.keys() & right.keys():
        if left[key] != right[key]:
            raise ValueError(f"Conflicting worker result: {key}")
    return left | right
