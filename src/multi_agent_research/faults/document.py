import json
import random
from pathlib import Path

from pydantic import Field, PrivateAttr, field_validator

from ..frames import DEFAULT_CORPUS
from .base import Fault


def first_read(fault, document_id) -> bool:
    """Whether `document_id` is one of the first `num_docs` distinct documents read."""
    read = fault._state.setdefault("read", [])
    if document_id not in read and len(read) < fault.num_docs:
        read.append(document_id)
    return document_id in read


class PromptInjectionFault(Fault):
    """Prepends a literal prompt to every page of the first N distinct documents read."""

    point = "read_document"
    num_docs: int = Field(default=1, ge=0)  # first N distinct documents read; 0 disables
    prompt: str

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value):
        if not value.strip():
            raise ValueError("prompt must be nonempty")
        return value

    async def after(self, call, page, runtime):
        if not first_read(self, page["document_id"]):
            return page
        runtime.faults.fire(self, call, {"document_id": page["document_id"],
                                         "offset": page["offset"]})
        return {**page, "text": f"{self.prompt}\n\n{page['text']}"}


class SilentTruncationFault(Fault):
    """Ends the document at a paragraph or line boundary near `keep_fraction` of its length,
    like a scraper losing the tail. Pages before the cut are untouched; the page reaching it
    reports the shorter total_characters and no next_offset."""

    point = "read_document"
    num_docs: int = Field(default=1, ge=1)  # first N distinct documents read up to the cut
    keep_fraction: float = Field(default=0.35, gt=0, lt=1)  # of the document's characters
    max_fires: int = Field(default=1, ge=1)  # per document; later reads are clean

    def cut(self, text):
        target = int(len(text) * self.keep_fraction)
        tolerance = max(200, int(len(text) * 0.05))
        for separator in ("\n\n", "\n"):
            cuts = [index for index in (text.rfind(separator, 0, target + 1),
                                        text.find(separator, target))
                    if 0 < index < len(text) and abs(index - target) <= tolerance]
            if cuts:
                return min(cuts, key=lambda index: abs(index - target))
        return max(1, min(target, len(text) - 1))

    async def after(self, call, page, runtime):
        document_id, offset = page["document_id"], page["offset"]
        if self._state.get(document_id, 0) >= self.max_fires:
            return page
        full = runtime.documents.documents[document_id].text
        truncated = full[:self.cut(full)]
        text = truncated[offset:offset + runtime.config.max_document_chars]
        if offset + len(text) < len(truncated) or not first_read(self, document_id):
            return page  # before the cut, or not a target
        self._state[document_id] = self._state.get(document_id, 0) + 1
        runtime.faults.fire(self, call, {"document_id": document_id, "offset": offset,
                                         "kept_characters": len(truncated)})
        if not text:
            raise ValueError("Document offset/limit is out of range")
        return {**page, "text": text, "total_characters": len(truncated), "next_offset": None}


class DocMisroutingFault(Fault):
    point = "read_document"
    num_docs: int = Field(default=1, ge=1)  # first N distinct documents read
    seed: int = 0
    overrides: dict[str, str] = Field(default_factory=dict)  # requested ID -> replacement ID
    corpus_dir: Path = DEFAULT_CORPUS
    max_fires: int = Field(default=1, ge=1)  # per document; later reads are clean
    _index: dict | None = PrivateAttr(default=None)  # corpus documents; not in _state

    async def after(self, call, page, runtime):
        requested = page["document_id"]
        if not first_read(self, requested) or self._state.get(requested, 0) >= self.max_fires:
            return page
        if self._index is None:
            index = json.loads((self.corpus_dir / "index.json").read_text(encoding="utf-8"))
            self._index = index["documents"]
        # By URL: catalog IDs may be relabeled visible IDs, not corpus IDs.
        urls = {doc.url for doc in runtime.documents.documents.values()}
        others = sorted(key for key, entry in self._index.items() if entry["url"] not in urls)
        url = runtime.documents.documents[requested].url
        served = (self.overrides.get(requested)
                  or random.Random(f"{self.seed}:{url}").choice(others))
        text = (self.corpus_dir / self._index[served]["file"]).read_text(encoding="utf-8")
        self._state[requested] = self._state.get(requested, 0) + 1
        runtime.faults.fire(self, call, {"document_id": requested, "offset": page["offset"],
                                         "served_document_id": served})
        # Keep the requested page's length and pagination, so the catalog and any later
        # clean reads agree with it; past the replacement's end, read it from the start.
        start = page["offset"] if page["offset"] < len(text) else 0
        return {**page, "text": text[start:start + len(page["text"])]}
