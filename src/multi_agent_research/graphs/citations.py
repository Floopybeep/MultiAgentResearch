import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from .. import prompts
from ..runtime import BudgetExceeded

MARKER = re.compile(r"\[\[cite:([a-zA-Z0-9]+):(p\d+)\]\]")


def validate_citations(draft, annotated, sources):
    stripped = MARKER.sub("", annotated)
    if stripped != draft:
        raise ValueError("Citation pass changed draft text or emitted invalid markup")
    for source, paragraph in MARKER.findall(annotated):
        if source not in sources or paragraph not in sources[source].paragraphs:
            raise ValueError(f"Unknown citation: {source}:{paragraph}")
    return len(MARKER.findall(annotated))


def text_content(message):
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block.get("text", "")
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "text"
    )


async def cite(runtime, state):
    # Deliberately fail instead of silently discarding evidence beyond the configured cap.
    documents = [s.model_dump() for s in runtime.sources.values()]
    payload = json.dumps({"draft": state["draft"], "sources": documents}, ensure_ascii=False)
    if len(payload) > runtime.config.max_citation_chars:
        return {"status": "budget_exhausted", "stop_reason": "citation_input_limit"}
    runtime.event(
        "citation.started",
        "citation",
        {"draft": state["draft"]},
        runtime.observed.get("lead", []) + list(runtime.source_events.values()),
    )
    try:
        response = await runtime.call_model(
            "citation",
            "citation",
            [SystemMessage(content=prompts.load("citation")), HumanMessage(content=payload)],
            [],
        )
        if response.tool_calls:
            raise ValueError("Citation agent cannot call tools")
        report = text_content(response)
        count = validate_citations(state["draft"], report, runtime.sources)
        runtime.event(
            "citation.validated",
            "citation",
            {"citation_count": count},
            runtime.observed["citation"].copy(),
        )
        return {"report": report, "status": "completed", "stop_reason": "complete_task"}
    except BudgetExceeded as exc:
        return {"status": "budget_exhausted", "stop_reason": str(exc)}
    except Exception as exc:
        runtime.event(
            "citation.failed",
            "citation",
            {"error": str(exc)},
            runtime.observed.get("citation", []).copy(),
        )
        return {"status": "failed", "stop_reason": f"citation: {type(exc).__name__}: {exc}"}
