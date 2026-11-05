"""Does the oracle catalog's metadata alone reveal a question's gold answer?

`catalog_entry()` is `model_dump(exclude={"text"})` (tools/documents.py:14-15), so
every non-text field reaches the Lead, including `title`. Where the gold answer is
also a document title, denying that document's body cannot deny the answer, and a
ROUTED_AROUND verdict says more about the harness than about the system under test.

`direct` is computed: gold and title agree after normalization, or one contains the
other. `soft` cannot be computed -- it needs world knowledge that two different names
denote the same thing -- so it is a reviewed annotation, listed in SOFT_LEAKS with its
reason. `review` flags partial word overlap for a human to rule on.
"""

import json
import re
import unicodedata
from pathlib import Path

ARTICLES = ("the ", "a ", "an ")

# Reviewed by hand; a computed check cannot see these.
SOFT_LEAKS = {
    ("224", "doc_0728"): "Gold 'Verizon Center' and title 'Capital One Arena' are the "
                         "same venue, renamed in 2017; bridgeable from world knowledge.",
}


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse spaces, drop a leading article."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for article in ARTICLES:
        if text.startswith(article):
            return text[len(article):]
    return text


def classify(gold: str, title: str, question_id: str, document_id: str):
    """direct / soft / review / none, with the evidence for the verdict."""
    g, t = normalize(gold), normalize(title)
    if g and t and (g == t or g in t or t in g):
        return "direct", f"gold '{g}' vs title '{t}'"
    if (question_id, document_id) in SOFT_LEAKS:
        return "soft", SOFT_LEAKS[(question_id, document_id)]
    gw, tw = set(g.split()), set(t.split())
    shared = gw & tw
    if shared and len(shared) / min(len(gw), len(tw)) >= 0.5:
        return "review", f"shared words {sorted(shared)}: gold '{g}' vs title '{t}'"
    return "none", ""


def leaks(question_ids, corpus_dir=Path("corpus"), report=Path("eval/v2_screening_report.json")):
    """Per (question, document) pair: the leak verdict against that document's title."""
    index = json.loads((corpus_dir / "index.json").read_text())
    questions = json.loads(report.read_text())["questions"]
    out = {}
    for qid in question_ids:
        gold = questions[qid]["reference_answer"]
        for doc in index["questions"][qid]:
            title = index["documents"][doc]["title"]
            verdict, evidence = classify(gold, title, qid, doc)
            out[(qid, doc)] = {"title": title, "gold": gold,
                               "title_leak": verdict, "evidence": evidence}
    return out


if __name__ == "__main__":
    ids = Path("eval/shared_10_question_ids.txt").read_text().split()
    table = leaks(ids)
    for (qid, doc), row in table.items():
        mark = "" if row["title_leak"] == "none" else "  <<<"
        print(f"{qid:>4} {doc} {row['title_leak']:<7} {row['title'][:42]:<42} "
              f"gold={row['gold'][:34]!r}{mark}")
        if row["evidence"]:
            print(f"       {row['evidence']}")
