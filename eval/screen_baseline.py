#!/usr/bin/env python3
"""Screen repeated FRAMES baseline runs for a stable, injectable question subset.

Standalone and offline: reads batch manifests, run event logs and the local
corpus only. Makes no API calls and writes nothing outside its report paths.

Usage:
    python eval/screen_baseline.py runs/base1 runs/base2 runs/base3 \
        --corpus-dir corpus --out eval/screening_report.json

Each positional argument is either a batch manifest JSON or a run output
directory containing batches/*.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Answer normalization
# --------------------------------------------------------------------------

# Mirrors grading.normalize_answer (grading.py:17) so "strict" and "semantic"
# tiers are both anchored on the grader's own notion of equality.
def normalize_answer(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


# Canonical unit spellings, so "21 m" and "21 meters" collapse together.
UNIT_CANON = {
    "m": "meter", "metre": "meter", "metres": "meter", "meter": "meter", "meters": "meter",
    "km": "kilometer", "kilometre": "kilometer", "kilometres": "kilometer",
    "kilometer": "kilometer", "kilometers": "kilometer",
    "cm": "centimeter", "centimetre": "centimeter", "centimetres": "centimeter",
    "centimeter": "centimeter", "centimeters": "centimeter",
    "mm": "millimeter", "millimetre": "millimeter", "millimetres": "millimeter",
    "ft": "foot", "foot": "foot", "feet": "foot",
    # Bare "in" is deliberately absent: it is far more often the preposition
    # ("60,779 in 2021") than an inch abbreviation, and mapping it to "inch"
    # both mangles dates and lets it escape the STOPWORDS filter below.
    "inch": "inch", "inches": "inch",
    "mi": "mile", "mile": "mile", "miles": "mile",
    "kg": "kilogram", "kilogram": "kilogram", "kilograms": "kilogram",
    "g": "gram", "gram": "gram", "grams": "gram",
    "lb": "pound", "lbs": "pound", "pound": "pound", "pounds": "pound",
    "yr": "year", "yrs": "year", "year": "year", "years": "year",
    "mo": "month", "month": "month", "months": "month",
    "wk": "week", "week": "week", "weeks": "week",
    "d": "day", "day": "day", "days": "day",
    "hr": "hour", "hrs": "hour", "hour": "hour", "hours": "hour",
    "min": "minute", "mins": "minute", "minute": "minute", "minutes": "minute",
    "sec": "second", "secs": "second", "second": "second", "seconds": "second",
    "%": "percent", "pct": "percent", "percent": "percent", "percentage": "percent",
    "usd": "dollar", "dollar": "dollar", "dollars": "dollar",
    "m2": "squaremeter", "m²": "squaremeter", "sqm": "squaremeter",
    "km2": "squarekilometer", "km²": "squarekilometer",
}

ORDINAL_CANON = {
    "first": "1", "1st": "1", "second": "2", "2nd": "2", "third": "3", "3rd": "3",
    "fourth": "4", "4th": "4", "fifth": "5", "5th": "5", "sixth": "6", "6th": "6",
    "seventh": "7", "7th": "7", "eighth": "8", "8th": "8", "ninth": "9", "9th": "9",
    "tenth": "10", "10th": "10", "eleventh": "11", "11th": "11", "twelfth": "12",
    "12th": "12", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}

# Filler that varies freely between repetitions without changing the claim.
STOPWORDS = {"the", "a", "an", "of", "and", "or", "is", "was", "были", "approximately",
             "about", "around", "roughly", "circa", "ca", "approx", "at", "in", "on",
             "to", "it", "its", "that", "this", "with", "by", "for", "as", "which"}


def canon_number(token: str) -> str:
    """1,724 -> 1724; 21.0 -> 21; $2.7 -> 2.7."""
    stripped = token.replace(",", "").replace("$", "").replace("−", "-")
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        number = float(stripped)
        return str(int(number)) if number == int(number) else str(number)
    return token


def core_answer(value: str) -> str:
    """The leading claim, before any appended explanation.

    The Lead often puts the answer then a justification inside the braces
    ("81 years. The band watched..."). The tail varies freely between runs
    while the claim itself does not, so this is reported as a diagnostic
    alongside the two required stability tiers, never instead of them.
    """
    if not value:
        return ""
    head = re.split(r"\s+[—–-]\s+|(?<=[a-z0-9)\"'])\.\s+|;\s+|,\s+(?=[A-Z][a-z]{3})",
                    value.strip(), maxsplit=1)[0]
    return semantic_key(head.rstrip(" .,;:—–-"))


def semantic_key(value: str) -> str:
    """Order-preserving canonical form: units, ordinals, numbers and filler."""
    text = normalize_answer(value)
    # "6th" -> "6" FIRST, so the digit form matches the word form "sixth". This
    # must precede the digit/unit split below, which would otherwise turn "6th"
    # into "6 th" and leave a stray "th" token behind.
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    # Split "48m" into "48 m" so the unit canonicalizes.
    text = re.sub(r"(\d)\s*([a-z²³%]+)", r"\1 \2", text)
    text = re.sub(r"[\"'‘’“”]", "", text)
    tokens = re.findall(r"[a-z²³%]+|-?[\d.,]+\d|\d", text)
    out = []
    for token in tokens:
        # Drop filler before canonicalizing, so a stopword can never be
        # rewritten into a content token and survive the filter.
        if token in STOPWORDS:
            continue
        token = canon_number(token)
        token = UNIT_CANON.get(token, token)
        token = ORDINAL_CANON.get(token, token)
        out.append(token)
    return " ".join(fold_magnitudes(out))


MAGNITUDES = {"hundred": 100, "thousand": 1000, "million": 10 ** 6,
              "billion": 10 ** 9, "trillion": 10 ** 12}


def fold_magnitudes(tokens: list[str]) -> list[str]:
    """"2 million" -> "2000000", so it matches the digit form "2,000,000"."""
    out: list[str] = []
    for token in tokens:
        if token in MAGNITUDES and out:
            try:
                value = float(out[-1]) * MAGNITUDES[token]
            except ValueError:
                out.append(token)
                continue
            out[-1] = str(int(value)) if value == int(value) else str(value)
            continue
        out.append(token)
    return out


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def find_manifest(target: Path) -> Path:
    if target.is_file():
        return target
    candidates = sorted(target.glob("batches/*.json")) or sorted(target.glob("*.json"))
    if not candidates:
        raise SystemExit(f"No batch manifest found under {target}")
    if len(candidates) > 1:
        # Newest wins; batch ids are timestamp-prefixed, so sort order is time order.
        print(f"  note: {len(candidates)} manifests under {target}, using {candidates[-1].name}")
    return candidates[-1]


def worker_count(result: dict) -> int | None:
    workers = result.get("worker_results")
    if isinstance(workers, dict):
        return len(workers)
    if isinstance(workers, list):
        return len(workers)
    return None


def worker_docs(result: dict) -> list[str]:
    """Document IDs the workers reported reading, in assignment order."""
    workers = result.get("worker_results")
    values = workers.values() if isinstance(workers, dict) else (workers or [])
    out = []
    for entry in values:
        if isinstance(entry, dict):
            for key in entry.get("document_ids") or []:
                if key not in out:
                    out.append(key)
    return out


def load_run(target: Path) -> dict:
    path = find_manifest(target)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    per_question = {}
    for result in manifest.get("results", []):
        grade = result.get("grade") or {}
        per_question[str(result.get("question_id"))] = {
            "status": result.get("status"),
            "correct": grade.get("correct"),
            "method": grade.get("method"),
            "format_valid": grade.get("format_valid"),
            "exact_match": grade.get("exact_match"),
            "extracted_answer": grade.get("extracted_answer"),
            "judge_error": grade.get("error"),
            "reference_answer": result.get("reference_answer"),
            "question": result.get("question"),
            "answer": result.get("answer"),
            "workers": worker_count(result),
            "worker_docs": worker_docs(result),
            "usage": result.get("usage") or {},
            "run_id": result.get("run_id"),
            "output_dir": result.get("output_dir"),
            "duration_seconds": result.get("duration_seconds"),
        }
    return {
        "label": target.name,
        "manifest_path": str(path),
        "batch_id": manifest.get("batch_id"),
        "status": manifest.get("status"),
        "seed": manifest.get("seed"),
        "question_ids": [str(q) for q in manifest.get("question_ids", [])],
        "summary": manifest.get("summary") or {},
        "config": manifest.get("config") or {},
        "duration_seconds": manifest.get("duration_seconds"),
        "questions": per_question,
    }


# --------------------------------------------------------------------------
# Trace reading: which character spans did a worker actually read?
# --------------------------------------------------------------------------

def artifact(root: Path, ref: str):
    path = root / "artifacts" / f"{ref}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def read_spans(run_dir: Path) -> tuple[dict[str, list[tuple[int, int, str]]], set[str]]:
    """Return {document_id: [(start, end, agent)]} and the set of system_fingerprints."""
    spans: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    fingerprints: set[str] = set()
    db_path = run_dir / "events.sqlite"
    if not db_path.exists():
        return spans, fingerprints
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for (body,) in db.execute("select body from events order by sequence"):
            event = json.loads(body)
            kind = event.get("event_type")
            if kind not in ("tool.result", "model.response"):
                continue
            try:
                payload = artifact(run_dir, event["payload_ref"])
            except (OSError, ValueError, KeyError):
                continue
            if kind == "model.response":
                meta = (payload or {}).get("response_metadata") or {}
                if meta.get("system_fingerprint"):
                    fingerprints.add(meta["system_fingerprint"])
                continue
            if not isinstance(payload, dict) or "text" not in payload:
                continue
            doc = payload.get("document_id")
            offset = payload.get("offset")
            if not isinstance(doc, str) or not isinstance(offset, int):
                continue
            spans[doc].append((offset, offset + len(payload["text"]), event.get("agent_id", "?")))
    finally:
        db.close()
    return spans, fingerprints


def resolve_run_dir(entry: dict, roots: list[Path]) -> Path | None:
    candidate = entry.get("output_dir")
    if candidate:
        path = Path(candidate)
        if path.is_dir():
            return path
    run_id = entry.get("run_id")
    if run_id:
        for root in roots:
            for path in root.glob(f"*{run_id}"):
                if path.is_dir():
                    return path
    return None


def span_was_read(spans: dict, doc: str, start: int, end: int) -> str | None:
    for read_start, read_end, agent in spans.get(doc, []):
        if read_start <= start and end <= read_end:
            return agent
    return None


# --------------------------------------------------------------------------
# Injectability
# --------------------------------------------------------------------------

QUOTE_RE = re.compile(r'"([^"\n]{8,200})"')
# Numbers, dates and measurements carried by the gold answer.
SALIENT_RE = re.compile(
    r"\b\d[\d,.]*\s*(?:m|km|cm|mm|ft|mi|kg|g|lb|%|years?|months?|days?)\b"
    r"|\b(?:1[0-9]{3}|20[0-9]{2})\b"
    r"|\b\d[\d,.]*\b",
    re.IGNORECASE,
)
# Multi-word proper-noun entities carried by the gold answer, e.g.
# "Charles Muhanji" or "Subaru Impreza WRX". Two or more capitalized words,
# so single common capitalized words do not flood the candidate list.
ENTITY_RE = re.compile(r"\b[A-Z][\w.'-]*(?:\s+(?:[A-Z][\w.'-]*|of|the|de|von|van))*\b")

# Tier ranking: a confirmed gold-answer span is the strongest injection target,
# a bare small number the weakest.
TIER_RANK = {"gold_verbatim": 0, "gold_entity": 1, "gold_salient": 2, "worker_quoted": 3}


def gold_entities(reference: str) -> list[str]:
    """Proper-noun phrases of two or more words from the gold answer."""
    out = []
    for match in ENTITY_RE.finditer(reference):
        phrase = match.group(0).strip(" .,;:")
        words = phrase.split()
        if len(words) >= 2 and len(phrase) >= 6:
            out.append(phrase)
        # Also keep the trailing proper-noun run alone (e.g. "Subaru Impreza WRX"
        # inside "Charles Muhanji in a Subaru Impreza WRX").
        if len(words) > 2:
            out.append(" ".join(words[-2:]))
    return list(dict.fromkeys(out))


def content_tokens(value: str) -> set[str]:
    """Lowercased content words and numbers, filler removed."""
    return {t for t in re.findall(r"[a-z]{3,}|\d[\d,.]*", (value or "").casefold())
            if t not in STOPWORDS}


def shares_answer_token(span: str, reference: str) -> bool:
    """Does the span carry any content token of the gold answer?

    A span can be read and even quoted by a worker without bearing on the
    answer at all. Q353 is the worked example: the worker quoted a casualty
    count from the Columbine article while the question turned on a date, so
    corrupting that sentence would very likely change nothing. Token overlap
    with the gold answer is a crude but cheap relevance filter.
    """
    return bool(content_tokens(span) & content_tokens(reference))


def weak_candidate(tier: str, span: str) -> bool:
    """A bare one-or-two-digit number is too common to be a defensible target."""
    bare = span.strip().rstrip(".,;:")
    return tier == "gold_salient" and bare.isdigit() and len(bare) <= 2


def locate(haystack: str, needle: str) -> int:
    """Case-insensitive literal search; -1 if absent."""
    if not needle:
        return -1
    return haystack.casefold().find(needle.casefold())


def injectability(question_id: str, entry: dict, corpus_dir: Path, doc_index: dict,
                  doc_ids: list[str], spans_per_run: dict[str, dict]) -> dict:
    """Find an answer-relevant, corruptible source span.

    Tiers, strongest first:
      gold_verbatim  - the gold answer appears literally in a gold document
      gold_entity    - a proper-noun entity of the gold answer ("Charles Muhanji")
      gold_salient   - a numeric/date token of the gold answer; an intermediate
                       fact needed to derive it rather than the answer itself
      worker_quoted  - a span the baseline worker quoted back in its findings,
                       so it is provably evidence that reached the worker
    Questions whose gold answer is absent verbatim are NOT excluded: a
    derivable intermediate fact still counts.

    IMPORTANT, on what the read-verification does and does not establish.
    Three separate claims must not be conflated:
      1. a worker read a page covering the span      <- the trace proves this
      2. the span is an answer-relevant fact         <- the tier is evidence
      3. the worker RELIED on it to derive a finding <- NOT established here
    `echoed_in_findings` is circumstantial evidence for (3): the span text
    reappears in what the worker reported. It is still not proof of causal
    reliance; a worker may quote a passage it did not depend on, or derive an
    answer from a different passage carrying the same fact. Treat the output
    as a ranked shortlist for manual inspection, not as a verified causal set.
    Because worker assignments vary between runs, coverage is computed PER RUN
    and `read_in_all_runs` reports whether the span would reach a worker in
    every repetition. A span read in only some runs makes a fault intermittent.
    """
    texts = {}
    for key in doc_ids:
        meta = doc_index.get(key)
        if not meta:
            continue
        path = corpus_dir / meta["file"]
        if path.exists():
            texts[key] = path.read_text(encoding="utf-8")

    reference = (entry.get("reference_answer") or "").strip()
    candidates: list[dict] = []

    findings_by_run = entry.get("_findings_by_run") or {}
    run_labels = list(spans_per_run) or list(findings_by_run)

    def add(tier: str, needle: str, note: str = "") -> None:
        for key, text in texts.items():
            at = locate(text, needle)
            if at < 0:
                continue
            end = at + len(needle)
            span_text = text[at:end]
            folded = span_text.casefold()
            # Redundancy: if the same fact is stated elsewhere in this document
            # or in a sibling gold document, corrupting ONE occurrence may be
            # neutralised by the duplicate and produce no observable effect.
            occurrences = text.casefold().count(folded)
            also_in = [k for k, other in texts.items()
                       if k != key and folded in other.casefold()]
            # Per-run coverage: which repetitions actually read this span.
            readers = {label: span_was_read(spans, key, at, end)
                       for label, spans in spans_per_run.items()}
            read_in = [label for label, who in readers.items() if who]
            # Circumstantial evidence of reliance: the worker echoed the span.
            echoed_in = [label for label, texts_ in findings_by_run.items()
                         if any(locate(t, span_text) >= 0 for t in texts_)]
            candidates.append({
                "tier": tier,
                "document_id": key,
                "title": (doc_index.get(key) or {}).get("title"),
                "char_offset": at,
                "char_end": end,
                "span": span_text,
                "context": text[max(0, at - 60):end + 60].replace("\n", " "),
                "read_by_worker": next((w for w in readers.values() if w), None),
                "read_by_worker_per_run": readers,
                "read_in_runs": read_in,
                "read_in_all_runs": bool(run_labels) and len(read_in) == len(run_labels),
                "echoed_in_runs": echoed_in,
                "echoed_in_all_runs": bool(run_labels) and len(echoed_in) == len(run_labels),
                "verified_read": bool(read_in),
                "occurrences_in_document": occurrences,
                "also_in_documents": also_in,
                "redundant": occurrences > 1 or bool(also_in),
                # Relevance: tiers derived from the gold answer are relevant by
                # construction; a worker-quoted span must earn it by overlap.
                "shares_answer_token": tier != "worker_quoted"
                                       or shares_answer_token(span_text, reference),
                "weak": weak_candidate(tier, span_text),
                "note": note,
            })
            return  # first containing document is enough per needle

    if reference:
        add("gold_verbatim", reference, "gold answer appears literally in a gold document")
        # Strip a trailing period etc., which often blocks a verbatim hit.
        trimmed = reference.rstrip(" .")
        if not candidates and trimmed != reference:
            add("gold_verbatim", trimmed, "gold answer, trailing punctuation removed")

    if reference:
        for phrase in gold_entities(reference):
            add("gold_entity", phrase, "proper-noun entity carried by the gold answer")
        for token in dict.fromkeys(m.group(0) for m in SALIENT_RE.finditer(reference)):
            token = token.strip()
            if len(token) >= 2:
                add("gold_salient", token,
                    "numeric/date fact from the gold answer, or needed to derive it")

    # Spans the worker itself quoted are provably evidence that reached the worker.
    quoted: list[str] = []
    for findings in entry.get("_findings", []):
        quoted.extend(QUOTE_RE.findall(findings))
    for needle in dict.fromkeys(quoted):
        if len(candidates) >= 12:
            break
        add("worker_quoted", needle.strip(), "verbatim evidence quoted by a baseline worker")

    # Rank: read in every run first, then echoed in findings, then tier
    # strength, then the longest (most specific) span.
    # A unique (non-redundant) span is a better target than a duplicated one,
    # since corrupting a duplicated fact may be silently neutralised.
    candidates.sort(key=lambda c: (
        not c["read_in_all_runs"], not c["shares_answer_token"],
        not c["echoed_in_all_runs"], c["redundant"],
        TIER_RANK.get(c["tier"], 9), c["weak"], -len(c["span"])))
    # `confirmed` now demands coverage in ALL runs, not just one.
    confirmed = [c for c in candidates
                 if c["read_in_all_runs"] and not c["weak"]
                 and c["shares_answer_token"]]
    irrelevant = [c for c in candidates
                  if c["read_in_all_runs"] and not c["weak"]
                  and not c["shares_answer_token"]]
    partial = [c for c in candidates
               if c["verified_read"] and not c["read_in_all_runs"] and not c["weak"]]
    weak_only = [c for c in candidates if c["verified_read"] and c["weak"]]
    unverified = [c for c in candidates if not c["verified_read"]]
    if confirmed:
        status = "injectable"
    elif irrelevant:
        status = "uncertain_relevance"   # read, but no token overlap with the answer
    elif partial:
        status = "uncertain_partial_read"  # read in some runs only: intermittent fault
    elif weak_only:
        status = "uncertain_weak"     # only a bare small number was locatable
    elif unverified:
        status = "uncertain_unread"   # span exists but no trace proof a worker read it
    else:
        status = "uncertain_nospan"   # no corruptible span located automatically
    best = (confirmed or irrelevant or partial or weak_only or candidates or [None])[0]
    return {
        "status": status,
        "injectable": bool(confirmed),
        "exposure_only": True,
        "reliance_established": False,
        "caveat": "read_in_all_runs proves exposure, not that the worker relied on "
                  "the span. echoed_in_runs is circumstantial only. Inspect manually "
                  "before injecting.",
        "n_candidates": len(candidates),
        "best": best,
        "best_echoed_in_all_runs": bool(best and best.get("echoed_in_all_runs")),
        "best_redundant": bool(best and best.get("redundant")),
        "best_shares_answer_token": bool(best and best.get("shares_answer_token")),
        "relevance_unverified": [c for c in irrelevant[:3]],
        "unique_confirmed": [c for c in confirmed if not c["redundant"]][:3],
        "has_unique_target": any(not c["redundant"] for c in confirmed),
        "partial_read": partial[:3],
        "best_tier": (best or {}).get("tier"),
        "confirmed": confirmed[:4],
        "weak_only": weak_only[:3],
        "unverified": unverified[:3],
        "gold_answer_in_corpus": any(c["tier"] == "gold_verbatim" for c in candidates),
        "documents_available": sorted(texts),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def corpus_fingerprint(corpus_dir: Path) -> str:
    try:
        out = subprocess.run(
            f"find {corpus_dir} -name '*.md' | sort | xargs shasum | shasum",
            shell=True, capture_output=True, text=True, check=True).stdout
        return out.split()[0]
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path,
                        help="Batch manifest JSONs or run output directories")
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--out", type=Path, default=Path("eval/screening_report.json"))
    parser.add_argument("--require-exact-match", action="store_true",
                        help="Treat method==exact_match as an eligibility filter rather "
                             "than a reported statistic (default: report only)")
    args = parser.parse_args()

    print("Loading batch manifests")
    runs = [load_run(target) for target in args.runs]
    for run in runs:
        print(f"  {run['label']:<10} {run['manifest_path']}  status={run['status']} "
              f"questions={len(run['questions'])}")

    # ---- question universe, and a hard check that the sets really match ----
    id_sets = [set(run["questions"]) for run in runs]
    common = sorted(set.intersection(*id_sets), key=lambda q: int(q) if q.isdigit() else 0)
    mismatch = sorted(set.union(*id_sets) - set.intersection(*id_sets),
                      key=lambda q: int(q) if q.isdigit() else 0)
    if mismatch:
        print(f"\n  WARNING: {len(mismatch)} question ids are not present in all runs: {mismatch}")

    # ---- config / fingerprint drift across runs ----
    # output_dir necessarily differs (one directory per run), so it is excluded:
    # otherwise every correctly-separated 3x experiment looks mis-configured.
    def experimental_config(run):
        return {k: v for k, v in (run["config"] or {}).items() if k != "output_dir"}

    config_keys = {json.dumps(experimental_config(run), sort_keys=True) for run in runs}
    corpus_dir = args.corpus_dir
    index = json.loads((corpus_dir / "index.json").read_text(encoding="utf-8"))
    doc_index, question_docs = index["documents"], index["questions"]

    # ---- per-run accuracy, format validity, grading method ----
    print("\n" + "=" * 78)
    print("PER-RUN RESULTS  (ungraded is counted separately from incorrect)")
    print("=" * 78)
    header = f"{'run':<10}{'n':>4}{'correct':>9}{'wrong':>7}{'noanswer':>10}{'ungraded':>10}" \
             f"{'fmt_ok':>8}{'exact':>7}{'judge':>7}{'jerr':>6}{'cost$':>9}{'wall_s':>9}"
    print(header)
    per_run_stats = []
    for run in runs:
        rows = [run["questions"][q] for q in common]
        correct = sum(r["correct"] is True for r in rows)
        # runner.py:88 records an unanswered task as correct=False/method=not_answered,
        # so a question that never produced an answer is otherwise indistinguishable
        # from a wrong answer. Split it out: execution failure is not a wrong answer.
        not_answered = sum(r["method"] == "not_answered" for r in rows)
        incorrect = sum(r["correct"] is False and r["method"] != "not_answered" for r in rows)
        ungraded = sum(r["correct"] is None for r in rows)
        completed = sum(r["status"] == "completed" for r in rows)
        statuses = Counter(r["status"] for r in rows)
        fmt_ok = sum(bool(r["format_valid"]) for r in rows)
        methods = Counter(r["method"] for r in rows)
        stats = {
            "label": run["label"], "batch_id": run["batch_id"], "n": len(rows),
            "correct": correct, "incorrect": incorrect, "ungraded": ungraded,
            "not_answered": not_answered, "completed": completed,
            "status_counts": dict(statuses),
            "accuracy_of_all": correct / len(rows) if rows else None,
            "accuracy_of_graded": correct / (correct + incorrect) if (correct + incorrect) else None,
            "accuracy_of_completed": correct / completed if completed else None,
            "format_valid": fmt_ok,
            "format_valid_rate": fmt_ok / len(rows) if rows else None,
            "method_counts": dict(methods),
            "summary_from_manifest": run["summary"],
            "duration_seconds": run["duration_seconds"],
        }
        per_run_stats.append(stats)
        print(f"{run['label']:<10}{len(rows):>4}{correct:>9}{incorrect:>7}{not_answered:>10}{ungraded:>10}"
              f"{fmt_ok:>8}{methods.get('exact_match', 0):>7}{methods.get('llm_judge', 0):>7}"
              f"{methods.get('judge_error', 0):>6}"
              f"{run['summary'].get('estimated_cost_usd') or 0:>9.4f}"
              f"{run['duration_seconds'] or 0:>9.1f}")

    # ---- stability, variance, worker counts ----
    print("\n" + "=" * 78)
    print("PER-QUESTION STABILITY")
    print("=" * 78)
    questions: dict[str, dict] = {}
    for qid in common:
        rows = [run["questions"][qid] for run in runs]
        answers = [r["extracted_answer"] for r in rows]
        grades = [r["correct"] for r in rows]
        methods = [r["method"] for r in rows]
        workers = [r["workers"] for r in rows]
        strict = len({a if a is not None else "\0None" for a in answers}) == 1
        semantic = len({semantic_key(a) if a else "\0None" for a in answers}) == 1
        questions[qid] = {
            "question_id": qid,
            "reference_answer": rows[0]["reference_answer"],
            "question": rows[0]["question"],
            "answers": answers,
            "semantic_keys": [semantic_key(a) if a else None for a in answers],
            "grades": grades,
            "methods": methods,
            "format_valid": [r["format_valid"] for r in rows],
            "worker_counts": workers,
            "statuses": [r["status"] for r in rows],
            "all_correct": all(g is True for g in grades),
            "any_ungraded": any(g is None for g in grades),
            "grade_stable": len(set(grades)) == 1,
            "strictly_stable": strict,
            "semantically_stable": semantic,
            "core_answers": [core_answer(a) if a else None for a in answers],
            "core_answer_stable": len({core_answer(a) if a else "\0None"
                                       for a in answers}) == 1,
            "any_not_answered": any(m == "not_answered" for m in methods),
            "all_not_answered": all(m == "not_answered" for m in methods),
            "all_exact_match": all(m == "exact_match" for m in methods),
            "any_exact_match": any(m == "exact_match" for m in methods),
            "worker_count_stable": len({w for w in workers}) == 1,
            "worker_docs": rows[0]["worker_docs"],
            "_findings": [],
            "_findings_by_run": {},
        }

    answer_changed = [q for q, v in questions.items() if not v["strictly_stable"]]
    semantic_changed = [q for q, v in questions.items() if not v["semantically_stable"]]
    grade_changed = [q for q, v in questions.items() if not v["grade_stable"]]
    worker_changed = [q for q, v in questions.items() if not v["worker_count_stable"]]
    print(f"  answer string changed between runs : {len(answer_changed):>3}/{len(common)}  {answer_changed}")
    print(f"  answer meaning changed (normalized): {len(semantic_changed):>3}/{len(common)}  {semantic_changed}")
    print(f"  GRADE flipped between runs         : {len(grade_changed):>3}/{len(common)}  {grade_changed}")
    print(f"  worker count varied between runs   : {len(worker_changed):>3}/{len(common)}  {worker_changed}")
    never = [q for q, v in questions.items() if v["all_not_answered"]]
    some = [q for q, v in questions.items() if v["any_not_answered"] and not v["all_not_answered"]]
    print(f"  NO ANSWER in all runs (exec failure): {len(never):>3}/{len(common)}  {never}")
    print(f"  NO ANSWER in some runs (flaky exec) : {len(some):>3}/{len(common)}  {some}")
    # Diagnostic: how much of the instability is only a varying trailing
    # justification rather than a different claim.
    tail_only = [q for q, v in questions.items()
                 if not v["semantically_stable"] and v["core_answer_stable"]
                 and not v["any_not_answered"]]
    print(f"  of the unstable, CORE claim identical  : {len(tail_only):>3}      {tail_only}")
    print("      (same leading answer, different appended justification)")

    # ---- traces: read spans and endpoint fingerprints ----
    print("\nReading run traces for read-spans and endpoint fingerprints")
    roots = [t if t.is_dir() else t.parent.parent for t in args.runs]
    all_fingerprints: set[str] = set()
    # Spans are kept PER RUN, never merged. Worker assignments vary between
    # repetitions, so a span read in one run may never be read in another; a
    # fault planted there would simply not reach a worker in those runs.
    spans_by_question: dict[str, dict[str, dict]] = {}
    for qid in common:
        per_run: dict[str, dict] = {}
        for run in runs:
            entry = run["questions"][qid]
            run_dir = resolve_run_dir(entry, roots)
            if run_dir is None:
                per_run[run["label"]] = {}
                continue
            spans, fps = read_spans(run_dir)
            all_fingerprints |= fps
            per_run[run["label"]] = spans
        spans_by_question[qid] = per_run
    print(f"  endpoint system_fingerprint values seen: {sorted(all_fingerprints) or ['none']}")
    if len(all_fingerprints) > 1:
        print("  WARNING: endpoint build changed mid-experiment; runs are not comparable.")

    # recover worker findings text per run, so "did the worker echo this span"
    # can be answered run by run rather than pooled across repetitions
    for run in runs:
        manifest = json.loads(Path(run["manifest_path"]).read_text(encoding="utf-8"))
        for result in manifest.get("results", []):
            qid = str(result.get("question_id"))
            if qid not in questions:
                continue
            workers = result.get("worker_results")
            values = workers.values() if isinstance(workers, dict) else (workers or [])
            texts = [e["findings"] for e in values
                     if isinstance(e, dict) and e.get("findings")]
            questions[qid]["_findings_by_run"][run["label"]] = texts
            questions[qid]["_findings"].extend(texts)

    # ---- injectability ----
    print("\n" + "=" * 78)
    print("INJECTABILITY")
    print("=" * 78)
    for qid, record in questions.items():
        docs = question_docs.get(qid) or record["worker_docs"]
        record["injectability"] = injectability(
            qid, {**record, "reference_answer": record["reference_answer"]},
            corpus_dir, doc_index, docs, spans_by_question.get(qid, {}))
    inj_counts = Counter(v["injectability"]["status"] for v in questions.values())
    print(f"  span read in ALL runs (exposure confirmed): {inj_counts.get('injectable', 0)}")
    print(f"  read, but NO token overlap with the answer: {inj_counts.get('uncertain_relevance', 0)}"
          f"   <- relevance unverified")
    print(f"  span read in SOME runs only (intermittent): {inj_counts.get('uncertain_partial_read', 0)}")
    print(f"  uncertain, only a bare small number    : {inj_counts.get('uncertain_weak', 0)}")
    print(f"  uncertain, span found but read unproven : {inj_counts.get('uncertain_unread', 0)}")
    print(f"  uncertain, no span located             : {inj_counts.get('uncertain_nospan', 0)}")
    print(f"  gold answer verbatim in corpus         : "
          f"{sum(v['injectability']['gold_answer_in_corpus'] for v in questions.values())}")
    echoed = sum(v['injectability']['best_echoed_in_all_runs'] for v in questions.values())
    print(f"  target ALSO echoed in findings, all runs : {echoed}"
          f"   <- circumstantial reliance evidence, not proof")
    red = sum(v['injectability']['best_redundant'] for v in questions.values())
    uniq = sum(v['injectability']['has_unique_target'] for v in questions.values())
    print(f"  best target is REDUNDANT (dup in doc/sibling): {red}"
          f"   <- corrupting one copy may be neutralised")
    print(f"  has at least one UNIQUE confirmed target     : {uniq}")
    print("  NOTE: exposure is proven; causal reliance is NOT. Inspect manually.")

    # ---- eligibility ----
    eligible, near_miss, excluded = [], [], []
    for qid, v in questions.items():
        reasons = []
        if v["any_not_answered"]:
            reasons.append(
                f"execution failure in {sum(m == 'not_answered' for m in v['methods'])}/"
                f"{len(v['methods'])} runs (no answer produced; not a wrong answer)")
        elif not v["all_correct"]:
            reasons.append("not correct in all 3 runs")
        if not v["semantically_stable"]:
            reasons.append("answer meaning unstable")
        if not v["injectability"]["injectable"]:
            reasons.append(f"injectability {v['injectability']['status']}")
        if args.require_exact_match and not v["all_exact_match"]:
            reasons.append("not exact_match in all runs")
        v["eligibility_reasons"] = reasons
        if not reasons:
            eligible.append(qid)
        elif v["all_correct"] and v["semantically_stable"]:
            near_miss.append(qid)
        else:
            excluded.append(qid)

    strict_eligible = [q for q in eligible if questions[q]["strictly_stable"]]
    semantic_only = [q for q in eligible if not questions[q]["strictly_stable"]]
    exact_eligible = [q for q in eligible if questions[q]["all_exact_match"]]

    print("\n" + "=" * 78)
    print("ELIGIBLE QUESTION SET")
    print("=" * 78)
    order = lambda s: sorted(s, key=lambda q: int(q) if q.isdigit() else 0)
    print(f"  YIELD: {len(eligible)}/{len(common)} stable, correct and injectable")
    print(f"  eligible ids          : {' '.join(order(eligible))}")
    print(f"    strictly stable     : {len(strict_eligible)}  {' '.join(order(strict_eligible))}")
    print(f"    semantically only   : {len(semantic_only)}  {' '.join(order(semantic_only))}")
    print(f"    graded by exact_match in all runs: {len(exact_eligible)}  {' '.join(order(exact_eligible))}")
    print(f"  needs manual review   : {len(near_miss)}  {' '.join(order(near_miss))}")
    print(f"  excluded              : {len(excluded)}  {' '.join(order(excluded))}")

    # ---- totals ----
    def total(field: str) -> int:
        return sum((run["summary"] or {}).get(field) or 0 for run in runs)

    cost = sum((run["summary"] or {}).get("estimated_cost_usd") or 0 for run in runs)
    print("\n" + "=" * 78)
    print("TOTALS ACROSS ALL RUNS")
    print("=" * 78)
    print(f"  input tokens  : {total('input_tokens'):,}")
    print(f"  output tokens : {total('output_tokens'):,}")
    print(f"  model calls   : {total('model_calls'):,}")
    print(f"  estimated cost: ${cost:.4f}   (configured rates x returned usage, not a bill)")
    print(f"  wall clock    : {sum(r['duration_seconds'] or 0 for r in runs):.1f}s")

    for v in questions.values():
        v.pop("_findings", None)
        v.pop("_findings_by_run", None)

    report = {
        "provenance": {
            "git_commit": git_commit(),
            "corpus_fingerprint": corpus_fingerprint(corpus_dir),
            "model": (runs[0]["config"].get("lead") or {}).get("model"),
            "config_identical_across_runs": len(config_keys) == 1,
            "resolved_config_sha256": __import__("hashlib").sha256(
                json.dumps(experimental_config(runs[0]), sort_keys=True).encode()).hexdigest(),
            "config_hash_excludes": ["output_dir"],
            "output_dirs": [str((r["config"] or {}).get("output_dir")) for r in runs],
            "endpoint_system_fingerprints": sorted(all_fingerprints),
            "endpoint_stable": len(all_fingerprints) <= 1,
            "runs": [{"label": r["label"], "batch_id": r["batch_id"],
                      "manifest": r["manifest_path"], "status": r["status"],
                      "timestamp_from_batch_id": (r["batch_id"] or "")[:13],
                      "duration_seconds": r["duration_seconds"]} for r in runs],
            "question_ids": common,
            "question_ids_not_in_all_runs": mismatch,
        },
        "per_run": per_run_stats,
        "variance": {
            "answer_string_changed": order(answer_changed),
            "answer_meaning_changed": order(semantic_changed),
            "grade_flipped": order(grade_changed),
            "worker_count_varied": order(worker_changed),
            "n_questions": len(common),
        },
        "core_answer_diagnostic": {
            "unstable_but_core_identical": order(
                [q for q, v in questions.items()
                 if not v["semantically_stable"] and v["core_answer_stable"]
                 and not v["any_not_answered"]]),
            "note": "Excluded by the semantic-stability criterion, but the leading "
                    "claim matched in all runs; only the appended justification "
                    "varied. Reported for manual review, not auto-included.",
        },
        "injectability_counts": dict(inj_counts),
        "injectability_caveats": {
            "exposure_not_reliance": "A confirmed target means a worker read a page "
                "covering the span in every run. It does NOT establish that the worker "
                "relied on that span to derive its finding.",
            "echo_is_circumstantial": "echoed_in_runs means the span text reappears in "
                "the worker's reported findings. Suggestive of use, not proof.",
            "redundancy": "Spans marked redundant occur more than once in their document "
                "or also appear in a sibling gold document; a single-span corruption may "
                "be neutralised by the duplicate.",
            "first_page_bias": "Most targets fall within the first max_document_chars "
                "page, which workers almost always read, so read_in_all_runs is a weak "
                "discriminator here.",
            "recommendation": "Inspect targets by hand before injecting; prefer "
                "unique_confirmed targets.",
        },
        "execution_failures": {
            "no_answer_all_runs": order([q for q, v in questions.items() if v["all_not_answered"]]),
            "no_answer_some_runs": order([q for q, v in questions.items()
                                          if v["any_not_answered"] and not v["all_not_answered"]]),
            "note": "runner.py:88 stores these as correct=False, so benchmark.summarize "
                    "counts them in `incorrect`. They are execution failures, not wrong answers.",
        },
        "eligible": {
            "ids": order(eligible),
            "yield": f"{len(eligible)}/{len(common)}",
            "strictly_stable": order(strict_eligible),
            "semantically_stable_only": order(semantic_only),
            "exact_match_in_all_runs": order(exact_eligible),
        },
        "manual_review": order(near_miss),
        "excluded": order(excluded),
        "totals": {
            "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"),
            "model_calls": total("model_calls"),
            "estimated_cost_usd": cost,
        },
        "questions": questions,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
