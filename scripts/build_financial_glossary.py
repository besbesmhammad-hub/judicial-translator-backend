from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ocr_utils import ocr_pdf_page_text


DOWNLOADS = Path.home() / "Downloads"
OUT_PATH = ROOT / "app" / "data" / "financial_terms_trilingual.jsonl"
PDF_GLOB = "Henni - Dictionnaire des termes economiques et financiers_ *.pdf"


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    text = strip_accents((value or "").lower())
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"\s+", " ", text).strip(" _-")
    return text


def clean_column(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip(" _-")
    return value


def valid_latin_term(value: str) -> bool:
    if len(value) < 3:
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]", value):
        return False
    if value.lower().startswith(("www.", "page ", "preface", "librairie du liban")):
        return False
    return True


def valid_english_term(value: str) -> bool:
    if len(value) < 3:
        return False
    return bool(re.search(r"[A-Za-z]", value))


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


def parse_page_entries(text: str, page_num: int) -> list[dict]:
    entries: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 8:
            continue
        parts = [clean_column(part) for part in re.split(r"\s{2,}", line) if clean_column(part)]
        if len(parts) < 3:
            continue
        fr, en, ar = parts[0], parts[1], parts[2]
        if not valid_latin_term(fr) or not valid_english_term(en):
            continue
        if re.fullmatch(r"\d+", fr) or re.fullmatch(r"\d+", en):
            continue
        if len(fr) > 120 or len(en) > 140 or len(ar) > 140:
            continue
        entries.append(
            {
                "fr": fr,
                "en": en,
                "ar": ar,
                "fr_norm": normalize_text(fr),
                "en_norm": normalize_text(en),
                "ar_norm": normalize_text(ar),
                "fr_quality": round(latin_quality(fr), 4),
                "en_quality": round(latin_quality(en), 4),
                "page": page_num,
            }
        )
    return entries


def main() -> None:
    matches = sorted(DOWNLOADS.glob(PDF_GLOB))
    if not matches:
        raise SystemExit("Financial dictionary PDF not found in Downloads.")
    pdf_path = matches[0]
    doc = fitz.open(str(pdf_path))
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    start_page = 40
    end_page = max(start_page, doc.page_count - 5)
    for page_index in range(start_page, end_page):
        page = doc.load_page(page_index)
        text = ocr_pdf_page_text(page, scale=1.0)
        if len(re.findall(r"[A-Za-zÀ-ÿ]", text)) < 20:
            continue
        for entry in parse_page_entries(text, page_index + 1):
            key = (entry["fr_norm"], entry["en_norm"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(entry)
        if (page_index + 1) % 50 == 0:
            print(json.dumps({"progress_page": page_index + 1, "entries": len(rows)}, ensure_ascii=False), flush=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"pdf": pdf_path.name, "entries": len(rows), "output": str(OUT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
