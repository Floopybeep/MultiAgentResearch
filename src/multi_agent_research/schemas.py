"""Public tool contracts and serializable graph states."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class memory_write(Contract):
    """Persist or update the research plan before delegation."""

    plan: str = Field(min_length=1)


class memory_read(Contract):
    """Read the most recent saved research plan."""


class run_blocking_subagent(Contract):
    """Delegate one self-contained research task; independent calls form a parallel batch."""

    prompt: str = Field(min_length=1)


class complete_task(Contract):
    """Submit the final report (lead) or evidence-backed findings (worker)."""

    report: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class web_search(Contract):
    """Find relevant web pages and snippets. Fetch promising pages before citing them."""

    query: str = Field(min_length=1)


class web_fetch(Contract):
    """Fetch a public HTML/text page and preserve its evidence with paragraph identifiers."""

    url: str = Field(min_length=1)


class SourceDocument(Contract):
    source_id: str
    url: str
    final_url: str
    title: str
    retrieved_at: str
    raw_ref: str
    paragraphs: dict[str, str]
    truncated: bool = False
    extraction_version: str = "bs4-get-text-v1"


class WorkerResult(Contract):
    assignment_id: str
    status: Literal["completed", "failed", "budget_exhausted"]
    findings: str = ""
    source_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    stop_reason: str


class AgentState(TypedDict, total=False):
    messages: list[Any]
    turns: int
    tool_calls: int
    batches: int
    results: dict[str, dict]
    draft: str
    report: str
    status: str
    stop_reason: str
    sources: list[str]
    result: dict


def merge_results(left: dict, right: dict) -> dict:
    for key in left.keys() & right.keys():
        if left[key] != right[key]:
            raise ValueError(f"Conflicting worker result: {key}")
    return left | right
