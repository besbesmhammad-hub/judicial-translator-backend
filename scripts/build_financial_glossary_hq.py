from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "app" / "data" / "financial_terms_trilingual.jsonl"
OUT_PATH = ROOT / "app" / "data" / "financial_terms_trilingual_hq.jsonl"

FR_KEYWORDS = {
    "abattement", "actif", "amort", "audit", "banque", "bilan", "budget", "caisse",
    "charge", "cloture", "commissaire", "compta", "comptable", "comptabil", "compte",
    "consolid", "cotisation", "creance", "credit", "debiteur", "deficit", "dette",
    "dividende", "douane", "encaisse", "enregistrement", "etat financier", "facture",
    "finance", "financier", "fiscal", "fiscalite", "fonds", "grand livre", "impot",
    "immobil", "inventaire", "irpp", "journal", "liasse", "liquidite", "matricule fiscal",
    "micro-credit", "note de debit", "opcvm", "paie", "passif", "penalite",
    "piece comptable", "provision", "recouvrement", "registre", "report", "reserve",
    "resultat", "retenue a la source", "revenu", "salaires", "solde", "stock",
    "subvention", "taxe", "timbre", "tresorer", "tva", "valeur ajoutee",
}

EN_KEYWORDS = {
    "account", "accounting", "accrual", "amort", "asset", "audit", "auditor", "balance",
    "bank", "budget", "cash", "charge", "consolid", "consumption tax", "cost", "credit",
    "customs", "debit", "debt", "deferred", "depreci", "dividend", "duty", "expense",
    "finance", "financial", "fiscal", "fund", "general ledger", "income", "input tax",
    "inventory", "invoice", "journal", "ledger", "liability", "loss", "output tax",
    "payable", "payroll", "penalty", "provision", "receivable", "reconciliation",
    "refund", "reserve", "retained earnings", "revenue", "salary", "social security",
    "source withholding", "statement", "stock", "surplus", "tax", "taxable",
    "treasury", "vat", "value added", "withholding",
}

STRONG_FR_KEYWORDS = {
    "actif", "amort", "audit", "banque", "bilan", "caisse", "charge", "comptable",
    "comptabil", "compte", "consolid", "creance", "credit", "dette", "douane",
    "enregistrement", "facture", "fiscal", "fiscalite", "impot", "immobil", "irpp",
    "journal", "liasse", "paie", "passif", "provision", "recouvrement", "resultat",
    "retenue a la source", "stock", "taxe", "timbre", "tresorer", "tva", "valeur ajoutee",
}

STRONG_EN_KEYWORDS = {
    "account", "accounting", "accrual", "asset", "audit", "bank", "balance", "cash",
    "credit", "customs", "debit", "debt", "depreci", "expense", "financial", "fiscal",
    "general ledger", "income", "input tax", "invoice", "ledger", "liability",
    "output tax", "payable", "payroll", "provision", "receivable", "reserve",
    "revenue", "tax", "taxable", "treasury", "vat", "value added", "withholding",
}

BLACKLIST_SUBSTRINGS = {
    "www", "librairie du liban", "preface", "index", "table des", "introduction",
}


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    text = strip_accents((value or "").lower())
    text = text.replace("â€™", "'").replace("`", "'").replace("‘", "'").replace("’", "'")
    text = re.sub(r"\s+", " ", text).strip(" _-")
    return text


def latin_quality(value: str) -> float:
    text = (value or "").strip()
    if not text:
        return 0.0
    letters = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
    weird = len(re.findall(r"[^A-Za-zÀ-ÿ0-9'()\-.,/& ]", text))
    vowels = len(re.findall(r"[AEIOUYaeiouyÀ-ÿ]", text))
    ratio = letters / max(len(text), 1)
    vowel_ratio = vowels / max(letters, 1)
    score = ratio * 0.6 + min(vowel_ratio, 0.55) * 0.8 - weird * 0.08
    return max(0.0, min(score, 1.0))


def has_keyword(value: str, keywords: set[str]) -> bool:
    norm = normalize_text(value)
    return any(keyword in norm for keyword in keywords)


def token_count(value: str) -> int:
    return len(re.findall(r"[a-z]{2,}", normalize_text(value)))


def looks_like_ocr_junk(value: str) -> bool:
    text = normalize_text(value)
    if len(text) < 4:
        return True
    if any(bad in text for bad in BLACKLIST_SUBSTRINGS):
        return True
    tokens = re.findall(r"[a-z]{2,}", text)
    if not tokens:
        return True
    if len(tokens) >= 2 and sum(len(token) <= 2 for token in tokens) >= len(tokens) - 1:
        return True
    if re.search(r"(.)\1\1", text):
        return True
    return False


def is_high_confidence_record(record: dict) -> bool:
    fr = record.get("fr", "")
    en = record.get("en", "")
    ar = record.get("ar", "")
    fr_norm = normalize_text(fr)
    en_norm = normalize_text(en)
    fr_quality = float(record.get("fr_quality") or latin_quality(fr))
    en_quality = float(record.get("en_quality") or latin_quality(en))

    if looks_like_ocr_junk(fr) or looks_like_ocr_junk(en):
        return False
    if len(fr_norm) > 90 or len(en_norm) > 100:
        return False
    if fr_quality < 0.64 or en_quality < 0.66:
        return False
    fr_has_keyword = has_keyword(fr, FR_KEYWORDS)
    en_has_keyword = has_keyword(en, EN_KEYWORDS)
    if not fr_has_keyword and not en_has_keyword:
        return False
    if not has_keyword(fr, STRONG_FR_KEYWORDS) and not has_keyword(en, STRONG_EN_KEYWORDS):
        return False
    if len(re.findall(r"[A-Za-zÀ-ÿ]", fr)) < 4 or len(re.findall(r"[A-Za-z]", en)) < 4:
        return False
    if ar and len(ar.strip()) <= 1:
        return False
    if token_count(fr) == 1 and token_count(en) == 1:
        if not has_keyword(fr, STRONG_FR_KEYWORDS) and not has_keyword(en, STRONG_EN_KEYWORDS):
            return False
    if token_count(fr) == 1 and fr_norm in {"valeur", "vente", "societe", "revenu", "fonds"}:
        return False
    if token_count(en) == 1 and en_norm in {"value", "sale", "company", "fund", "revenue", "tax"}:
        return False
    return True


def main() -> None:
    if not RAW_PATH.exists():
        raise SystemExit(f"Raw glossary not found: {RAW_PATH}")

    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    with RAW_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if not is_high_confidence_record(record):
                continue
            key = (normalize_text(record.get("fr", "")), normalize_text(record.get("en", "")))
            if key in seen:
                continue
            seen.add(key)
            record["fr_quality"] = round(float(record.get("fr_quality") or latin_quality(record.get("fr", ""))), 4)
            record["en_quality"] = round(float(record.get("en_quality") or latin_quality(record.get("en", ""))), 4)
            kept.append(record)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps({
        "raw_path": str(RAW_PATH),
        "output_path": str(OUT_PATH),
        "entries": len(kept),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
