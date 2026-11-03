import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

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


OPEN = "<exact_text_with_citation>"
CLOSE = "</exact_text_with_citation>"


def extract_report(text):
    if OPEN not in text and CLOSE not in text:
        # Legacy bare output still undergoes exact-text validation.
        return text
    if text.count(OPEN) != 1 or text.count(CLOSE) != 1:
        raise ValueError("Ambiguous citation output envelope")
    before, remainder = text.split(OPEN, 1)
    if CLOSE in before or CLOSE not in remainder:
        raise ValueError("Malformed citation output envelope")
    report, trailing = remainder.split(CLOSE, 1)
    if trailing.strip():
        raise ValueError("Unexpected text after citation output envelope")
    return report


def citation_input(draft, documents):
    # Fail visibly on reserved delimiters rather than corrupting or truncating a draft.
    reserved = (OPEN, CLOSE, "<synthesized_text>", "</synthesized_text>",
                "<sources>", "</sources>")
    if any(tag in draft for tag in reserved):
        raise ValueError("Draft contains a reserved citation delimiter")
    sources = json.dumps(documents, ensure_ascii=False)
    # Escaped JSON preserves source text while preventing literal delimiter collisions.
    sources = sources.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<synthesized_text>{draft}</synthesized_text>\n<sources>{sources}</sources>"


async def cite(runtime, state):
    # Deliberately fail instead of silently discarding evidence beyond the configured cap.
    documents = [s.model_dump() for s in runtime.sources.values()]
    runtime.event(
        "citation.started",
        "citation",
        {"draft": state["draft"]},
        runtime.observed.get("lead", []) + list(runtime.source_events.values()),
    )
    try:
        payload = citation_input(state["draft"], documents)
        if len(payload) > runtime.config.max_citation_chars:
            return {"status": "budget_exhausted", "stop_reason": "citation_input_limit"}
        response = await runtime.call_model(
            "citation",
            "citation",
            [SystemMessage(content=runtime.rendered_prompts["citation"]), HumanMessage(content=payload)],
            [],
        )
        if response.tool_calls:
            raise ValueError("Citation agent cannot call tools")
        report = extract_report(text_content(response))
        count = validate_citations(state["draft"], report, runtime.sources)
        runtime.event(
            "citation.validated",
            "citation",
            {"citation_count": count, "report": report},
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
