from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


GOLDEN_KB_PATH = Path(__file__).with_name("data") / "golden_kb.jsonl"
STOPWORDS = {
    "avec", "aux", "ces", "dans", "des", "donne", "donner", "du", "elle", "elles", "est",
    "etre", "explique", "expliquez", "les", "leur", "leurs", "par", "pas", "pour", "que",
    "qui", "sur", "une", "vous", "what", "which", "the", "and", "for", "from", "that",
    "this", "def", "definition", "definition", "signifie", "cest", "quoi", "quelle",
    "quelles", "meaning", "means", "dire",
}

INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "document_analysis",
        re.compile(r"piece jointe|document ci-joint|document joint|dans ce document|analyse ce document|selon ce document|uploaded document|attached document", re.I),
    ),
    (
        "comparison",
        re.compile(r"\bdifference\b|\bdiff[ée]rence\b|\bcompar|versus|\bvs\b|par rapport a|par rapport à|oppose a|opposé à", re.I),
    ),
    (
        "tax_calculation",
        re.compile(r"calcul|calcule|comment calcul|base imposable|taux|bar[èe]me|liquider|montant de l[' ]impot|montant de l[' ]impôt|d[ée]termination de l[' ]impot", re.I),
    ),
    (
        "legal_basis",
        re.compile(r"quelle loi|quelle regle|quelle règle|base legale|base légale|quel article|quels articles|fondement juridique|texte applicable", re.I),
    ),
    (
        "accounting_treatment",
        re.compile(r"comment comptabil|traitement comptable|ecriture comptable|écriture comptable|passation|enregistrer comptablement|presentation dans les etats financiers|présentation dans les états financiers", re.I),
    ),
    (
        "audit",
        re.compile(r"\baudit\b|commissaire aux comptes|cac\b|isa\b|rapport d[' ]audit|rapport du commissaire", re.I),
    ),
    (
        "company_law",
        re.compile(r"sarl|sa\b|societe|société|registre du commerce|liquidation|dissolution|statuts|associe|associé", re.I),
    ),
    (
        "definition",
        re.compile(r"qu[' ]est ce que|c[' ]est quoi|defin|défin|signifie|veut dire|meaning|means|acronyme|abreviation|abr[eé]viation|equivalent|équivalent", re.I),
    ),
]


def tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zÀ-ÿ']{2,}|[\u0600-\u06FF]{2,}", (value or "").lower())
    return [token.strip("'") for token in tokens if token not in STOPWORDS]


def classify_query_intent(message: str, context: str = "") -> str:
    query = f"{message}\n{context}".strip()
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(query):
            return intent
    return "general"


@lru_cache(maxsize=1)
def load_golden_kb() -> list[dict]:
    if not GOLDEN_KB_PATH.exists():
        return []
    rows: list[dict] = []
    with GOLDEN_KB_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            search_blob = " ".join(
                [
                    row.get("concept", ""),
                    " ".join(row.get("aliases", [])),
                    row.get("canonical_definition", ""),
                    " ".join(row.get("related_concepts", [])),
                    row.get("domain", ""),
                ]
            )
            row["_tokens"] = tokenize(search_blob)
            rows.append(row)
    return rows


def golden_kb_status() -> dict:
    rows = load_golden_kb()
    return {
        "available": bool(rows),
        "entries": len(rows),
        "domains": sorted({row.get("domain", "") for row in rows if row.get("domain")}),
    }


def retrieve_golden_kb(query: str, limit: int = 3) -> list[dict]:
    kb = load_golden_kb()
    if not kb:
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    query_text = (query or "").lower()
    scored: list[tuple[float, dict]] = []
    exact_rows: list[tuple[float, dict]] = []
    for row in kb:
        token_set = set(row["_tokens"])
        overlap = sum(1 for token in query_tokens if token in token_set)
        if not overlap:
            continue
        score = overlap * 4.0
        concept = (row.get("concept") or "").lower()
        aliases = [alias.lower() for alias in row.get("aliases", [])]
        exact_match = False
        if concept and concept in query_text:
            score += 18.0
            exact_match = True
        if any(alias and alias in query_text for alias in aliases):
            score += 15.0
            exact_match = True
        if len(query_tokens) >= 2 and overlap < 2 and concept not in query_text:
            continue
        score += float(row.get("confidence_score", 0.7)) * 10.0
        payload = (score, row)
        scored.append(payload)
        if exact_match:
            exact_rows.append(payload)
    if exact_rows:
        scored = exact_rows
    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict] = []
    seen: set[str] = set()
    for score, row in scored:
        concept = row.get("concept", "")
        if concept in seen:
            continue
        seen.add(concept)
        results.append(
            {
                "concept": concept,
                "domain": row.get("domain"),
                "canonical_definition": row.get("canonical_definition"),
                "legal_basis": row.get("legal_basis", []),
                "source_refs": row.get("source_refs", []),
                "related_concepts": row.get("related_concepts", []),
                "common_mistakes": row.get("common_mistakes", []),
                "last_reviewed": row.get("last_reviewed"),
                "confidence_label": row.get("confidence_label", "high"),
                "confidence_score": row.get("confidence_score", 0.7),
                "score": round(score, 3),
            }
        )
        if len(results) >= limit:
            break
    return results
