from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


GOLDEN_KB_PATH = Path(__file__).with_name("data") / "golden_kb.jsonl"
STOPWORDS = {
    "avec", "aux", "ces", "dans", "de", "des", "donne", "donner", "du", "elle", "elles",
    "en", "est", "etre", "explique", "expliquez", "la", "le", "les", "leur", "leurs",
    "par", "pas", "pour", "que", "qui", "sur", "une", "vous", "what", "which", "the",
    "and", "for", "from", "that", "this", "def", "definition", "signifie", "cest",
    "quoi", "quelle", "quelles", "meaning", "means", "dire",
}


def match_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()

DEFINITION_PATTERN = re.compile(
    r"qu[' ]est ce que|qu[' ]est ce qu[' ]un|qu[' ]est ce qu[' ]une|c[' ]est quoi|defin|d[ée]fin|"
    r"signifie|veut dire|meaning|means|acronyme|abreviation|abr[ée]viation|equivalent|[ée]quivalent|"
    r"explique|pr[ée]sentation de|presentation de",
    re.I,
)

PROFESSIONAL_FORMALITY_PATTERN = re.compile(
    r"inscription|attestation d[' ]inscription|radiation|suspension|stagiaire|ordre professionnel|"
    r"compte rendu de stagiaire|demande d[' ]inscription|s inscrire a l ordre|inscrire a l ordre",
    re.I,
)

INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "legal_hierarchy",
        re.compile(
            r"hierarchie des normes|hi[ée]rarchie des normes|hierarchie juridique|hi[ée]rarchie juridique|"
            r"ordre des normes|valeur juridique des normes|rang des normes",
            re.I,
        ),
    ),
    (
        "document_analysis",
        re.compile(
            r"piece jointe|document ci-joint|document joint|dans ce document|analyse ce document|selon ce document|"
            r"uploaded document|attached document|analyse ce dossier|analyse ce cas|analyse d[' ]audit|"
            r"premiere analyse|controle interne|contr[ôo]le interne|risques comptables|risques fiscaux|"
            r"risques techniques|risques de preuve|dossier paie incomplet|bulletins de paie|avantages en nature|"
            r"regulariser ses dettes fiscales|remise de penalites|remise de p[ée]nalit[ée]s",
            re.I,
        ),
    ),
    (
        "comparison",
        re.compile(
            r"\bdifference\b|\bdiff[ée]rence\b|\bcompar|versus|\bvs\b|par rapport a|par rapport à|"
            r"oppose a|opposé à",
            re.I,
        ),
    ),
    (
        "tax_calculation",
        re.compile(
            r"\bcalcul\b|\bcalcule\b|comment calcul|base imposable|\btaux\b|\bbar[èe]me\b|\bliquider\b|"
            r"montant de l[' ]impot|montant de l[' ]impôt|d[ée]termination de l[' ]impot|"
            r"dividendes?.*retenues? a la source|retenues? a la source.*dividendes?|"
            r"credit de tva|cr[ée]dit de tva|restitution|demarches|d[ée]marches|"
            r"points de controle|points de contr[ôo]le|d[ée]ductible|d[ée]ductibilit[ée]|deductibilite|deductibile",
            re.I,
        ),
    ),
    (
        "legal_basis",
        re.compile(
            r"quelle loi|quelle regle|quelle règle|base legale|base légale|quel article|quels articles|"
            r"fondement juridique|texte applicable|quels textes|quel texte|regime tva|r[ée]gime tva|"
            r"bases? legales?|bases? légales?|cons[eé]quences? fiscales?|que prevoit la reglementation|"
            r"que prévoit la réglementation|apres l emission de son rapport|après l émission de son rapport|"
            r"apres emission de son rapport|après émission de son rapport|"
            r"obligations de facturation [ée]lectronique|facturation [ée]lectronique|parite d[' ]echange|"
            r"parit[ée] d[' ][ée]change|evaluation des actifs et passifs|[ée]valuation des actifs et passifs|"
            r"prestataire non resident|prestataire non r[ée]sident|textes fiscaux|"
            r"prestations? de services.*client etabli en france|prestations? de services.*client établi en france|"
            r"prestation informatique.*client francais|prestation informatique.*client français|"
            r"client non assujetti|non assujetti a la tva|non assujetti à la tva",
            re.I,
        ),
    ),
    (
        "accounting_treatment",
        re.compile(
            r"comment comptabil|traitement comptable|ecriture comptable|écriture comptable|passation|"
            r"enregistrer comptablement|presentation dans les etats financiers|présentation dans les états financiers|"
            r"traiter une provision|provision pour clients douteux|subvention d[' ]investissement|goodwill|"
            r"amortissement|amortir un goodwill|credit[ -]bail|cr[ée]dit[ -]bail|reconnaissance du revenu|ifrs ?15|ifrs ?16|"
            r"contrat de location|avant comptabilisation|avant cloture|avant cl[ôo]ture",
            re.I,
        ),
    ),
    (
        "company_law",
        re.compile(r"sarl|sa\b|societe|société|registre du commerce|liquidation|dissolution|statuts|associe|associé", re.I),
    ),
    (
        "audit",
        re.compile(r"\baudit\b|commissaire aux comptes|cac\b|isa\b|rapport d[' ]audit|rapport du commissaire", re.I),
    ),
    (
        "professional_formality",
        re.compile(
            r"inscription|attestation d[' ]inscription|radiation|suspension|stagiaire|ordre professionnel|"
            r"compte rendu de stagiaire|demande d[' ]inscription",
            re.I,
        ),
    ),
    (
        "definition",
        re.compile(
            r"qu[' ]est ce que|qu[' ]est ce qu[' ]un|qu[' ]est ce qu[' ]une|c[' ]est quoi|defin|d[ée]fin|"
            r"signifie|veut dire|meaning|means|acronyme|abreviation|abr[ée]viation|equivalent|[ée]quivalent|"
            r"explique|pr[ée]sentation de|presentation de",
            re.I,
        ),
    ),
]


def tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zÀ-ÿ']{2,}|[\u0600-\u06FF]{2,}", (value or "").lower())
    return [token.strip("'") for token in tokens if token not in STOPWORDS]


def normalize_lookup_text(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^0-9a-zà-ÿ\u0600-\u06ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_exact_phrase(haystack: str, needle: str) -> bool:
    hay = f" {normalize_lookup_text(haystack)} "
    ned = normalize_lookup_text(needle)
    if not ned:
        return False
    return f" {ned} " in hay


def classify_query_intent(message: str, context: str = "") -> str:
    query = match_key(f"{message}\n{context}".strip())
    accounting_pattern = next(pattern for intent, pattern in INTENT_PATTERNS if intent == "accounting_treatment")
    legal_pattern = next(pattern for intent, pattern in INTENT_PATTERNS if intent == "legal_basis")
    if re.search(r"dividendes?|associe non resident|associe resident|retenue a la source", query, re.I):
        return "tax_calculation" if re.search(r"retenue a la source|points fiscaux|consequences fiscales|bases? legales?", query, re.I) else "legal_basis"
    if accounting_pattern.search(query) and legal_pattern.search(query):
        return "accounting_treatment"
    priority_intents = {
        "legal_hierarchy",
        "document_analysis",
        "comparison",
        "tax_calculation",
        "accounting_treatment",
        "legal_basis",
        "company_law",
        "audit",
    }
    for intent, pattern in INTENT_PATTERNS:
        if intent in priority_intents and pattern.search(query):
            return intent
    if PROFESSIONAL_FORMALITY_PATTERN.search(query):
        return "professional_formality"
    if DEFINITION_PATTERN.search(query) and not re.search(
        r"dividendes?|credit de tva|cr[ée]dit de tva|restitution|regime tva|r[ée]gime tva|"
        r"facturation [ée]lectronique|goodwill|ifrs ?15|ifrs ?16|contrat de location",
        query,
        re.I,
    ):
        return "definition"
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

    scored: list[tuple[float, dict]] = []
    exact_rows: list[tuple[float, dict]] = []
    for row in kb:
        token_set = set(row["_tokens"])
        overlap = sum(1 for token in query_tokens if token in token_set)
        if not overlap:
            continue

        score = overlap * 4.0
        concept = row.get("concept") or ""
        aliases = row.get("aliases", [])
        exact_match = False

        if concept and contains_exact_phrase(query, concept):
            score += 18.0
            exact_match = True
        if any(alias and contains_exact_phrase(query, alias) for alias in aliases):
            score += 15.0
            exact_match = True
        if len(query_tokens) >= 2 and overlap < 2 and not contains_exact_phrase(query, concept):
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
