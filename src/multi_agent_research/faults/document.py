import json
import random
from pathlib import Path

from pydantic import Field, PrivateAttr, field_validator

from ..frames import DEFAULT_CORPUS
from .base import Fault


class PromptInjectionFault(Fault):
    """Prepends a literal prompt to every page of the first N catalog documents."""

    point = "read_document"
    num_docs: int = Field(default=1, ge=0)  # first N catalog documents
    prompt: str

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value):
        if not value.strip():
            raise ValueError("prompt must be nonempty")
        return value

    async def after(self, call, page, runtime):
        if page["document_id"] not in list(runtime.documents.documents)[:self.num_docs]:
            return page
        runtime.faults.fire(self, call, {"document_id": page["document_id"],
                                         "offset": page["offset"]})
        return {**page, "text": f"{self.prompt}\n\n{page['text']}"}


class SilentTruncationFault(Fault):
    """Drops a block of whole lines from the middle of the document, like a scraper losing a
    section. total_characters and next_offset are untouched."""

    point = "read_document"
    num_docs: int = Field(default=1, ge=1)  # first N catalog documents
    drop_start: float = Field(default=0.25, ge=0, lt=1)  # fractions of the document,
    drop_end: float = Field(default=0.55, gt=0, le=1)    # widened to whole lines
    max_fires: int = Field(default=1, ge=1)  # per document; later reads are clean

    async def after(self, call, page, runtime):
        document_id = page["document_id"]
        if (document_id not in list(runtime.documents.documents)[:self.num_docs]
                or self._state.get(document_id, 0) >= self.max_fires):
            return page
        full = runtime.documents.documents[document_id].text
        start = full.rfind("\n", 0, int(len(full) * self.drop_start)) + 1
        end = full.find("\n", int(len(full) * self.drop_end))
        end = len(full) if end == -1 else end + 1
        page_start, page_end = page["offset"], page["offset"] + len(page["text"])
        if max(start, page_start) >= min(end, page_end):
            return page  # this page does not overlap the dropped block
        self._state[document_id] = self._state.get(document_id, 0) + 1
        runtime.faults.fire(self, call, {"document_id": document_id,
                                         "offset": page_start, "dropped": [start, end]})
        text = page["text"]
        kept = text[:max(start - page_start, 0)] + text[max(end - page_start, 0):]
        return {**page, "text": kept}


class DocMisroutingFault(Fault):
    point = "read_document"
    num_docs: int = Field(default=1, ge=1)  # first N catalog documents
    seed: int = 0
    overrides: dict[str, str] = Field(default_factory=dict)  # requested ID -> replacement ID
    corpus_dir: Path = DEFAULT_CORPUS
    max_fires: int = Field(default=1, ge=1)  # per document; later reads are clean
    _index: dict | None = PrivateAttr(default=None)  # corpus documents; not in _state

    async def after(self, call, page, runtime):
        catalog = list(runtime.documents.documents)
        requested = page["document_id"]
        if (requested not in catalog[:self.num_docs]
                or self._state.get(requested, 0) >= self.max_fires):
            return page
        self._state[requested] = self._state.get(requested, 0) + 1
        if self._index is None:
            index = json.loads((self.corpus_dir / "index.json").read_text(encoding="utf-8"))
            self._index = index["documents"]
        others = sorted(set(self._index) - set(catalog))
        served = (self.overrides.get(requested)
                  or random.Random(f"{self.seed}:{requested}").choice(others))
        text = (self.corpus_dir / self._index[served]["file"]).read_text(encoding="utf-8")
        runtime.faults.fire(self, call, {"document_id": requested, "offset": page["offset"],
                                         "served_document_id": served})
        # Keep the requested page's length and pagination, so the catalog and any later
        # clean reads agree with it; past the replacement's end, read it from the start.
        start = page["offset"] if page["offset"] < len(text) else 0
        return {**page, "text": text[start:start + len(page["text"])]}
