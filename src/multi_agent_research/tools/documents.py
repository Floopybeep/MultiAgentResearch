"""Question-scoped, paged reading of local Wikipedia article text."""

from typing import Any

from pydantic import BaseModel


class LocalDocument(BaseModel):
    document_id: str
    title: str
    url: str
    text: str

    def catalog_entry(self):
        return {**self.model_dump(exclude={"text"}), "characters": len(self.text)}


class OracleDocuments:
    """Only the current question's articles are visible to its agents."""

    def __init__(self, documents: list[LocalDocument]):
        if not documents:
            raise ValueError("At least one local document is required")
        self.documents = {doc.document_id: doc for doc in documents}

    def catalog(self):
        return [doc.catalog_entry() for doc in self.documents.values()]

    def read(self, key: str, offset: int, limit: int) -> dict[str, Any]:
        if key not in self.documents:
            raise ValueError("Document is outside this question's available documents")
        doc = self.documents[key]
        if offset < 0 or offset >= len(doc.text) or limit <= 0:
            raise ValueError("Document offset/limit is out of range")
        end = min(offset + limit, len(doc.text))
        return {
            "document_id": key, "title": doc.title, "url": doc.url,
            "offset": offset, "text": doc.text[offset:end], "total_characters": len(doc.text),
            "next_offset": end if end < len(doc.text) else None,
        }
