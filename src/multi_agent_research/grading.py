"""Answer extraction, exact matching and LLM-judge evaluation."""

import json
import re
import time
import unicodedata
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, StrictBool

from . import prompts
from .runtime import Runtime


def normalize_answer(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def extract_answer(response: str) -> str | None:
    if response.count("{") != 1 or response.count("}") != 1:
        return None
    match = re.search(r"\{([^{}]+)\}", response)
    return (match.group(1).strip() or None) if match else None


class JudgeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct: StrictBool
    reason: str


async def grade_answer(
    runtime: Runtime, question: str, reference: str, response: str,
) -> dict[str, Any]:
    # TODO: Input question/reference/response; output format, correctness and judge metadata.
    # Define multi-part matching, normalization, partial credit and the judge rubric.
    started = time.monotonic()
    extracted = extract_answer(response)
    matched = extracted is not None and normalize_answer(extracted) == normalize_answer(reference)
    result = {
        "format_valid": extracted is not None, "extracted_answer": extracted,
        "exact_match": matched, "correct": True if matched else None,
        "method": "exact_match" if matched else "llm_judge", "judge_reason": None,
        "error": None,
    }
    # Record the evaluator input before exact-match or judge completion.
    runtime.event("grade.started", "judge", {
        "question": question, "reference_answer": reference, "candidate_response": response,
    }, runtime.observed.get("system", [])[-1:])
    if not matched:
        try:
            answer = await runtime.call_model("judge", "judge", [
                SystemMessage(content=prompts.load("judge")),
                HumanMessage(content=json.dumps({
                    "question": question, "reference_answer": reference,
                    "candidate_response": response, "extracted_answer": extracted,
                })),
            ], [])
            if not isinstance(answer.content, str):
                raise ValueError("Judge response must be a JSON string")
            decision = JudgeDecision.model_validate_json(answer.content)
            result.update(correct=decision.correct, judge_reason=decision.reason)
        except Exception as exc:
            result.update(method="judge_error", error=runtime.log.redact(f"{type(exc).__name__}: {exc}"))
    result["duration_seconds"] = time.monotonic() - started
    result["usage"] = runtime.usage_by_role["judge"].as_dict()
    runtime.event("grade.finished", "judge", result, runtime.observed.get("judge", []).copy())
    return result
