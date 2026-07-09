import json
import math
import re
from functools import lru_cache
from pathlib import Path


CORPUS_PATH = Path(__file__).with_name("data") / "tunisian_legal_corpus.jsonl"
STOPWORDS = {
    "avec", "aux", "ces", "dans", "des", "du", "elle", "elles", "est", "etre",
    "être", "les", "leur", "leurs", "par", "pas", "pour", "que", "qui", "sur",
    "une", "vous", "the", "and", "or", "من", "في", "على", "إلى", "عن", "ما",
}


def tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9']{3,}|[\u0600-\u06FF]{2,}", value.lower())
    return [token.strip("'") for token in tokens if token not in STOPWORDS]


@lru_cache(maxsize=1)
def load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        return []
    records = []
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                record["_tokens"] = tokenize(
                    " ".join([
                        record.get("title", ""),
                        record.get("heading", ""),
                        record.get("text", ""),
                    ])
                )
                records.append(record)
    return records


def corpus_status() -> dict:
    records = load_corpus()
    documents = sorted({record.get("doc_id") for record in records if record.get("doc_id")})
    return {
        "available": bool(records),
        "chunks": len(records),
        "documents": documents,
    }


def retrieve_legal_context(query: str, limit: int = 5) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    corpus = load_corpus()
    if not corpus:
        return []

    query_counts: dict[str, int] = {}
    for token in query_tokens:
        query_counts[token] = query_counts.get(token, 0) + 1
    total_docs = len(corpus)
    doc_freq: dict[str, int] = {}
    for token in query_counts:
        doc_freq[token] = sum(1 for record in corpus if token in set(record["_tokens"]))

    scored = []
    for record in corpus:
        tokens = record["_tokens"]
        if not tokens:
            continue
        token_counts: dict[str, int] = {}
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
        score = 0.0
        for token, query_count in query_counts.items():
            frequency = token_counts.get(token, 0)
            if not frequency:
                continue
            inverse_df = math.log((1 + total_docs) / (1 + doc_freq.get(token, 0))) + 1
            score += query_count * (1 + math.log(frequency)) * inverse_df
        if score:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, record in scored[:limit]:
        results.append({
            "id": record["id"],
            "title": record["title"],
            "filename": record["filename"],
            "page": record["page"],
            "heading": record.get("heading", ""),
            "excerpt": record["text"][:1400],
            "score": round(score, 3),
        })
    return results
