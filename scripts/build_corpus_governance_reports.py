from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "app" / "data" / "tunisian_legal_corpus.jsonl"
REPORTS_DIR = ROOT / "reports"

CURRENT_DEFAULTS = {
    "code_irpp_is_2025",
    "tva_droit_consommation",
    "procedures_fiscales_2026",
    "enregistrement_timbre",
    "fiscalite_locale_2026",
    "loi_finances_2026",
    "loi_finances_2026_ar",
}

HISTORICAL_PREFIXES = (
    "code_irpp_is_",
    "tva_droit_consommation_",
    "procedures_fiscales_",
    "enregistrement_timbre_",
    "fiscalite_locale_",
    "droits_taxes_hors_codes_",
)


def load_records() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def detect_year(doc_id: str, title: str, filename: str) -> int | None:
    for value in (doc_id, title, filename):
        match = re.search(r"(20\d{2}|19\d{2})", value or "")
        if match:
            return int(match.group(1))
    return None


def detect_language(text: str) -> str:
    arabic = len(re.findall(r"[\u0600-\u06ff]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    if arabic and latin:
        return "mixed"
    if arabic:
        return "ar"
    if latin:
        return "fr"
    return "unknown"


def classify_quality(text: str) -> str:
    compact = (text or "").strip()
    if len(compact) < 80:
        return "unusable"
    bad = len(re.findall(r"[�]|Ã|Â|Ø|Ù|\?{3,}", compact))
    ratio = bad / max(len(compact), 1)
    if ratio > 0.015:
        return "garbled"
    return "clean"


def tags_for(doc_id: str, title: str) -> tuple[list[str], list[str]]:
    key = f"{doc_id} {title}".lower()
    topic_tags: set[str] = set()
    workflow_tags: set[str] = set()
    mapping = [
        ("irpp", "fiscalite_directe"),
        ("is", "fiscalite_directe"),
        ("tva", "tva"),
        ("procedures_fiscales", "procedure_fiscale"),
        ("enregistrement", "enregistrement_timbre"),
        ("timbre", "enregistrement_timbre"),
        ("fiscalite_locale", "fiscalite_locale"),
        ("loi_finances", "loi_finances"),
        ("investissement", "avantages_fiscaux"),
        ("avantages_fiscaux", "avantages_fiscaux"),
        ("convention_fiscale", "conventions_fiscales"),
        ("cnss", "paie_social"),
        ("audit", "audit_cac"),
        ("cac", "audit_cac"),
        ("nc_", "comptabilite"),
        ("ias_", "comptabilite_ifrs"),
        ("ifrs_", "comptabilite_ifrs"),
        ("societes", "droit_societes"),
        ("comptable", "comptabilite"),
    ]
    for needle, tag in mapping:
        if needle in key:
            topic_tags.add(tag)
            workflow_tags.add(tag)
    if not topic_tags:
        topic_tags.add("general")
    if not workflow_tags:
        workflow_tags.add("general")
    return sorted(topic_tags), sorted(workflow_tags)


def source_status(doc_id: str) -> str:
    if doc_id in CURRENT_DEFAULTS:
        return "active/default"
    if doc_id == "code_irpp_is_2011":
        return "historical-only"
    if doc_id.startswith(HISTORICAL_PREFIXES) and doc_id not in CURRENT_DEFAULTS:
        return "historical-only"
    return "active/targeted"


def duplicate_relation(doc_id: str) -> str:
    groups = {
        "code_irpp_is": ["code_irpp_is_2011", "code_irpp_is_2019", "code_irpp_is_2020", "code_irpp_is_2021", "code_irpp_is_2022", "code_irpp_is_2023", "code_irpp_is_2025"],
        "tva_droit_consommation": ["tva_droit_consommation", "tva_droit_consommation_2019", "tva_droit_consommation_2021", "tva_droit_consommation_2023", "tva_droit_consommation_2025"],
        "procedures_fiscales": ["procedures_fiscales_2023", "procedures_fiscales_2024", "procedures_fiscales_2025", "procedures_fiscales_2026"],
        "enregistrement_timbre": ["enregistrement_timbre", "enregistrement_timbre_2018", "enregistrement_timbre_2020", "enregistrement_timbre_2022", "enregistrement_timbre_2025"],
        "fiscalite_locale": ["fiscalite_locale", "fiscalite_locale_2018", "fiscalite_locale_2020", "fiscalite_locale_2023", "fiscalite_locale_2025", "fiscalite_locale_2026"],
    }
    for family, members in groups.items():
        if doc_id in members:
            return family
    return ""


def priority_for(doc_id: str) -> int:
    if doc_id in CURRENT_DEFAULTS:
        return 100
    if source_status(doc_id) == "active/targeted":
        return 70
    return 40


def build_manifest(records: list[dict]) -> list[dict]:
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_doc[record.get("doc_id") or "unknown"].append(record)

    manifest: list[dict] = []
    for doc_id, items in sorted(by_doc.items()):
        first = items[0]
        text_sample = "\n".join(str(item.get("text") or "")[:1500] for item in items[:5])
        title = first.get("title") or doc_id
        filename = first.get("filename") or ""
        topic_tags, workflow_tags = tags_for(doc_id, title)
        manifest.append({
            "document_id": doc_id,
            "title": title,
            "year_version": detect_year(doc_id, title, filename),
            "language": detect_language(f"{title}\n{filename}\n{text_sample}"),
            "source_filename": filename,
            "source_url": first.get("source_url") or None,
            "status": source_status(doc_id),
            "duplicate_near_duplicate_relation": duplicate_relation(doc_id),
            "topic_tags": topic_tags,
            "workflow_tags": workflow_tags,
            "preferred_source_priority": priority_for(doc_id),
            "chunk_count": len(items),
            "page_count_indexed": len({item.get("page") for item in items if item.get("page") is not None}),
        })
    return manifest


def build_arabic_quality(records: list[dict]) -> list[dict]:
    pages: dict[tuple[str, int], list[str]] = defaultdict(list)
    meta: dict[str, dict] = {}
    for record in records:
        doc_id = record.get("doc_id") or "unknown"
        meta.setdefault(doc_id, record)
        key = (doc_id, int(record.get("page") or 0))
        pages[key].append(record.get("text") or "")

    by_doc: dict[str, dict] = {}
    for (doc_id, page), text_parts in pages.items():
        record = meta[doc_id]
        joined = "\n".join(text_parts)
        lang = detect_language(f"{record.get('title','')}\n{record.get('filename','')}\n{joined[:2000]}")
        if lang not in {"ar", "mixed"}:
            continue
        quality = classify_quality(joined)
        doc = by_doc.setdefault(doc_id, {
            "document_id": doc_id,
            "title": record.get("title") or doc_id,
            "source_filename": record.get("filename") or "",
            "clean_pages": [],
            "garbled_pages": [],
            "unusable_pages": [],
            "direct_passage_safe_pages": [],
            "framework_source_only_pages": [],
        })
        if quality == "clean":
            doc["clean_pages"].append(page)
            doc["direct_passage_safe_pages"].append(page)
        elif quality == "garbled":
            doc["garbled_pages"].append(page)
            doc["framework_source_only_pages"].append(page)
        else:
            doc["unusable_pages"].append(page)
            doc["framework_source_only_pages"].append(page)
    return list(by_doc.values())


def write_outputs(manifest: list[dict], arabic_quality: list[dict]) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "corpus_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with (REPORTS_DIR / "corpus_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        for row in manifest:
            writer.writerow({**row, "topic_tags": ";".join(row["topic_tags"]), "workflow_tags": ";".join(row["workflow_tags"])})
    (REPORTS_DIR / "source_quality_arabic.json").write_text(json.dumps(arabic_quality, ensure_ascii=False, indent=2), encoding="utf-8")

    active = [row for row in manifest if row["status"] == "active/default"]
    historical = [row for row in manifest if row["status"] == "historical-only"]
    md = [
        "# Corpus Manifest Summary",
        "",
        f"- Indexed documents: {len(manifest)}",
        f"- Active/default sources: {len(active)}",
        f"- Historical-only sources: {len(historical)}",
        "",
        "## Active Defaults",
        *[f"- `{row['document_id']}` ({row['year_version']}): {row['title']}" for row in active],
        "",
        "## Governance Notes",
        "- Current cabinet questions use the latest consolidated/default source available.",
        "- Historical editions remain indexed, but should be selected only when the user asks for a specific edition/year or when historical law is legally required.",
        "- Arabic-heavy pages marked garbled or unusable should not be treated as direct passage support.",
    ]
    (REPORTS_DIR / "corpus_manifest.md").write_text("\n".join(md), encoding="utf-8")

    quality_md = ["# Arabic Source Quality Report", ""]
    for row in arabic_quality:
        quality_md.append(f"## {row['document_id']}")
        quality_md.append(f"- Title: {row['title']}")
        quality_md.append(f"- Clean pages: {len(row['clean_pages'])}")
        quality_md.append(f"- Garbled pages: {len(row['garbled_pages'])}")
        quality_md.append(f"- Unusable pages: {len(row['unusable_pages'])}")
        quality_md.append(f"- Direct-passage safe pages: {len(row['direct_passage_safe_pages'])}")
        quality_md.append(f"- Framework-source only pages: {len(row['framework_source_only_pages'])}")
        quality_md.append("")
    (REPORTS_DIR / "source_quality_arabic.md").write_text("\n".join(quality_md), encoding="utf-8")

    impact_md = [
        "# New Corpus Impact Report",
        "",
        "- `code_irpp_is_2025`: current/default IRPP/IS source for cabinet questions; replaces `code_irpp_is_2011` as default while keeping 2011 historical-only.",
        "- `loi_finances_2026_ar`: improves Arabic finance-law routing from missing or irrelevant source toward direct/framework source support.",
        "- CDPF, TVA, enregistrement/timbre, fiscalite locale yearly editions: enable explicit source-year routing instead of accidental year matching from transaction facts.",
        "- Declaration forms and LICOBA schema: targeted form/document workflow support; not general legal authority unless the query concerns that form.",
        "",
        "Detailed source movement must be confirmed by `scripts/run_corpus_governance_checks.py` and the Level 1/2/2.5/3/3.5 benchmarks.",
    ]
    (REPORTS_DIR / "new_corpus_impact_report.md").write_text("\n".join(impact_md), encoding="utf-8")


def main() -> None:
    records = load_records()
    manifest = build_manifest(records)
    arabic_quality = build_arabic_quality(records)
    write_outputs(manifest, arabic_quality)
    print(json.dumps({
        "documents": len(manifest),
        "active_default": sum(1 for row in manifest if row["status"] == "active/default"),
        "historical_only": sum(1 for row in manifest if row["status"] == "historical-only"),
        "arabic_quality_docs": len(arabic_quality),
        "reports_dir": str(REPORTS_DIR),
    }, indent=2))


if __name__ == "__main__":
    main()
