"""Inject configured text at the document-to-worker boundary."""

from typing import Any

from ..config import DocumentInjectionConfig


def inject_document_prompt(
    page: dict[str, Any], config: DocumentInjectionConfig,
) -> dict[str, Any]:
    """Prepend the literal prompt to each page, preserving source pagination."""
    if not config.enabled:
        return page
    return {**page, "text": f"{config.prompt}\n\n{page['text']}"}
