#!/usr/bin/env python3
"""Locate each question's reference answer in its own catalog documents.

Ground truth only: reads the local corpus and the FRAMES gold answers. Makes no
API calls and never consults model output, so a hallucinated worker finding
cannot influence the result.

For every question the script reports, per catalog document, the character
offsets at which the answer's distinguishing literal strings occur. An answer
that must be computed across documents appears as a literal nowhere; those are
classified "derived" when operands that produce it are found, rather than
"not_found".

Usage:
    python eval/locate_answer_evidence.py --ids eval/shared_10_question_ids.txt
    python eval/locate_answer_evidence.py            # all 50 baseline IDs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from multi_agent_research.frames import load_frames, select_examples  # noqa: E402

# Tokens too common to identify an answer-bearing document on their own.
STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "or", "for", "with",
    "by", "from", "as", "is", "was", "were", "be", "been", "it", "its", "that",
    "this", "he", "she", "they", "his", "her", "their", "him", "them", "which",
    "who", "whom", "what", "when", "where", "about", "into", "than", "then",
    "there", "these", "those", "has", "had", "have", "not", "no", "yes", "one",
    "two", "years", "year", "name", "named", "approximately", "about",
}

NUMBER = re.compile(r"\d[\d,]*\.?\d*")
# A capitalized run, allowing internal lowercase particles ("King of Spain").
PROPER = re.compile(r"\b[A-Z][\w'’\-]*(?:\s+(?:of|de|la|le|van|von|der|den|del|the|and)\s+[A-Z][\w'’\-]*|\s+[A-Z][\w'’\-]*)*")


def fold(text: str) -> str:
    """Case/width-fold without changing length, so offsets stay valid."""
    return unicodedata.normalize("NFKC", text).casefold()


def to_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def literals(answer: str) -> list[str]:
    """Distinguishing substrings of the answer, most specific first."""
    stripped = answer.strip().rstrip(".").strip()
    out: list[str] = []

    def add(value: str) -> None:
        value = value.strip().rstrip(".,;:").strip()
        if len(value) >= 2 and value.lower() not in STOPWORDS and value not in out:
            out.append(value)

    if len(stripped) >= 4:
        add(stripped)
    for match in PROPER.finditer(stripped):
        if len(match.group().split()) >= 1:
            add(match.group())
    for match in NUMBER.finditer(stripped):
        add(match.group())
    # Longest remaining content words, as a fallback for lowercase answers.
    for word in sorted(re.findall(r"[\w'’\-]{4,}", stripped), key=len, reverse=True)[:3]:
        add(word)
    return out


def find_all(haystack_folded: str, needle: str, limit: int = 6) -> list[int]:
    needle_folded = fold(needle)
    if not needle_folded:
        return []
    offsets, start = [], 0
    while len(offsets) < limit:
        at = haystack_folded.find(needle_folded, start)
        if at < 0:
            break
        offsets.append(at)
        start = at + 1
    return offsets


def numeric_variants(value: float) -> list[str]:
    """Spellings a corpus might use for the same quantity."""
    out = []
    if value == int(value):
        whole = int(value)
        out += [f"{whole:,}", str(whole)]
    else:
        out += [f"{value:,}", str(value)]
    return list(dict.fromkeys(out))


#: Below this, an operand pair hitting the target proves nothing: in any article
#: pair some two numbers differ by 9, so a one-digit answer always "derives".
DERIVE_MIN_TARGET = 1000


def derive(target: float, numbers: dict[str, list[tuple[str, int]]]) -> dict | None:
    """Find an operand pair across the catalog that yields the answer."""
    if abs(target) < DERIVE_MIN_TARGET:
        return None
    flat = [
        (raw, value, doc, off)
        for doc, items in numbers.items()
        for raw, off in items
        if (value := to_number(raw)) is not None
    ]
    # Prefer larger operands: "16,086 = 60,779 - 44,693" over "2 = 1 + 1".
    flat = [f for f in flat if abs(f[1]) >= 10]
    flat.sort(key=lambda f: -abs(f[1]))
    flat = flat[:400]
    for (a_raw, a, a_doc, a_off), (b_raw, b, b_doc, b_off) in combinations(flat, 2):
        for op, result in (("-", a - b), ("-", b - a), ("+", a + b)):
            if abs(result - target) < 1e-6 and abs(a) > abs(target) * 0.1:
                left, right = ((a_raw, a_doc, a_off), (b_raw, b_doc, b_off))
                if op == "-" and result == b - a:
                    left, right = right, left
                return {
                    "operation": f"{left[0]} {op} {right[0]}",
                    "operands": [
                        {"value": left[0], "document_id": left[1], "offset": left[2]},
                        {"value": right[0], "document_id": right[1], "offset": right[2]},
                    ],
                    "cross_document": left[1] != right[1],
                }
    return None


def analyze(example, corpus_dir: Path, document_index) -> dict:
    texts, numbers = {}, {}
    for key in example.document_ids:
        entry = document_index[key]
        raw = (corpus_dir / entry["file"]).read_text(encoding="utf-8")
        texts[key] = (raw, fold(raw), entry["title"])
        numbers[key] = [(m.group(), m.start()) for m in NUMBER.finditer(raw)]

    hits = []
    for needle in literals(example.answer):
        per_doc = {}
        for key, (_, folded, _) in texts.items():
            offsets = find_all(folded, needle)
            if offsets:
                per_doc[key] = offsets
        if per_doc:
            hits.append({
                "literal": needle,
                "documents": per_doc,
                "document_count": len(per_doc),
                "total_occurrences": sum(len(v) for v in per_doc.values()),
            })

    # A literal confined to one document locates the answer only if the literal is
    # specific enough to BE the answer. A 1-digit answer or a single word lifted out
    # of a longer phrase matches by coincidence: "9" hits the 9s in "(1919-1996)",
    # and "Theory" (from "The Theory of Vision") hits "Theory of optics". Those are
    # reported as weak_match, never as located evidence.
    stripped = (example.answer or "").strip().rstrip(".").strip()

    def specific(literal: str) -> bool:
        full = fold(literal) == fold(stripped)
        digits = literal.replace(",", "").replace(".", "")
        if digits.isdigit() and len(digits) < 4:
            return False
        if full:
            return len(literal) >= 4
        coverage = len(literal) / max(len(stripped), 1)
        return coverage >= 0.6 and len(literal) >= 8

    for hit in hits:
        hit["specific"] = specific(hit["literal"])

    unique = [h for h in hits if h["document_count"] == 1]
    unique.sort(key=lambda h: (not h["specific"], -len(h["literal"]),
                               h["total_occurrences"]))

    record = {
        "question_id": example.question_id,
        "answer": example.answer,
        "catalog": [
            {"document_id": k, "title": v[2], "characters": len(v[0])}
            for k, v in texts.items()
        ],
        "catalog_size": len(texts),
        "literals_searched": literals(example.answer),
        "hits": hits,
    }

    if unique:
        best = unique[0]
        doc = next(iter(best["documents"]))
        record["classification"] = "localized" if best["specific"] else "weak_match"
        record["answer_bearing_document"] = doc if best["specific"] else None
        record["evidence"] = {
            "literal": best["literal"],
            "document_id": doc,
            "offsets": best["documents"][doc],
            "title": texts[doc][2],
            "specific": best["specific"],
        }
        if not best["specific"]:
            record["evidence"]["caveat"] = (
                "Literal is too short or too small a fraction of the answer to "
                "identify it; the match is probably coincidental. Verify by hand "
                "before using this as a fault target."
            )
        return record

    if hits:
        record["classification"] = "ambiguous"
        record["answer_bearing_document"] = None
        record["evidence"] = {
            "note": "every matching literal occurs in more than one catalog document",
            "spread": {h["literal"]: h["documents"] for h in hits[:4]},
        }
        return record

    target = None
    found = NUMBER.search(example.answer or "")
    if found:
        target = to_number(found.group())
    if target is not None:
        for key, (_, folded, _) in texts.items():
            for variant in numeric_variants(target):
                digits = variant.replace(",", "").replace(".", "")
                if len(digits) < 4:
                    continue
                if find_all(folded, variant):
                    record["classification"] = "localized"
                    record["answer_bearing_document"] = key
                    record["evidence"] = {
                        "literal": variant, "document_id": key,
                        "offsets": find_all(folded, variant), "title": texts[key][2],
                    }
                    return record
        derivation = derive(target, numbers)
        if derivation:
            record["classification"] = "derived"
            record["answer_bearing_document"] = None
            record["evidence"] = derivation
            return record

    record["classification"] = "not_found"
    record["answer_bearing_document"] = None
    record["evidence"] = None
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ids", type=Path, default=Path("eval/baseline_50_question_ids.txt"))
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    ids = args.ids.read_text().split()
    examples, _, document_index = load_frames(args.corpus_dir)
    selected = select_examples(examples, question_ids=ids)

    records = [analyze(e, args.corpus_dir, document_index) for e in selected]

    counts: dict[str, int] = {}
    for record in records:
        counts[record["classification"]] = counts.get(record["classification"], 0) + 1

    width = max(len(r["question_id"]) for r in records)
    for record in records:
        doc = record["answer_bearing_document"] or "-"
        line = (f"Q{record['question_id']:<{width}}  {record['classification']:<10} "
                f"docs={record['catalog_size']}  bearer={doc:<9}")
        evidence = record["evidence"] or {}
        if record["classification"] == "localized":
            line += f"  {evidence['literal']!r} @ {evidence['offsets'][:3]}"
        elif record["classification"] == "derived":
            line += f"  {evidence['operation']} (cross_doc={evidence['cross_document']})"
        print(line)
    print()
    print("classification counts:", counts)

    if args.out:
        args.out.write_text(
            json.dumps({"counts": counts, "questions": records}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
