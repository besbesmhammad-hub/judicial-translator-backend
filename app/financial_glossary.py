from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path(__file__).with_name("data")
HQ_GLOSSARY_PATH = DATA_DIR / "financial_terms_trilingual_hq.jsonl"
GLOSSARY_PATH = DATA_DIR / "financial_terms_trilingual.jsonl"
GLOSSARY_STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "un", "une", "et", "ou", "sur", "sous", "pour",
    "par", "dans", "aux", "au", "en", "of", "the", "and", "for", "with", "from", "to",
    "on", "in", "at",
}


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_glossary_text(value: str) -> str:
    text = _strip_accents((value or "").lower())
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^0-9a-z\u0600-\u06FF+' -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize_glossary_text(value: str) -> list[str]:
    tokens = re.findall(r"[0-9a-z]{2,}|[\u0600-\u06FF]{2,}", normalize_glossary_text(value))
    return [token for token in tokens if token not in GLOSSARY_STOPWORDS]


def _latin_quality(value: str) -> float:
    text = (value or "").strip()
    if not text:
        return 0.0
    letters = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
    weird = len(re.findall(r"[^A-Za-zÀ-ÿ0-9'()\-.,/ ]", text))
    vowels = len(re.findall(r"[AEIOUYaeiouyÀ-ÿ]", text))
    ratio = letters / max(len(text), 1)
    vowel_ratio = vowels / max(letters, 1)
    score = ratio * 0.6 + min(vowel_ratio, 0.55) * 0.8 - weird * 0.08
    return max(0.0, min(score, 1.0))


def _prepare_record(record: dict) -> dict:
    record["_search_blob"] = " ".join(
        filter(
            None,
            [
                record.get("fr", ""),
                record.get("en", ""),
                record.get("ar", ""),
                record.get("fr_norm", ""),
                record.get("en_norm", ""),
                record.get("ar_norm", ""),
            ],
        )
    )
    record["_tokens"] = tokenize_glossary_text(record["_search_blob"])
    record["_fr_quality"] = _latin_quality(record.get("fr", ""))
    record["_en_quality"] = _latin_quality(record.get("en", ""))
    return record


def _load_glossary_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(_prepare_record(json.loads(line)))
    return records


@lru_cache(maxsize=1)
def load_financial_glossary_hq() -> list[dict]:
    return _load_glossary_file(HQ_GLOSSARY_PATH)


@lru_cache(maxsize=1)
def load_financial_glossary() -> list[dict]:
    return _load_glossary_file(GLOSSARY_PATH)


def _search_records(records: list[dict], query: str, limit: int = 8) -> list[dict]:
    if not records:
        return []
    query_tokens = tokenize_glossary_text(query)
    if not query_tokens:
        return []
    query_norm = normalize_glossary_text(query)

    scored: list[tuple[float, dict]] = []
    latin_query_tokens = [token for token in query_tokens if re.fullmatch(r"[0-9a-z]{2,}", token)]
    for record in records:
        token_set = set(record["_tokens"])
        overlap = sum(1 for token in query_tokens if token in token_set)
        if not overlap:
            continue
        score = overlap * 4.0
        exactish = False
        field_token_matches = 0
        for field in ("fr_norm", "en_norm", "ar_norm"):
            value = record.get(field, "")
            if not value:
                continue
            if value in query_norm or query_norm in value:
                score += 18.0
                exactish = True
            if latin_query_tokens and all(token in value for token in latin_query_tokens):
                field_token_matches += 1
                score += 10.0
        if len(record.get("ar", "")) >= 3:
            score += 0.6
        quality = max(record.get("_fr_quality", 0.0), record.get("_en_quality", 0.0))
        if len(query_tokens) >= 2 and overlap < 2 and not exactish and field_token_matches == 0:
            continue
        if latin_query_tokens and not exactish and field_token_matches == 0:
            continue
        if exactish:
            if quality < 0.28:
                continue
        elif quality < 0.52:
            continue
        score *= 0.75 + quality
        scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for score, record in scored:
        key = (record.get("fr", ""), record.get("en", ""))
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "fr": record.get("fr", ""),
                "en": record.get("en", ""),
                "ar": record.get("ar", ""),
                "page": record.get("page"),
                "score": round(score, 3),
            }
        )
        if len(results) >= limit:
            break
    return results


def search_financial_glossary(query: str, limit: int = 8) -> list[dict]:
    hq_results = _search_records(load_financial_glossary_hq(), query, limit=limit)
    if hq_results:
        return hq_results[:limit]

    fallback_results = _search_records(load_financial_glossary(), query, limit=limit * 3)
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in [*hq_results, *fallback_results]:
        key = (row.get("fr", ""), row.get("en", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged
