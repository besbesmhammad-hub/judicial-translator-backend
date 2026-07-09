from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ocr_utils import choose_better_text, is_low_quality_text, normalize_text, ocr_pdf_page_text


CORPUS_PATH = ROOT / "app" / "data" / "tunisian_legal_corpus.jsonl"
DOWNLOADS = Path.home() / "Downloads"


DOCS = [
    {
        "filename": "compte-rendu-stagiaire-v2025.pdf",
        "doc_id": "formulaire_compte_rendu_stagiaire",
        "title": "Formulaire de compte rendu de stagiaire CCT",
        "authority": "Compagnie des Comptables de Tunisie",
        "source_tier": "form_template",
        "year": 2012,
        "domain": "stage_professionnel",
    },
    {
        "filename": "lettre-circulaire-stagiaires.pdf",
        "doc_id": "circulaire_stagiaires_2018",
        "title": "Lettre circulaire stagiaires 2018",
        "authority": "Compagnie des Comptables de Tunisie",
        "source_tier": "professional_circular",
        "year": 2018,
        "domain": "stage_professionnel",
    },
    {
        "filename": None,
        "doc_id": "textes_profession_comptable_2018",
        "title": "Textes relatifs aux comptables, experts-comptables et commissaires aux comptes",
        "authority": "Imprimerie Officielle de la Republique Tunisienne",
        "source_tier": "professional_text_collection",
        "year": 2018,
        "domain": "reglementation_professionnelle",
    },
    {
        "filename": "Rapport-moral-2023.pdf",
        "doc_id": "rapport_moral_2023",
        "title": "Rapport moral 2023",
        "authority": "Organisation professionnelle comptable tunisienne",
        "source_tier": "institutional_report",
        "year": 2023,
        "domain": "vie_professionnelle",
    },
    {
        "filename": "rapport-moral-2024.pdf",
        "doc_id": "rapport_moral_2024",
        "title": "Rapport moral 2024",
        "authority": "Organisation professionnelle comptable tunisienne",
        "source_tier": "institutional_report",
        "year": 2024,
        "domain": "vie_professionnelle",
    },
    {
        "filename": "rapport-moral-2025.pdf",
        "doc_id": "rapport_moral_2025",
        "title": "Rapport moral 2025",
        "authority": "Organisation professionnelle comptable tunisienne",
        "source_tier": "institutional_report",
        "year": 2025,
        "domain": "vie_professionnelle",
    },
]

DOC_ID_FILTER = {value.strip() for value in os.environ.get("DOC_IDS", "").split(",") if value.strip()}
MAX_PAGES_PER_DOC = int(os.environ.get("MAX_PAGES_PER_DOC", "0") or "0")


HEADING_RE = re.compile(
    r"^(article\s+\d+|art\.\s*\d+|chapitre\s+[ivxlcdm\d]+|section\s+\d+|titre\s+[ivxlcdm\d]+|annexe|appendice|partie\s+[ivxlcdm\d]+|i\.|ii\.|iii\.|iv\.|v\.|vi\.|vii\.|viii\.|ix\.|x\.|\d+\s*[\.)-])",
    re.I,
)


def resolve_filename(meta: dict) -> str:
    if meta["filename"]:
        return meta["filename"]
    for path in DOWNLOADS.iterdir():
        if path.suffix.lower() == ".pdf" and not path.name.isascii() and path.stat().st_size == 1_196_628:
            return path.name
    raise FileNotFoundError("Arabic professional text collection PDF not found.")


def pick_heading(paragraph: str) -> str:
    for raw_line in paragraph.splitlines()[:4]:
        line = raw_line.strip(" -:•\t")
        if not line:
            continue
        if len(line) <= 140 and (HEADING_RE.match(line) or line.isupper()):
            return line
    return ""


def chunk_text(text: str, limit: int = 1800) -> list[tuple[str, str]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[tuple[str, str]] = []
    current = ""
    current_heading = ""
    for paragraph in paragraphs:
        paragraph_heading = pick_heading(paragraph)
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if current and len(candidate) > limit:
            chunks.append((current_heading, current.strip()))
            current = paragraph
            current_heading = paragraph_heading or current_heading or ""
        else:
            current = candidate
            current_heading = current_heading or paragraph_heading or ""
        if len(current) > limit * 1.35:
            parts = [current[i:i + limit] for i in range(0, len(current), limit)]
            for part in parts[:-1]:
                chunks.append((current_heading, part.strip()))
            current = parts[-1].strip()
    if current.strip():
        chunks.append((current_heading, current.strip()))
    return chunks


def extract_page_text(page) -> str:
    blocks = page.get_text("blocks")
    embedded = normalize_text("\n".join(str(block[4]).strip() for block in blocks if len(block) > 4))
    if is_low_quality_text(embedded):
        try:
            return choose_better_text(embedded, ocr_pdf_page_text(page))
        except Exception:
            return embedded
    return embedded


def build_records(meta: dict) -> list[dict]:
    path = DOWNLOADS / resolve_filename(meta)
    doc = fitz.open(path)
    records: list[dict] = []
    page_count = min(doc.page_count, MAX_PAGES_PER_DOC) if MAX_PAGES_PER_DOC else doc.page_count
    for page_index in range(page_count):
        page_text = extract_page_text(doc.load_page(page_index))
        if not page_text:
            continue
        for local_index, (heading, chunk) in enumerate(chunk_text(page_text), start=1):
            digest = hashlib.blake2b(
                f"{meta['doc_id']}|{page_index + 1}|{local_index}|{chunk[:200]}".encode("utf-8"),
                digest_size=8,
            ).hexdigest()
            records.append({
                "id": digest,
                "doc_id": meta["doc_id"],
                "title": meta["title"],
                "filename": path.name,
                "page": page_index + 1,
                "heading": heading,
                "text": chunk,
                "authority": meta["authority"],
                "source_tier": meta["source_tier"],
                "year": meta["year"],
                "domain": meta["domain"],
            })
    return records


def main() -> None:
    selected_docs = [meta for meta in DOCS if not DOC_ID_FILTER or meta["doc_id"] in DOC_ID_FILTER]
    existing = []
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                existing.append(json.loads(line))

    target_ids = {meta["doc_id"] for meta in selected_docs}
    kept = [row for row in existing if row.get("doc_id") not in target_ids]
    rebuilt: list[dict] = []
    for meta in selected_docs:
        rebuilt.extend(build_records(meta))

    with CORPUS_PATH.open("w", encoding="utf-8") as handle:
        for row in kept + rebuilt:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(f"kept={len(kept)} rebuilt={len(rebuilt)} total={len(kept) + len(rebuilt)}")
    for doc_id in sorted(target_ids):
        print(doc_id, sum(1 for row in rebuilt if row["doc_id"] == doc_id))


if __name__ == "__main__":
    main()
