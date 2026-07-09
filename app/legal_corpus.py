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

    query_text = query.lower()
    domain_boosts = {
        "tva_droit_consommation": r"\btva\b|taxe sur la valeur ajout|valeur ajoutee|valeur ajoutée|droit de consommation|assujetti|deduction|déduction|exoner|exonér",
        "enregistrement_timbre": r"enregistrement|timbre|mutation|acte|donation|succession|bail|vente immobili",
        "fiscalite_locale": r"fiscalite locale|fiscalité locale|taxe sur les immeubles|tcl|collectivite|collectivité|commune|municipal",
        "loi_comptable": r"loi comptable|systeme comptable|système comptable|normes comptables|etats financiers|états financiers",
        "cadre_conceptuel_comptable": r"cadre conceptuel|qualitative|hypothese sous-jacente|hypothèse sous-jacente|information financiere|information financière",
        "droits_taxes_hors_codes": r"taxes non incorporees|taxes non incorporées|circulation|voyage|assurance|telecommunication|télécommunication|hotel|hôtel",
        "nc_01_norme_generale": r"\bnc 01\b|norme comptable generale|norme comptable générale|presentation des etats financiers|présentation des états financiers|organisation comptable",
        "nc_02_capitaux_propres": r"\bnc 02\b|capitaux propres|reserve|réserve|dividende|resultat reporte|résultat reporté",
        "nc_03_revenus": r"\bnc 03\b|revenus|produits|prestations de services|vente de biens|interets|intérêts|redevances",
        "nc_04_stocks": r"\bnc 04\b|stocks|cout d'acquisition|coût d'acquisition|cout de production|coût de production|depreciation des stocks|dépréciation des stocks",
        "nc_05_immobilisations_corporelles": r"\bnc 05\b|immobilisations corporelles|amortissement|valeur residuelle|valeur résiduelle|depreciation|dépréciation",
        "nc_06_immobilisations_incorporelles": r"\bnc 06\b|immobilisations incorporelles|actifs incorporels|logiciel|fonds commercial|recherche et developpement|recherche et développement",
    }

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
        pattern = domain_boosts.get(record.get("doc_id", ""))
        if pattern and re.search(pattern, query_text, re.I):
            score *= 2.8
        if record.get("heading") and re.search(r"article|art\.|chapitre|section|titre", record["heading"], re.I):
            score *= 1.1
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
