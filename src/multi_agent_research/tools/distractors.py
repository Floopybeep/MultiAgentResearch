"""Deterministic TF-IDF distractor documents from the local corpus."""

import hashlib
import heapq
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..frames import prepare_documents
from .documents import OracleDocuments

TOKEN = re.compile(r"[a-z0-9]+")
TERMS = 200  # highest-weighted terms kept in each document vector


class DistractorIndex:
    """TF-IDF cosine neighbors over every corpus document; build once per batch."""

    def __init__(self, corpus_dir, document_index):
        self.corpus_dir, self.document_index = corpus_dir, document_index
        counts = {}
        for key, entry in document_index.items():
            text = (Path(corpus_dir) / entry["file"]).read_text(encoding="utf-8")
            counts[key] = Counter(TOKEN.findall(f"{entry['title']}\n{text}".lower()))
        df = Counter()
        for terms in counts.values():
            df.update(terms.keys())
        # A term found in only one document cannot match another.
        idf = {term: math.log(len(counts) / count) for term, count in df.items() if count > 1}
        self.vectors, self.postings = {}, defaultdict(list)
        for key, terms in counts.items():
            weights = {term: (1 + math.log(count)) * idf[term]
                       for term, count in terms.items() if term in idf}
            top = heapq.nlargest(TERMS, weights.items(), key=lambda item: item[1])
            norm = math.sqrt(sum(weight * weight for _, weight in top)) or 1.0
            self.vectors[key] = [(term, weight / norm) for term, weight in top]
            for term, weight in self.vectors[key]:
                self.postings[term].append((key, weight))

    def nearest(self, key, count, excluded):
        scores = defaultdict(float)
        for term, weight in self.vectors[key]:
            for other, other_weight in self.postings[term]:
                scores[other] += weight * other_weight
        candidates = [other for other in scores if other not in excluded]
        return heapq.nsmallest(count, candidates, key=lambda other: (-scores[other], other))

    def documents(self, oracle_ids, question_id, settings):
        """The sampled documents, copied under visible IDs `doc_01`, ... in catalog order, and
        metadata naming the oracle and distractor IDs and each one's corpus ID."""
        order, distractors = self.sample(oracle_ids, question_id, settings)
        corpus = prepare_documents(order, self.corpus_dir, self.document_index).documents
        corpus_doc_ids = {f"doc_{index:02d}": key for index, key in enumerate(order, 1)}
        visible = {key: name for name, key in corpus_doc_ids.items()}
        documents = OracleDocuments([corpus[key].model_copy(update={"document_id": name})
                                     for name, key in corpus_doc_ids.items()])
        return documents, {"oracle_doc_ids": [visible[key] for key in oracle_ids],
                           "distractor_doc_ids": [visible[key] for key in distractors],
                           "corpus_doc_ids": corpus_doc_ids}

    def sample(self, oracle_ids, question_id, settings):
        """Shuffled oracle plus distractor corpus IDs, and the distractors in selection order."""
        digest = hashlib.sha256(f"{settings.seed}:{question_id}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        budget = max(0, settings.max_total_docs - len(oracle_ids))
        queues, targets = [], []
        if budget:
            for key in oracle_ids:
                queue = self.nearest(key, settings.top_m, set(oracle_ids))
                rng.shuffle(queue)
                queues.append(queue)
                targets.append(rng.randint(settings.min_per_oracle, settings.max_per_oracle))
        distractors = round_robin(queues, targets, budget)
        documents = [*oracle_ids, *distractors]
        rng.shuffle(documents)
        return documents, distractors


def round_robin(queues, targets, budget):
    """One new ID per queue per round until the budget, every target or every queue is spent."""
    chosen, taken = [], [0] * len(queues)
    while len(chosen) < budget:
        before = len(chosen)
        for index, queue in enumerate(queues):
            while queue and queue[0] in chosen:
                queue.pop(0)
            if queue and taken[index] < targets[index] and len(chosen) < budget:
                chosen.append(queue.pop(0))
                taken[index] += 1
        if len(chosen) == before:
            break
    return chosen
