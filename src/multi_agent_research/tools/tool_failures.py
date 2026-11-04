"""Accidental tool failures at the worker document-reading boundary.

Targeting predicates and per-question-run bookkeeping for evidence denial. Pure
of I/O, Runtime and the event loop, so the rules stay testable on their own.
"""

import hashlib
from dataclasses import dataclass, field

from ..config import ToolFailureConfig

TOOL_NAME = "read_document"
UNAVAILABLE_MESSAGE = "read_document is unavailable"


class ToolUnavailableError(RuntimeError):
    """A configured accidental fault denied an otherwise valid document read."""


def question_key(document_ids) -> str:
    """Stable identity for the question, derived from its document set.

    Runtime is built without the FRAMES question ID, so the sorted catalog
    stands in for it: 821 of the corpus's 822 questions have a distinct
    document set. Only the one colliding pair shares fault verdicts, and only
    when `failure_probability` is below 1.
    """
    return hashlib.sha256("|".join(sorted(document_ids)).encode("utf-8")).hexdigest()


@dataclass
class ToolFailureState:
    """Fault bookkeeping for one question run, shared across every worker."""

    failures: int = 0
    denied: set[tuple[str, int]] = field(default_factory=set)
    attempts: dict[tuple[str, int], int] = field(default_factory=dict)

    def record_attempt(self, document_id: str, offset: int) -> int:
        """Count this request against its page and return the 1-based attempt."""
        key = (document_id, offset)
        self.attempts[key] = self.attempts.get(key, 0) + 1
        return self.attempts[key]

    def reserve(self, document_id: str, offset: int) -> int:
        """Claim a failure slot and return its 1-based number.

        Called before any delay, so concurrent reads cannot overrun
        `max_failures` while an earlier denial is still sleeping.
        """
        self.failures += 1
        self.denied.add((document_id, offset))
        return self.failures


@dataclass(frozen=True)
class ToolFailureDecision:
    fail: bool
    reason: str
    attempt: int = 0


def targeted(config: ToolFailureConfig, document_id: str, offset: int) -> bool:
    """An empty `document_ids` or `offsets` list means "any"; set lists must match.

    Targets absent from this question simply never match. That is a normal
    outcome, not an error: one config is swept across questions that do not
    share documents.
    """
    if config.document_ids and document_id not in config.document_ids:
        return False
    if config.offsets and offset not in config.offsets:
        return False
    return True


def selected(
    config: ToolFailureConfig, *, key: str, document_id: str, offset: int, attempt: int,
) -> bool:
    """Draw a reproducible verdict from SHA-256, never the salted builtin `hash()`.

    Persistent faults hash the page alone, so a page that survives one read
    stays readable and a selected page stays broken. Transient faults add the
    attempt, randomizing each retry independently.
    """
    if config.failure_probability >= 1.0:
        return True
    if config.failure_probability <= 0.0:
        return False
    parts = [str(config.seed), key, document_id, str(offset)]
    if not config.persistent:
        parts.append(str(attempt))
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") < config.failure_probability * 2**64


def decide(
    config: ToolFailureConfig, state: ToolFailureState, *,
    key: str, document_id: str, offset: int,
) -> ToolFailureDecision:
    """Rule out a read, or select it for denial; records the attempt when targeted."""
    if not config.enabled:
        return ToolFailureDecision(False, "disabled")
    if not targeted(config, document_id, offset):
        return ToolFailureDecision(False, "not_targeted")
    attempt = state.record_attempt(document_id, offset)
    if not config.persistent and (document_id, offset) in state.denied:
        return ToolFailureDecision(False, "already_denied", attempt)
    if config.max_failures is not None and state.failures >= config.max_failures:
        return ToolFailureDecision(False, "cap_reached", attempt)
    if not selected(
        config, key=key, document_id=document_id, offset=offset, attempt=attempt
    ):
        return ToolFailureDecision(False, "not_selected", attempt)
    return ToolFailureDecision(True, "selected", attempt)


def delay_seconds(config: ToolFailureConfig, call_timeout_seconds: float) -> float:
    """Always longer than the tool timeout, so raising it cannot disarm the fault."""
    return call_timeout_seconds * config.timeout_margin
