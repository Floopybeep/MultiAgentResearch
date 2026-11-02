"""Local FRAMES loading, seeded selection, and question-scoped article access."""

import ast
import csv
import json
import random
from pathlib import Path

from pydantic import BaseModel

from .tools.documents import LocalDocument, OracleDocuments

DEFAULT_CORPUS = Path("corpus")


class FramesExample(BaseModel):
    question_id: str
    question: str
    answer: str
    document_ids: list[str]
    original_wikipedia_urls: list[str]
    reasoning_types: list[str]


def load_frames(corpus_dir=DEFAULT_CORPUS):
    root = Path(corpus_dir)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    with (root / "frames.tsv").open(encoding="utf-8-sig", newline="") as stream:
        examples = [
            FramesExample(
                question_id=row[""], question=row["Prompt"].strip(), answer=row["Answer"].strip(),
                document_ids=index["questions"][row[""]],
                original_wikipedia_urls=ast.literal_eval(row["wiki_links"]),
                reasoning_types=[v.strip() for v in row["reasoning_types"].split("|") if v.strip()],
            )
            for row in csv.DictReader(stream, delimiter="\t")
        ]
    provenance = {
        "dataset": "google/frames-benchmark", "split": "test",
        "path": str(root / "frames.tsv"), "index_path": str(root / "index.json"),
        "total_questions": len(examples),
    }
    return examples, provenance, index["documents"]


def select_examples(examples: list[FramesExample], size=10, seed=42, question_ids=None):
    if question_ids is not None:
        indexed = {e.question_id: e for e in examples}
        if len(set(question_ids)) != len(question_ids) or not question_ids:
            raise ValueError("Question IDs must be a nonempty, unique list")
        missing = set(question_ids) - indexed.keys()
        if missing:
            raise ValueError(f"Unknown FRAMES question IDs: {sorted(missing)}")
        return [indexed[key] for key in question_ids]
    if not 1 <= size <= len(examples):
        raise ValueError(f"Sample size must be between 1 and {len(examples)}")
    return random.Random(seed).sample(examples, size)


def prepare_documents(example: FramesExample, corpus_dir, document_index):
    documents = []
    for key in example.document_ids:
        entry = document_index[key]
        documents.append(LocalDocument(
            document_id=key, title=entry["title"], url=entry["url"],
            text=(Path(corpus_dir) / entry["file"]).read_text(encoding="utf-8"),
        ))
    return OracleDocuments(documents)
