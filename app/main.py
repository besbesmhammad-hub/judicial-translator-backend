from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import config
from .financial_glossary import search_financial_glossary
from .golden_kb import classify_query_intent, golden_kb_status, retrieve_golden_kb
from .legal_corpus import corpus_status, infer_query_domain, load_corpus, retrieve_legal_context
from .native_documents import translate_docx_native, translate_pdf_visual_native, translate_pptx_native, translate_xlsx_native
from .parser import detect_file_format, parse_document
from .renderer import render_document
from .schemas import AccountingChatRequest, AnalyzeResponse, TranslateRequest, TranslateResponse
from .skills import ACTIVE_SKILLS, detect_document_kind
from .translator import (
    ProviderCreditError,
    ProviderRateLimitError,
    extract_json,
    friendly_provider_error,
    is_credit_error,
    is_rate_limit_error,
    prioritized_translation_routes,
    provider_body,
    provider_content,
    provider_timeout,
    clean_translation_output,
    translate_text,
)
import asyncio
import ast
import io
import json
import os
import re
import shutil
import time
import unicodedata
import urllib.request
import uuid
from pathlib import Path

import httpx


SEGMENT_PATTERN = re.compile(r"\[\[\[JT_SEG_(\d{4})\]\]\]([\s\S]*?)(?:\[\[\[/JT_SEG_\1\]\]\]|$)")
SEGMENT_OPEN_RE = re.compile(r"\[\[\[JT_SEG_\d{4}\]\]\]")
SEGMENT_CLOSE_RE = re.compile(r"\[\[\[/JT_SEG_\d{4}\]\]\]")
SEGMENT_ANY_RE = re.compile(r"\[\[\[/?JT_SEG_\d{4}\]\]\]")
# Loose variant: catches malformed markers with 2-3 brackets, whitespace inside,
# or partial markers that LLMs sometimes emit (e.g. "[[/JT_SEG_0000]]").
SEGMENT_LOOSE_RE = re.compile(r"\[{2,3}\s*/?\s*JT_SEG_\d{4}\s*\]{2,3}")
SECTION_SPLIT_RE = re.compile(
    r"\*\*(Assumptions|Next steps|Warnings)\*\*\s*:\s*",
    re.I,
)
CONCEPT_BRIEF_SECTIONS = ["Definition", "Base legale", "Points de vigilance", "Sources utilisees"]
PRACTICAL_ANALYSIS_SECTIONS = ["Reponse", "Application pratique", "Points de vigilance", "Sources utilisees"]


def match_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


CLIENT_SOURCE_TITLES = {
    "code_irpp_is_2011": "Code de l'impôt sur le revenu des personnes physiques et de l'impôt sur les sociétés (IRPP et IS)",
    "tva_droit_consommation": "Code de la taxe sur la valeur ajoutée (loi n° 88-61 du 2 juin 1988), recueil officiel mis à jour au 1er janvier 2026",
    "procedures_fiscales_2026": "Code des droits et procédures fiscaux, édition 2026",
    "enregistrement_timbre": "Code des droits d'enregistrement et de timbre, édition 2026",
    "fiscalite_locale": "Code de la fiscalité locale",
    "loi_finances_2026": "Loi de finances pour 2026",
}
CLIENT_SOURCE_TITLE_ALIASES = {
    "Code de l IRPP et de l IS": CLIENT_SOURCE_TITLES["code_irpp_is_2011"],
    "Code TVA et droit de consommation 2026": CLIENT_SOURCE_TITLES["tva_droit_consommation"],
    "Code des droits et procedures fiscaux 2026": CLIENT_SOURCE_TITLES["procedures_fiscales_2026"],
    "Code des droits d enregistrement et du timbre 2026": CLIENT_SOURCE_TITLES["enregistrement_timbre"],
    "Code de la fiscalite locale 2017": CLIENT_SOURCE_TITLES["fiscalite_locale"],
    "Loi de finances 2026": CLIENT_SOURCE_TITLES["loi_finances_2026"],
}
CANONICAL_FISCAL_SOURCE_METADATA = {
    "code_irpp_is_2011": {
        "title": "Code de l IRPP et de l IS",
        "filename": "11-97.pdf",
        "page": 1,
        "authority": "Imprimerie Officielle de la Republique Tunisienne",
        "year": 2011,
    },
    "tva_droit_consommation": {
        "title": "Code TVA et droit de consommation 2026",
        "filename": "Code-TVA-2026.pdf",
        "page": 2,
        "authority": "Ministere des Finances / legislation fiscale tunisienne",
        "year": 2026,
    },
    "procedures_fiscales_2026": {
        "title": "Code des droits et procedures fiscaux 2026",
        "filename": "مجلة-الحقوق-والإجراءات-الجبائية-2026.pdf",
        "page": 1,
        "authority": "Ministere des Finances / legislation fiscale tunisienne",
        "year": 2026,
    },
    "enregistrement_timbre": {
        "title": "Code des droits d enregistrement et du timbre 2026",
        "filename": "مجلة-معاليم-التسجيل-والطابع-الجبائي-2026-1.pdf",
        "page": 1,
        "authority": "Ministere des Finances / legislation fiscale tunisienne",
        "year": 2026,
    },
    "fiscalite_locale": {
        "title": "Code de la fiscalite locale 2017",
        "filename": "CODE DE LA FISCALITE LOCALE, TEXTES D'APPLICATIONS ET TEXTES CONNEXES 2017 FR.pdf",
        "page": 1,
        "authority": "Ministere des Finances",
        "year": 2017,
    },
    "loi_finances_2026": {
        "title": "Loi de finances 2026",
        "filename": "115725.pdf",
        "page": 1,
        "authority": "Journal Officiel de la Republique Tunisienne",
        "year": 2026,
    },
}
JOB_DIR = Path(os.getenv("TRANSLATION_JOB_DIR", "/tmp/judicial_translator_jobs"))
JOB_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNTING_CHAT_LOG_PATH = Path(config.ACCOUNTING_CHAT_LOG_PATH)
ACCOUNTING_CHAT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
SPACE_REVISION_CACHE: dict[str, str | float | None] = {"value": None, "ts": 0.0}

app = FastAPI(title="Judicial Translator Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_segmented_translation(value: str, count: int) -> list[str] | None:
    matches = SEGMENT_PATTERN.findall(value or "")
    if len(matches) != count:
        return None
    ordered = [""] * count
    for raw_index, text in matches:
        index = int(raw_index)
        if index >= count:
            return None
        ordered[index] = text.strip()
    return ordered


def split_by_segment_markers(value: str, count: int) -> list[str] | None:
    """Positional fallback: split the model output on any JT_SEG marker and keep
    the chunks in order. Works when the model preserved the segment count and
    ordering but dropped/renumbered/corrupted the exact index digits."""
    text = value or ""
    parts = SEGMENT_ANY_RE.split(text)
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if len(cleaned) != count:
        return None
    return cleaned


def build_segment_payload(segments: list[str]) -> str:
    parts = []
    for index, text in enumerate(segments):
        marker = f"{index:04d}"
        parts.append(f"[[[JT_SEG_{marker}]]]\n{text}\n[[[/JT_SEG_{marker}]]]")
    return "\n\n".join(parts)


def segment_batches(segments: list[str], max_chars: int = 9000) -> list[list[tuple[int, str]]]:
    batches: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    current_chars = 0
    for index, text in enumerate(segments):
        projected = current_chars + len(text) + 80
        if current and projected > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append((index, text))
        current_chars += len(text) + 80
    if current:
        batches.append(current)
    return batches


def provider_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProviderRateLimitError):
        return HTTPException(status_code=429, detail=str(error))
    if isinstance(error, ProviderCreditError):
        return HTTPException(status_code=402, detail=str(error))
    return HTTPException(status_code=502, detail=friendly_provider_error(error))


def split_list_block(value: str) -> list[str]:
    items: list[str] = []
    for line in (value or "").splitlines():
        line = clean_translation_output(line).strip()
        if not line:
            continue
        line = re.sub(r"^\d+\.\s*", "", line)
        line = re.sub(r"^[-*]\s*", "", line)
        if line:
            items.append(line)
    return items


def parse_section_mapping(value: str) -> dict[str, str]:
    text = clean_translation_output(value).strip()
    if not text or not text.startswith("{"):
        return {}
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None
    if not isinstance(parsed, dict):
        return {}
    return {
        clean_translation_output(str(key)).strip(): clean_translation_output(str(val)).strip()
        for key, val in parsed.items()
        if str(val).strip()
    }


def section_aliases(style: str) -> dict[str, list[str]]:
    if style == "concept_brief":
        return {
            "Definition": ["definition", "définition"],
            "Base legale": ["base legale", "base légale", "fondement juridique", "base juridique"],
            "Points de vigilance": ["points de vigilance", "vigilance", "attention", "points d attention", "points d'attention"],
            "Sources utilisees": ["sources utilisees", "sources utilisées", "sources", "references", "références"],
        }
    if style == "practical_analysis":
        return {
            "Reponse": ["reponse", "réponse", "analyse", "conclusion"],
            "Application pratique": ["application pratique", "application", "mise en pratique", "traitement pratique"],
            "Points de vigilance": ["points de vigilance", "vigilance", "attention", "points d attention", "points d'attention"],
            "Sources utilisees": ["sources utilisees", "sources utilisées", "sources", "references", "références"],
        }
    return {}


def normalized_heading_answer(answer: str, style: str) -> str:
    text = clean_translation_output(answer).strip()
    if not text:
        return text
    aliases = section_aliases(style)
    for canonical, variants in aliases.items():
        pattern = r"(?im)^(?:#+\s*|\*\*)?(?:" + "|".join(re.escape(item) for item in variants) + r")(?:\*\*)?\s*:?\s*$"
        text = re.sub(pattern, f"## {canonical}", text)
    return text


def answer_has_required_sections(answer: str, style: str) -> bool:
    if style == "concept_brief":
        sections = CONCEPT_BRIEF_SECTIONS
    elif style == "practical_analysis":
        sections = PRACTICAL_ANALYSIS_SECTIONS
    else:
        return True
    return all(f"## {section}" in answer for section in sections)


def compose_structured_answer(style: str, section_values: dict[str, str]) -> str:
    sections = CONCEPT_BRIEF_SECTIONS if style == "concept_brief" else PRACTICAL_ANALYSIS_SECTIONS
    blocks: list[str] = []
    for section in sections:
        value = clean_translation_output(section_values.get(section, "")).strip()
        if value:
            blocks.append(f"## {section}\n{value}")
    return "\n\n".join(blocks).strip()


def build_structured_sections_from_answer(
    answer: str,
    style: str,
    golden_kb_hits: list[dict],
    legal_sources: list[dict],
) -> str:
    raw = clean_translation_output(answer).strip()
    top = golden_kb_hits[0] if golden_kb_hits else None
    first_paragraph = re.split(r"\n\s*\n", raw, maxsplit=1)[0].strip() if raw else ""
    if style == "concept_brief":
        definition = first_paragraph or (top.get("canonical_definition") if top else "")
        base_legale = ", ".join(top.get("legal_basis", [])) if top else ""
        if not base_legale and legal_sources:
            base_legale = "\n".join(
                f"- {source.get('title', 'Source interne')}, page {source.get('page')}"
                for source in legal_sources[:3]
            )
        points = "\n".join(f"- {item}" for item in (top.get("common_mistakes", []) if top else [])[:3])
        if not points:
            points = "- Verifier le texte exact applicable et la version en vigueur avant usage client."
        sources_used = summarize_source_titles(
            [{"title": ref.get("title"), "page": None, "heading": ""} for ref in top.get("source_refs", [])] if top else legal_sources
        )
        return compose_structured_answer(
            "concept_brief",
            {
                "Definition": definition or "La notion doit être rattachée aux textes applicables et au contexte précis du dossier.",
                "Base legale": base_legale or "Base légale à préciser selon le dossier.",
                "Points de vigilance": points,
                "Sources utilisees": sources_used or "- Référence à préciser selon le texte applicable",
            },
        )
    if style == "practical_analysis":
        response = first_paragraph or "Les sources internes permettent de formuler une premiere orientation pratique."
        application = "- Reconstituer les faits, montants et periodes.\n- Identifier le texte precis applicable.\n- Verifier les seuils, exceptions et pieces justificatives."
        points = "- Verifier la date du texte, les lois de finances ulterieures et les circonstances du client."
        sources_used = summarize_source_titles(legal_sources) or summarize_source_titles(
            [{"title": ref.get("title"), "page": None, "heading": ""} for hit in golden_kb_hits for ref in hit.get("source_refs", [])]
        )
        return compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": response,
                "Application pratique": application,
                "Points de vigilance": points,
                "Sources utilisees": sources_used or "- Référence à préciser selon le texte applicable",
            },
        )
    return raw


def ensure_answer_sections(answer: str, style: str) -> str:
    text = normalized_heading_answer(answer, style)
    if style not in {"concept_brief", "practical_analysis"}:
        return text
    if answer_has_required_sections(text, style):
        return text

    mapping = parse_section_mapping(text)
    if not mapping:
        return text

    aliases = section_aliases(style)
    section_values: dict[str, str] = {}
    for canonical, variants in aliases.items():
        for key, value in mapping.items():
            normalized_key = key.strip().lower()
            if normalized_key == canonical.lower() or normalized_key in variants:
                section_values[canonical] = value
                break
    rebuilt = compose_structured_answer(style, section_values)
    return rebuilt or text


def client_source_title(source: dict) -> str:
    doc_id = source.get("doc_id")
    if doc_id in CLIENT_SOURCE_TITLES:
        return CLIENT_SOURCE_TITLES[doc_id]
    title = source.get("title") or "Source interne"
    return CLIENT_SOURCE_TITLE_ALIASES.get(title, title)


def summarize_source_titles(sources: list[dict], limit: int = 3) -> str:
    lines: list[str] = []
    for source in sources[:limit]:
        title = client_source_title(source)
        page = source.get("page")
        heading = "" if source.get("score") == 999.0 else (source.get("heading") or "")
        suffix = f", page {page}" if page is not None else ""
        if heading:
            suffix += f" - {heading}"
        lines.append(f"- {title}{suffix}")
    return "\n".join(lines)


def legal_source_limit(intent: str, prefer_golden_kb: bool) -> int:
    if prefer_golden_kb:
        return 2
    if intent == "legal_basis":
        return 3
    if intent in {"tax_calculation", "accounting_treatment", "document_analysis"}:
        return 4
    return 3


def compact_excerpt(text: str, max_chars: int) -> str:
    value = clean_translation_output(text or "").strip()
    if len(value) <= max_chars:
        return value
    shortened = value[:max_chars]
    cut = max(shortened.rfind(". "), shortened.rfind("; "), shortened.rfind("\n"))
    if cut >= max_chars * 0.6:
        shortened = shortened[:cut + 1]
    return shortened.rstrip() + " [...]"


def legal_context_excerpt_budget(intent: str, answer_style: str) -> int:
    if answer_style == "concept_brief":
        return 420
    if intent == "legal_basis":
        return 650
    if intent in {"tax_calculation", "accounting_treatment", "document_analysis"}:
        return 520
    return 480


def build_legal_context_block(sources: list[dict], intent: str, answer_style: str) -> str:
    excerpt_budget = legal_context_excerpt_budget(intent, answer_style)
    blocks: list[str] = []
    for source in sources:
        header = " | ".join(
            [
                f"Source: {source.get('title', 'Source interne')}",
                f"page {source.get('page')}",
                source.get("heading") or "extrait",
                source.get("authority") or "autorite non precisee",
                source.get("source_tier") or "niveau non precise",
            ]
        )
        blocks.append("\n".join([header, compact_excerpt(source.get("excerpt", ""), excerpt_budget)]))
    return "\n\n".join(blocks)


def legal_sources_by_doc_ids(doc_ids: list[str]) -> list[dict]:
    by_doc: dict[str, dict] = {}
    missing_doc_ids: list[str] = []
    for doc_id in doc_ids:
        metadata = CANONICAL_FISCAL_SOURCE_METADATA.get(doc_id)
        if not metadata:
            missing_doc_ids.append(doc_id)
            continue
        by_doc[doc_id] = {
            "id": f"canonical:{doc_id}",
            "doc_id": doc_id,
            **metadata,
            "heading": "",
            "excerpt": "",
            "source_tier": "primary_law",
            "score": 999.0,
        }

    if missing_doc_ids:
        for record in load_corpus():
            doc_id = record.get("doc_id")
            if doc_id not in missing_doc_ids or doc_id in by_doc:
                continue
            by_doc[doc_id] = {
                "id": record.get("id"),
                "doc_id": doc_id,
                "title": record.get("title") or "Source interne",
                "filename": record.get("filename"),
                "page": record.get("page"),
                "heading": record.get("heading", ""),
                "excerpt": (record.get("text") or "")[:900],
                "source_tier": record.get("source_tier", ""),
                "authority": record.get("authority", ""),
                "year": record.get("year"),
                "score": 999.0,
            }
    return [by_doc[doc_id] for doc_id in doc_ids if doc_id in by_doc]


def fastpath_concept_answer(
    message: str,
    intent: str,
    legal_domain: str,
    golden_kb_hits: list[dict],
    legal_sources: list[dict],
) -> dict | None:
    if not golden_kb_hits:
        return None
    top = golden_kb_hits[0]
    definition = top.get("canonical_definition") or "Les sources internes permettent d'identifier la notion."
    legal_basis = ", ".join(top.get("legal_basis", []))
    if not legal_basis and legal_sources:
        legal_basis = "\n".join(
            f"- {source.get('title', 'Source interne')}, page {source.get('page')}"
            for source in legal_sources[:2]
        )
    vigilance_items = top.get("common_mistakes", [])[:3]
    vigilance = "\n".join(f"- {item}" for item in vigilance_items) or "- Verifier l'application concrete au dossier du client."
    sources_used = summarize_source_titles(
        [{"title": ref.get("title"), "page": None, "heading": ""} for ref in top.get("source_refs", [])]
    ) or summarize_source_titles(legal_sources)
    answer = compose_structured_answer(
        "concept_brief",
        {
            "Definition": definition,
            "Base legale": legal_basis or "Documents internes indexes.",
            "Points de vigilance": vigilance,
            "Sources utilisees": sources_used or "- Base documentaire interne",
        },
    )
    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": intent,
        "preferred_source": "golden_kb",
        "response_style": "concept_brief",
        "golden_kb_hits": golden_kb_hits,
        "sources": legal_sources,
        "model": "internal/golden-kb-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_tva_overview_answer(
    message: str,
    intent: str,
    legal_domain: str,
) -> dict | None:
    if not is_fiscal_overview_query(message, legal_domain, intent):
        return None

    canonical_sources = legal_sources_by_doc_ids([
        "tva_droit_consommation",
        "procedures_fiscales_2026",
        "loi_finances_2026",
    ])
    if not canonical_sources:
        return None
    source_lines = summarize_source_titles(canonical_sources, limit=3)

    answer = "\n\n".join([
        "## Réponse\n"
        "En Tunisie, la TVA est principalement régie par le **Code de la taxe sur la valeur ajoutée**, "
        "promulgué par la **loi n° 88-61 du 2 juin 1988**. Ce code fixe notamment le champ d'application "
        "de la TVA, les opérations imposables ou exonérées, l'assiette, le fait générateur, le droit à déduction "
        "et les obligations propres à cette taxe.\n\n"
        "Ce code est complété par ses textes d'application et par les modifications introduites, le cas échéant, "
        "par les lois de finances. "
        "Le **Code des droits et procédures fiscaux** encadre les règles de contrôle, de redressement, "
        "de sanctions et de contentieux. Des dispositions particulières peuvent aussi "
        "s'appliquer selon l'activité, le produit ou l'opération concernée.\n\n"
        "Le droit de consommation est une imposition distincte de la TVA, même si les deux matières sont "
        "réunies dans un même recueil officiel. Les lois de finances peuvent également modifier certaines "
        "dispositions du régime de TVA.",
        "## Base légale\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": intent,
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": canonical_sources,
        "model": "internal/tva-overview-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_general_fiscal_framework_answer(message: str, legal_domain: str) -> dict | None:
    if not is_general_fiscal_framework_query(message, legal_domain):
        return None

    framework_sources = legal_sources_by_doc_ids([
        "code_irpp_is_2011",
        "tva_droit_consommation",
        "procedures_fiscales_2026",
        "enregistrement_timbre",
        "fiscalite_locale",
        "loi_finances_2026",
    ])
    if not framework_sources:
        return None

    source_lines = summarize_source_titles(framework_sources, limit=6)
    answer = "\n\n".join([
        "## Réponse\n"
        "En Tunisie, la fiscalité n'est pas regroupée dans un Code général des impôts unique. Elle repose "
        "principalement sur plusieurs textes complémentaires :\n"
        "- le **Code de l'IRPP et de l'IS**, pour l'impôt sur le revenu des personnes physiques et l'impôt sur les sociétés ;\n"
        "- le **Code de la taxe sur la valeur ajoutée**, pour la TVA ;\n"
        "- le **Code des droits et procédures fiscaux**, pour le contrôle, le redressement, les sanctions et le contentieux ;\n"
        "- le **Code des droits d'enregistrement et de timbre** ;\n"
        "- le **Code de la fiscalité locale**, pour les impositions relevant des collectivités locales ;\n"
        "- les **lois de finances annuelles**, qui peuvent modifier les taux, avantages, obligations et procédures.\n\n"
        "Ces textes sont complétés par leurs décrets et arrêtés d'application ainsi que par les dispositions "
        "sectorielles pertinentes. Les notes communes et circulaires administratives peuvent éclairer leur "
        "application, sans se substituer aux textes législatifs et réglementaires.",
        "## Base légale\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "general",
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": framework_sources,
        "model": "internal/fiscal-framework-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_fiscal_sources_answer(message: str, legal_domain: str) -> dict | None:
    query = match_key(message)
    if legal_domain not in {"fiscalite", "general"}:
        return None
    if not re.search(r"sources? du droit fiscal|sources? principales? du droit fiscal|principales? sources? du droit fiscal", query, re.I):
        return None

    framework_sources = legal_sources_by_doc_ids([
        "code_irpp_is_2011",
        "tva_droit_consommation",
        "procedures_fiscales_2026",
        "enregistrement_timbre",
        "fiscalite_locale",
        "loi_finances_2026",
    ])
    if not framework_sources:
        return None

    source_lines = summarize_source_titles(framework_sources, limit=6)
    answer = "\n\n".join([
        "## Réponse\n"
        "Les principales sources du droit fiscal tunisien sont d'abord les textes législatifs qui organisent "
        "l'assiette de l'impôt, les procédures fiscales et les principales catégories de prélèvements. En pratique, "
        "il faut retenir en priorité :\n"
        "- le **Code de l'IRPP et de l'IS** ;\n"
        "- le **Code de la taxe sur la valeur ajoutée** ;\n"
        "- le **Code des droits et procédures fiscaux** ;\n"
        "- le **Code des droits d'enregistrement et de timbre** ;\n"
        "- le **Code de la fiscalité locale** ;\n"
        "- les **lois de finances annuelles**, qui modifient régulièrement ces textes ou y ajoutent des mesures nouvelles.\n\n"
        "À ce noyau s'ajoutent les décrets et arrêtés d'application, ainsi que les circulaires et notes communes "
        "qui en précisent l'interprétation pratique sans se substituer aux dispositions législatives et réglementaires.",
        "## Base légale\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "general",
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": framework_sources,
        "model": "internal/fiscal-sources-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_fiscal_code_comparison_answer(message: str, legal_domain: str) -> dict | None:
    query = match_key(message)
    if legal_domain not in {"fiscalite", "general"}:
        return None
    if not (
        ("procedure" in query or "procedures fiscales" in query)
        and ("irpp" in query or "is" in query or "code de l irpp" in query)
        and re.search(r"difference|compar|vs|versus", query, re.I)
    ):
        return None

    sources = legal_sources_by_doc_ids([
        "code_irpp_is_2011",
        "procedures_fiscales_2026",
    ])
    if not sources:
        return None

    source_lines = summarize_source_titles(sources, limit=2)
    answer = "\n\n".join([
        "## Réponse\n"
        "La différence est la suivante : le **Code de l'IRPP et de l'IS** fixe les règles de fond de l'imposition, "
        "alors que le **Code des droits et procédures fiscaux** organise la manière dont l'administration contrôle, "
        "redresse et recouvre l'impôt.\n\n"
        "- **Code de l'IRPP et de l'IS** : il détermine notamment les personnes imposables, les catégories de revenus, "
        "l'assiette, les déductions admises, les règles de calcul et, selon les cas, le régime applicable à l'impôt.\n"
        "- **Code des droits et procédures fiscaux** : il traite principalement des déclarations, du contrôle fiscal, "
        "des notifications, des délais, des voies de recours, des sanctions et du contentieux.\n\n"
        "En pratique, on consulte donc le premier pour savoir quoi est imposé et comment l'impôt se calcule, "
        "et le second pour savoir comment la règle fiscale s'applique, se contrôle et se conteste.",
        "## Base légale\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "comparison",
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/fiscal-code-comparison-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_legal_hierarchy_answer(message: str, legal_domain: str) -> dict | None:
    query = match_key(message)
    if legal_domain not in {"fiscalite", "general"}:
        return None
    if not re.search(r"hierarchie des normes|hierarchie juridique|ordre des normes|valeur juridique des normes|rang des normes", query, re.I):
        return None

    sources = legal_sources_by_doc_ids([
        "code_irpp_is_2011",
        "tva_droit_consommation",
        "procedures_fiscales_2026",
        "loi_finances_2026",
    ])
    if not sources:
        return None

    source_lines = summarize_source_titles(sources, limit=4)
    answer = "\n\n".join([
        "## Réponse\n"
        "En droit fiscal tunisien, la hiérarchie des normes se lit, en pratique, de la manière suivante :\n"
        "- la **Constitution** ;\n"
        "- les **traités internationaux régulièrement ratifiés**, selon leur place dans l'ordre juridique applicable ;\n"
        "- les **lois**, parmi lesquelles figurent les codes fiscaux et les lois de finances ;\n"
        "- les **décrets** et **arrêtés d'application** ;\n"
        "- les **circulaires**, **notes communes** et autres instructions administratives, qui guident l'interprétation pratique sans créer une règle supérieure à la loi.\n\n"
        "En conséquence, un code fiscal et une loi de finances relèvent tous deux du niveau législatif. "
        "Les textes d'application viennent ensuite, puis les prises de position administratives.",
        "## Base légale\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "legal_hierarchy",
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/legal-hierarchy-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_commissariat_texts_answer(message: str, legal_domain: str) -> dict | None:
    query = match_key(message)
    if legal_domain not in {"audit", "general"}:
        return None
    if not re.search(
        r"textes? qui regissent le commissariat aux comptes|"
        r"textes? du commissariat aux comptes|"
        r"commissariat aux comptes en tunisie|"
        r"cadre juridique du commissariat aux comptes|"
        r"quels textes.*commissariat aux comptes",
        query,
        re.I,
    ):
        return None

    sources = legal_sources_by_doc_ids([
        "code_societes_commerciales_2022",
        "textes_profession_comptable_2018",
        "note_orientation_bct_2012_02",
    ])
    if not sources:
        return None

    source_lines = summarize_source_titles(sources, limit=3)
    answer = "\n\n".join([
        "## Réponse\n"
        "En Tunisie, le commissariat aux comptes repose d'abord sur le **Code des sociétés commerciales**, "
        "qui fixe le cadre légal de la désignation, de la mission et, selon les cas, de certaines obligations de contrôle légal. "
        "Ce socle est complété par les textes professionnels relatifs aux **experts-comptables et commissaires aux comptes**, "
        "notamment pour les règles d'exercice, d'indépendance et d'encadrement de la profession.\n\n"
        "À cela s'ajoutent les **normes professionnelles** et textes d'orientation applicables à certaines missions ou secteurs, "
        "notamment lorsqu'un texte réglementaire spécial impose des diligences ou un format de rapport particulier. "
        "En pratique, il faut donc raisonner à la fois avec le cadre sociétaire, le cadre professionnel de la profession comptable "
        "et les normes professionnelles applicables à la mission concernée.",
        "## Sources utilisées\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "general",
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/commissariat-texts-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_loi_finances_tva_answer(message: str, legal_domain: str) -> dict | None:
    query = match_key(message)
    if legal_domain not in {"fiscalite", "general"}:
        return None
    if not re.search(
        r"loi de finances .*modifi.*code tva|"
        r"une loi de finances peut elle modifier le code tva|"
        r"loi de finances peut elle modifier la tva|"
        r"modification du code tva par loi de finances",
        query,
        re.I,
    ):
        return None

    sources = legal_sources_by_doc_ids([
        "tva_droit_consommation",
        "loi_finances_2026",
        "procedures_fiscales_2026",
    ])
    if not sources:
        return None

    source_lines = summarize_source_titles(sources, limit=3)
    answer = "\n\n".join([
        "## Réponse\n"
        "Oui. En Tunisie, une **loi de finances** peut modifier le **Code de la taxe sur la valeur ajoutée**, "
        "comme elle peut modifier d'autres textes fiscaux de niveau législatif. En pratique, la loi de finances "
        "peut changer des taux, des exonérations, des modalités d'application ou introduire des dispositions nouvelles "
        "qui s'intègrent au régime de TVA.\n\n"
        "Il convient toutefois de distinguer le **texte de base** de la TVA, qui demeure le Code de la taxe sur la valeur ajoutée, "
        "et les **modifications législatives annuelles** apportées par les lois de finances. Pour une réponse complète sur un point précis, "
        "il faut donc lire le code avec ses textes d'application et vérifier les lois de finances modificatives pertinentes.",
        "## Base légale\n"
        f"{source_lines}",
    ])

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "general",
        "preferred_source": "legal_corpus",
        "response_style": "flexible_expert",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/loi-finances-tva-fastpath",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def merge_priority_sources(priority_sources: list[dict], retrieved_sources: list[dict], limit: int = 5) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for source in [*priority_sources, *retrieved_sources]:
        key = source.get("doc_id") or source.get("id") or source.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(source)
        if len(merged) >= limit:
            break
    return merged


def case_analysis_sources(message: str, legal_sources: list[dict]) -> list[dict]:
    query = match_key(message)
    priority_doc_ids: list[str] = []
    blocked_doc_ids: set[str] = set()

    if "dividende" in query or "dividendes" in query:
        priority_doc_ids = ["code_irpp_is_2011", "loi_finances_2026", "procedures_fiscales_2026"]
        blocked_doc_ids = {
            "code_societes_commerciales_2022",
            "guide_creation_sarl_tunisie",
            "droits_taxes_hors_codes",
            "fiscalite_locale",
        }
    elif ("prestations de services" in query or "prestation informatique" in query) and ("france" in query or "client etabli" in query or "client francais" in query):
        priority_doc_ids = ["tva_droit_consommation", "procedures_fiscales_2026", "loi_finances_2026"]
        blocked_doc_ids = {"code_irpp_is_2011", "code_societes_commerciales_2022", "droits_taxes_hors_codes", "fiscalite_locale"}
    elif "fraude" in query and ("commissaire aux comptes" in query or "rapport" in query):
        priority_doc_ids = [
            "audit_resume_gaida_normes_missions",
            "audit_resume_acceptation_controle_qualite",
            "code_societes_commerciales_2022",
        ]
    elif "amortissement" in query and ("immobilisation" in query or "corporelle" in query):
        priority_doc_ids = ["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles", "nc_01_norme_generale"]
        blocked_doc_ids = {
            "audit_resume_gaida_normes_missions",
            "audit_resume_chakroun_scan",
            "audit_resume_acceptation_controle_qualite",
            "cours_audit_chiheb_ghanmi",
            "audit_controle_qualite_imed_ennouri",
            "cours_audit_imed_ennouri",
        }
    elif ("creances douteuses" in query or "créances douteuses" in query or "creance douteuse" in query or "créance douteuse" in query) and (
        "deductible" in query or "deductibilite" in query or "deductibile" in query or "déductible" in query or "déductibilité" in query
    ):
        priority_doc_ids = ["code_irpp_is_2011", "procedures_fiscales_2026", "nc_01_norme_generale", "ias_37_provisions_passifs_actifs_eventuels"]
        blocked_doc_ids = {
            "code_commerce_2014",
            "nct_44_takaful_controle_interne",
            "nc_22_bancaire_controle_interne",
            "droits_taxes_hors_codes",
            "fiscalite_locale",
        }

    if not priority_doc_ids and not blocked_doc_ids:
        return legal_sources

    filtered = [source for source in legal_sources if source.get("doc_id") not in blocked_doc_ids]
    priority = legal_sources_by_doc_ids(priority_doc_ids) if priority_doc_ids else []
    return merge_priority_sources(priority, filtered, limit=len(priority_doc_ids) if priority_doc_ids else 5)


def fastpath_case_analysis_answer(message: str, intent: str, legal_domain: str, legal_sources: list[dict]) -> dict | None:
    query = match_key(message)
    sources = case_analysis_sources(message, legal_sources)
    source_lines = summarize_source_titles(sources, limit=5)
    if not sources:
        return None

    answer: str | None = None
    returned_intent = intent
    returned_domain = legal_domain

    if "dividende" in query or "dividendes" in query:
        returned_intent = "tax_calculation" if intent == "general" else intent
        returned_domain = "fiscalite"
        beneficiary_label = "résident"
        if "non resident" in query or "non-résident" in query:
            beneficiary_label = "non-résident"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Pour une distribution de dividendes par une SARL tunisienne à un associé {beneficiary_label}, l'analyse doit d'abord porter "
                    "sur la retenue à la source éventuellement applicable au moment du paiement, puis sur les obligations déclaratives "
                    "et la justification remise à l'associé. Le montant de 250 000 TND ne suffit pas, à lui seul, pour conclure sur le taux "
                    "ou sur un caractère définitif d'imposition sans retrouver l'article fiscal applicable dans la version en vigueur."
                ),
                "Application pratique": (
                    "- Identifier la qualité exacte de l'associé: personne physique ou morale, statut de résidence fiscale, régime particulier éventuel.\n"
                    "- Vérifier dans le Code de l'IRPP et de l'IS le régime des revenus distribués et de la retenue à la source.\n"
                    "- Si l'associé est non-résident, vérifier en plus la convention fiscale applicable et les conditions documentaires liées au bénéficiaire étranger.\n"
                    "- Vérifier les modifications des lois de finances applicables à l'année 2026 avant de retenir un taux.\n"
                    "- Préparer les éléments de paiement: décision de distribution, montant brut, retenue opérée le cas échéant, déclaration, reversement et certificat de retenue."
                ),
                "Points de vigilance": (
                    "- Ne pas affirmer un taux, une option ou un caractère définitif d'imposition si l'article exact n'est pas cité.\n"
                    "- Ne pas confondre le traitement fiscal d'un associé résident avec celui d'un associé non-résident, ni celui d'une personne physique avec celui d'une personne morale.\n"
                    "- Séparer la régularité sociétaire de la distribution et son traitement fiscal."
                ),
                "Sources utilisees": source_lines,
            },
        )
        if "250 000" not in query and "250000" not in query and answer:
            answer = answer.replace(
                "Le montant de 250 000 TND ne suffit pas, à lui seul, pour conclure sur le taux ou sur un caractère définitif d'imposition sans retrouver l'article fiscal applicable dans la version en vigueur.",
                "La seule annonce d'une distribution en 2026 ne suffit pas, à elle seule, pour conclure sur le taux ou sur un caractère définitif d'imposition sans retrouver l'article fiscal applicable dans la version en vigueur.",
            )
        if "non resident" not in query and "non-résident" not in query and answer:
            answer = answer.replace(
                "- Si l'associé est non-résident, vérifier en plus la convention fiscale applicable et les conditions documentaires liées au bénéficiaire étranger.\n",
                "",
            )

    elif ("prestations de services" in query or "prestation informatique" in query) and ("france" in query or "client etabli" in query or "client francais" in query):
        returned_intent = "legal_basis"
        returned_domain = "fiscalite"
        non_assujetti = "non assujetti" in query
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Pour des prestations de services facturées par une société tunisienne à un client établi en France, il faut raisonner "
                    "en TVA sur la territorialité, la nature exacte du service et les conditions de preuve liées au client étranger. "
                    "La réponse ne doit pas être déduite de l'IRPP/IS: le texte de référence est le Code de la taxe sur la valeur ajoutée, "
                    "complété par les règles de procédure fiscale."
                ),
                "Application pratique": (
                    "- Qualifier le service: prestation intellectuelle, numérique, assistance, étude, licence, intervention matériellement exécutée en Tunisie ou hors Tunisie.\n"
                    + ("- Identifier le lieu d'établissement et le statut du client français non assujetti, puis vérifier si le régime diffère d'une prestation rendue à un assujetti.\n" if non_assujetti else "- Identifier le lieu d'établissement et le statut du client français, puis vérifier si l'opération relève d'une exportation ou d'un régime d'exonération avec droit à déduction.\n")
                    + "- Conserver les preuves: contrat, bon de commande, facture, justificatifs du client étranger, preuve de paiement et éléments montrant que le bénéficiaire est établi hors de Tunisie.\n"
                    "- Vérifier séparément les retenues à la source ou conventions fiscales seulement si le paiement transfrontalier soulève un sujet d'IRPP/IS."
                ),
                "Points de vigilance": (
                    "- Ne pas citer le Code de l'IRPP et de l'IS comme base de la TVA.\n"
                    + ("- La qualité de client non assujetti peut modifier l'analyse; ne pas reprendre mécaniquement la solution d'un schéma B2B.\n" if non_assujetti else "")
                    + "- Ne pas conclure définitivement sans connaître la nature du service et le lieu d'utilisation ou d'exploitation.\n"
                    + "- Les règles de facturation et les justificatifs conditionnent la sécurité du traitement."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif "fraude" in query and ("commissaire aux comptes" in query or "rapport" in query):
        returned_intent = "legal_basis"
        returned_domain = "audit"
        before_signature = "avant la signature" in query
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    ("Si le commissaire aux comptes découvre une fraude avant la signature de son rapport, il doit intégrer cette information dans ses travaux avant émission, "
                     "réévaluer le risque, l'incidence sur les états financiers et les conséquences sur l'opinion envisagée."
                    ) if before_signature else
                    ("Si le commissaire aux comptes découvre une fraude après l'émission de son rapport, la réponse n'est pas de redéfinir le CAC: "
                     "il doit analyser si l'information existait à la date du rapport, si elle remet en cause les états financiers ou l'opinion émise, "
                     "et quelles communications ou diligences complémentaires sont nécessaires.")
                ),
                "Application pratique": (
                    "- Documenter la date de découverte, la nature de la fraude, les montants, les personnes concernées et les périodes touchées.\n"
                    + ("- Réévaluer immédiatement le programme de travail, les éléments probants et l'opinion avant signature.\n" if before_signature else "- Évaluer l'incidence sur les états financiers déjà audités et sur le rapport émis.\n")
                    + "- Informer le niveau approprié de direction et de gouvernance, sauf situation imposant une autre voie de communication.\n"
                    + ("- Déterminer s'il faut demander une correction, étendre les diligences ou adapter l'opinion avant émission.\n" if before_signature else "- Déterminer s'il faut demander une correction, émettre une communication complémentaire, modifier la position du cabinet ou consulter juridiquement avant toute démarche externe.\n")
                    + "- Conserver une documentation complète des faits, décisions, échanges et fondements professionnels."
                ),
                "Points de vigilance": (
                    "- Ne pas traiter la fraude comme une simple anomalie sans apprécier son caractère significatif et intentionnel.\n"
                    "- Vérifier les obligations légales, professionnelles et sectorielles applicables avant toute communication externe.\n"
                    + ("- Avant signature, ne pas finaliser le rapport tant que l'incidence n'est pas correctement analysée.\n" if before_signature else "- Lorsque la situation touche un rapport déjà émis, une revue qualité ou un avis juridique est prudent avant conclusion.")
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif "amortissement" in query and ("immobilisation" in query or "corporelle" in query):
        returned_intent = "accounting_treatment"
        returned_domain = "comptabilite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Avant la clôture, l'amortissement d'une immobilisation corporelle doit être analysé comme une estimation comptable: "
                    "il faut vérifier la base amortissable, la durée d'utilité, le mode d'amortissement, la date de mise en service et l'existence "
                    "éventuelle d'indices de perte de valeur."
                ),
                "Application pratique": (
                    "- Rapprocher l'actif avec les factures, le registre des immobilisations et la date de mise en service.\n"
                    "- Vérifier le coût d'entrée, les composants significatifs, la valeur résiduelle éventuelle et la durée d'utilité retenue.\n"
                    "- Contrôler le mode d'amortissement et sa cohérence avec le rythme de consommation des avantages économiques.\n"
                    "- Calculer la dotation de l'exercice et rapprocher la comptabilité avec le tableau des immobilisations.\n"
                    "- Traiter séparément les limites ou réintégrations fiscales éventuelles: elles ne doivent pas remplacer l'analyse comptable."
                ),
                "Points de vigilance": (
                    "- Éviter de reprendre automatiquement les taux fiscaux comme durées comptables.\n"
                    "- Revoir les actifs cédés, mis au rebut, non utilisés ou devenus obsolètes.\n"
                    "- Documenter tout changement de durée, de méthode ou d'estimation."
                ),
                "Sources utilisees": source_lines,
            },
        )
        if ("a partir de quelle date" in query or "15 septembre" in query) and answer:
            answer = answer.replace(
                "## Reponse\n",
                "## Reponse\nL'amortissement commence à la date à laquelle l'immobilisation est prête à être utilisée dans les conditions prévues par l'entreprise. Si l'actif acheté le 15 septembre est immédiatement disponible et mis en service, le point de départ est le 15 septembre; si une installation, un essai ou une mise en service intervient plus tard, l'amortissement commence à cette date de mise en service.\n\n",
                1,
            )

    elif ("creances douteuses" in query or "créances douteuses" in query or "creance douteuse" in query or "créance douteuse" in query) and (
        "deductible" in query or "deductibilite" in query or "deductibile" in query or "déductible" in query or "déductibilité" in query
    ):
        returned_intent = "tax_calculation" if intent == "general" else intent
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Une provision pour créances douteuses ne doit pas être traitée comme une simple définition comptable. "
                    "Il faut distinguer la constatation comptable de la dépréciation et sa déductibilité fiscale. En pratique, "
                    "elle n'est défendable fiscalement que si la créance est individualisée, le risque de non-recouvrement est réel, "
                    "le montant est estimé de manière fiable et le dossier contient des justificatifs suffisants."
                ),
                "Application pratique": (
                    "- Identifier chaque créance: client, facture, échéance, montant TTC/HT, ancienneté et solde restant dû.\n"
                    "- Documenter les indices de doute: retards, relances, litige, procédure de recouvrement, situation financière du débiteur, garanties.\n"
                    "- Comptabiliser la dépréciation avant clôture selon une méthode cohérente et justifiée.\n"
                    "- Vérifier dans le Code de l'IRPP et de l'IS les conditions fiscales spécifiques avant déduction du résultat imposable.\n"
                    "- Préparer un dossier de contrôle: balance âgée, relances, correspondances, calcul de la provision et validation de direction."
                ),
                "Points de vigilance": (
                    "- Une provision globale ou forfaitaire sans analyse client par client est fragile.\n"
                    "- La déductibilité fiscale peut être plus restrictive que le traitement comptable.\n"
                    "- Vérifier les règles applicables à l'année concernée et les éventuelles limites sectorielles."
                ),
                "Sources utilisees": source_lines,
            },
        )

    if not answer:
        return None

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": returned_intent,
        "preferred_source": "legal_corpus",
        "response_style": "practical_analysis",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/case-analysis-playbook",
        "fallback_mode": False,
        "legal_domain": returned_domain,
        "question": message,
    }


def fallback_accounting_answer(
    message: str,
    intent: str,
    answer_style: str,
    legal_domain: str,
    golden_kb_hits: list[dict],
    legal_sources: list[dict],
) -> dict | None:
    if not golden_kb_hits and not legal_sources:
        return None

    case_fallback = fastpath_case_analysis_answer(message, intent, legal_domain, legal_sources)
    if case_fallback:
        case_fallback["fallback_mode"] = True
        case_fallback["model"] = "fallback/case-analysis-playbook"
        return case_fallback

    fallback_preferred_source = "golden_kb" if answer_style == "concept_brief" and golden_kb_hits else "legal_corpus"

    if answer_style == "concept_brief":
        top = golden_kb_hits[0] if golden_kb_hits else None
        definition = top.get("canonical_definition") if top else "La notion doit être rattachée aux textes applicables et au contexte précis du dossier."
        legal_basis = ", ".join(top.get("legal_basis", [])) if top else (
            ", ".join({client_source_title(source) for source in legal_sources[:2] if source.get("title")}) or "Base légale à préciser selon le dossier"
        )
        vigilance_items = top.get("common_mistakes", []) if top else []
        vigilance = "\n".join(f"- {item}" for item in vigilance_items[:3]) or "- Verifier l'application concrete de la notion au dossier du client."
        sources_used = summarize_source_titles(
            [{"title": ref.get("title"), "page": None, "heading": ""} for ref in top.get("source_refs", [])] if top else legal_sources
        )
        answer = compose_structured_answer(
            "concept_brief",
            {
                "Definition": definition,
                "Base legale": legal_basis,
                "Points de vigilance": vigilance,
                "Sources utilisees": sources_used or "- Base documentaire interne",
            },
        )
    else:
        response = "En première analyse, la réponse doit être rattachée aux textes applicables et aux faits précis du dossier."
        if legal_sources:
            main_title = client_source_title(legal_sources[0])
            response = f"En première analyse, le point doit être rattaché principalement au cadre suivant : {main_title}."
        practical = "- Identifier le texte exact applicable au cas du client.\n- Verifier la date de la version du texte et les modifications ulterieures.\n- Contrôler les pieces, montants, periodes et hypotheses avant conclusion."
        vigilance = "- Confirmer le texte, la date et les seuils applicables avant usage client.\n- Ne pas conclure sans rapprocher les faits du dossier avec la version officielle du texte."
        sources_used = summarize_source_titles(legal_sources) or summarize_source_titles(
            [{"title": ref.get("title"), "page": None, "heading": ""} for hit in golden_kb_hits for ref in hit.get("source_refs", [])]
        )
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": response,
                "Application pratique": practical,
                "Points de vigilance": vigilance,
                "Sources utilisees": sources_used or "- Base documentaire interne",
            },
        )

    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [
            "Verifier les textes officiels en vigueur avant usage client, surtout pour les points fiscaux et proceduraux."
        ],
        "intent": intent,
        "preferred_source": fallback_preferred_source,
        "response_style": answer_style,
        "golden_kb_hits": golden_kb_hits,
        "sources": legal_sources,
        "model": "fallback/internal-knowledge",
        "fallback_mode": True,
        "legal_domain": legal_domain,
        "question": message,
    }


def normalize_chat_payload(parsed: dict, answer_style: str = "flexible_expert") -> tuple[str, list[str], list[str], list[str]]:
    answer = clean_translation_output(str(parsed.get("answer") or parsed.get("translation") or "")).strip()
    assumptions_raw = parsed.get("assumptions")
    next_steps_raw = parsed.get("next_steps")
    warnings_raw = parsed.get("warnings")
    assumptions = assumptions_raw if isinstance(assumptions_raw, list) else split_list_block(str(assumptions_raw or ""))
    next_steps = next_steps_raw if isinstance(next_steps_raw, list) else split_list_block(str(next_steps_raw or ""))
    warnings = warnings_raw if isinstance(warnings_raw, list) else split_list_block(str(warnings_raw or ""))

    if answer.startswith("{") and '"answer"' in answer:
        try:
            nested = extract_json(answer)
            nested_answer = clean_translation_output(str(nested.get("answer") or nested.get("translation") or "")).strip()
            if nested_answer:
                answer = nested_answer
            if not assumptions:
                assumptions_raw = nested.get("assumptions")
                assumptions = assumptions_raw if isinstance(assumptions_raw, list) else split_list_block(str(assumptions_raw or ""))
            if not next_steps:
                next_steps_raw = nested.get("next_steps")
                next_steps = next_steps_raw if isinstance(next_steps_raw, list) else split_list_block(str(next_steps_raw or ""))
            if not warnings:
                warnings_raw = nested.get("warnings")
                warnings = warnings_raw if isinstance(warnings_raw, list) else split_list_block(str(warnings_raw or ""))
        except Exception:
            pass

    if answer and (not assumptions or not next_steps or not warnings):
        parts = SECTION_SPLIT_RE.split(answer)
        if len(parts) > 1:
            clean_answer = clean_translation_output(parts[0]).strip()
            extracted: dict[str, list[str]] = {"assumptions": [], "next_steps": [], "warnings": []}
            for index in range(1, len(parts), 2):
                label = parts[index].strip().lower()
                block = parts[index + 1] if index + 1 < len(parts) else ""
                if label == "assumptions" and not assumptions:
                    extracted["assumptions"] = split_list_block(block)
                elif label == "next steps" and not next_steps:
                    extracted["next_steps"] = split_list_block(block)
                elif label == "warnings" and not warnings:
                    extracted["warnings"] = split_list_block(block)
            answer = clean_answer or answer
            assumptions = assumptions or extracted["assumptions"]
            next_steps = next_steps or extracted["next_steps"]
            warnings = warnings or extracted["warnings"]

    answer = ensure_answer_sections(answer, answer_style)

    return (
        answer,
        [clean_translation_output(str(item)).strip() for item in assumptions if str(item).strip()],
        [clean_translation_output(str(item)).strip() for item in next_steps if str(item).strip()],
        [clean_translation_output(str(item)).strip() for item in warnings if str(item).strip()],
    )


def fiscal_answer_needs_repair(answer: str, legal_domain: str) -> bool:
    if legal_domain not in {"fiscalite", "general"}:
        return False
    answer_text = (answer or "").lower()
    forbidden_patterns = [
        r"code general des impots",
        r"code général des impôts",
        r"\bcgi\b",
        r"livre i\s*:\s*imp[oô]t sur le revenu",
        r"livre ii\s*:\s*imp[oô]t sur les soci",
        r"livre iii\s*:\s*taxe sur la valeur ajout",
        r"livre iv\s*:\s*droits d'enregistrement",
        r"livre v\s*:\s*imp[oô]ts locaux",
        r"livre vi\s*:\s*taxes sp[eé]cifiques",
        r"code des impots",
        r"code de s impots",
    ]
    return any(re.search(pattern, answer_text, re.I) for pattern in forbidden_patterns)


def is_fiscal_overview_query(message: str, legal_domain: str, intent: str) -> bool:
    if legal_domain not in {"fiscalite", "general"}:
        return False
    query = match_key(message)
    if intent not in {"general", "legal_basis", "flexible_expert"}:
        return False
    return bool(re.search(
        r"lois? de tva|tva .*generalement|donnez? moi les lois de tva|"
        r"presentation de la tva|cadre general de la tva|regime tva general",
        query,
        re.I,
    ))


def is_general_fiscal_framework_query(message: str, legal_domain: str) -> bool:
    if legal_domain not in {"fiscalite", "general"}:
        return False
    query = match_key(message)
    if "tva" in query:
        return False
    return bool(re.search(
        r"quelles sont les lois de fiscalit|quelles sont les lois fiscal|"
        r"donnez? moi les lois de fiscalit|donnez? moi les lois fiscal|"
        r"donnes? moi les lois de fiscalit|donnes? moi les lois fiscal|"
        r"cadre juridique de la fiscalit|cadre fiscal tunisien|systeme fiscal tunisien|"
        r"principaux textes fiscaux|principales lois fiscales|textes de fiscalit|"
        r"lois de fiscalite en tunisie|lois fiscales en tunisie|"
        r"fiscalite .*tunisie.*generalement|fiscalite tunisienne.*generalement|"
        r"cadre general de la fiscalit|reglementation fiscale generale",
        query,
        re.I,
    ))


def fiscal_overview_answer_needs_repair(answer: str, message: str, legal_domain: str, intent: str) -> bool:
    if not is_fiscal_overview_query(message, legal_domain, intent):
        return False
    answer_text = (answer or "").lower()
    risky_patterns = [
        r"version consolid[ée]e?[^\n]{0,40}[àa] jour",
        r"janvier\s*2026",
        r"taux normal est de",
        r"taux r[ée]duit",
        r"super[- ]r[ée]duit",
        r"mensuelle ou trimestrielle",
        r"seuil de franchise",
        r"r[ée]gime du forfait",
        r"v[ée]hicules de tourisme",
        r"locations nues d[' ]habitation",
        r"op[ée]rations financi[èe]res, assurances",
    ]
    hits = sum(1 for pattern in risky_patterns if re.search(pattern, answer_text, re.I))
    return hits >= 2


def answer_needs_professional_repair(answer: str) -> bool:
    answer_text = (answer or "").lower()
    risky_patterns = [
        r"we need to answer",
        r"we need to rewrite",
        r"rewrite the answer",
        r"the answer should",
        r"system prompt",
        r"developer prompt",
        r"retourne uniquement un json",
        r"json valide",
        r"tu es un assistant",
        r"according to indexed",
        r"sources internes recup",
        r"sources internes récup",
        r"documents actuellement index",
        r"la bonne reponse consiste",
        r"la bonne réponse consiste",
        r"moteur conversationnel",
        r"reponse de secours",
        r"réponse de secours",
        r"fallback",
        r'"\s*answer\s*"\s*:',
    ]
    risky_patterns.extend([
        r"we need to",
        r"rewrite answer",
        r"correcting error",
        r"article\s*\[\s*x\s*\]",
        r"source implicite",
        r"r[Ã©e]f[Ã©e]rence implicite",
        r"sources? non cit[Ã©e]es",
        r"non cit[Ã©e] dans le corpus",
    ])
    return any(re.search(pattern, answer_text, re.I) for pattern in risky_patterns)


def accounting_log_doc_refs(rows: list[dict], limit: int = 5) -> list[dict]:
    refs: list[dict] = []
    for row in rows[:limit]:
        refs.append(
            {
                "doc_id": row.get("doc_id"),
                "title": client_source_title(row) if row.get("title") or row.get("doc_id") else "Source interne",
                "page": row.get("page"),
                "score": row.get("score"),
            }
        )
    return refs


def append_accounting_chat_log(event: dict) -> None:
    if not config.ACCOUNTING_CHAT_LOG_ENABLED:
        return
    payload = {
        "logged_at": int(time.time()),
        "app_revision": config.APP_REVISION,
        **event,
    }
    payload.setdefault("user_rating", None)
    payload.setdefault("review_status", None)
    try:
        with ACCOUNTING_CHAT_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def accounting_runtime_environment() -> str:
    return (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("RENDER_SERVICE_NAME")
        or os.getenv("SPACE_ID")
        or "local"
    )


def public_space_revision() -> str | None:
    cached = SPACE_REVISION_CACHE.get("value")
    cached_at = float(SPACE_REVISION_CACHE.get("ts") or 0)
    if cached and time.time() - cached_at < 300:
        return str(cached)
    space_id = (
        os.getenv("HF_SPACE_ID")
        or os.getenv("SPACE_ID")
        or os.getenv("SPACE_REPOSITORY")
        or "mhammed001/judicial-translator-backend"
    )
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/spaces/{space_id}", timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        runtime = payload.get("runtime") or {}
        revision = runtime.get("sha") or payload.get("sha")
        if revision:
            revision = str(revision)[:7]
            SPACE_REVISION_CACHE["value"] = revision
            SPACE_REVISION_CACHE["ts"] = time.time()
            return revision
    except Exception:
        return None
    return None


def effective_app_revision() -> str:
    if config.APP_REVISION and config.APP_REVISION != "unknown":
        return config.APP_REVISION
    return public_space_revision() or config.APP_REVISION or "unknown"


def version_payload() -> dict:
    return {
        "app_version": app.version,
        "commit_hash": effective_app_revision(),
        "environment": accounting_runtime_environment(),
        "deployed_at": (
            os.getenv("DEPLOYED_AT")
            or os.getenv("RENDER_DEPLOY_CREATED_AT")
            or os.getenv("BUILD_TIMESTAMP")
            or None
        ),
        "service_name": (
            os.getenv("RENDER_SERVICE_NAME")
            or os.getenv("SPACE_ID")
            or os.getenv("SERVICE_NAME")
            or "local"
        ),
        "branch": (
            os.getenv("RENDER_GIT_BRANCH")
            or os.getenv("BRANCH")
            or os.getenv("GIT_BRANCH")
            or os.getenv("CF_PAGES_BRANCH")
            or None
        ),
        "case_analysis_available": True,
        "accounting_chat_debug_available": True,
    }


def accounting_debug_enabled(request: AccountingChatRequest) -> bool:
    env_value = os.getenv("ACCOUNTING_CHAT_DEBUG", "").lower()
    return bool(getattr(request, "debug", False)) or env_value in {"1", "true", "yes", "on"}


def controlled_source_insufficient_response(original: dict, selected_sources: list[dict]) -> dict:
    sources_used = summarize_source_titles(selected_sources or original.get("sources") or [], limit=5)
    return {
        "success": True,
        "answer": compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Les sources disponibles ne permettent pas de produire une reponse suffisamment fiable "
                    "pour un usage client sans verification complementaire."
                ),
                "Application pratique": (
                    "- Reprendre la question avec les pieces, dates, statuts fiscaux et textes applicables.\n"
                    "- Verifier les articles exacts dans les sources officielles avant toute conclusion.\n"
                    "- Relancer l'analyse apres correction des sources ou du fournisseur IA si necessaire."
                ),
                "Points de vigilance": (
                    "- Une reponse automatique a ete bloquee car elle contenait un marqueur interne, "
                    "un placeholder juridique ou une reference non exploitable.\n"
                    "- Le systeme ne doit jamais afficher ce type de contenu au client final."
                ),
                "Sources utilisees": sources_used or "- Source insuffisante",
            },
        ),
        "assumptions": [],
        "next_steps": [],
        "warnings": [
            "Reponse remplacee par le garde-fou final: sortie interne ou reference insuffisante detectee."
        ],
        "intent": original.get("intent"),
        "preferred_source": original.get("preferred_source"),
        "response_style": "practical_analysis",
        "golden_kb_hits": original.get("golden_kb_hits", []),
        "sources": original.get("sources", selected_sources),
        "model": "guardrail/source-insufficient",
        "fallback_mode": True,
        "legal_domain": original.get("legal_domain"),
        "question": original.get("question"),
        "blocked_by_guardrail": True,
    }


def finalize_accounting_response(
    response: dict,
    request: AccountingChatRequest,
    *,
    endpoint_name: str = "POST /v1/accounting-chat",
    intent: str | None = None,
    workflow: str | None = None,
    case_analysis_enabled: bool = False,
    retrieval_domains: list[str] | None = None,
    selected_sources: list[dict] | None = None,
    fallback_used: bool | None = None,
    answer_template_used: str | None = None,
    generator_path: str | None = None,
) -> dict:
    output = dict(response)
    effective_sources = selected_sources if selected_sources is not None else (output.get("sources") or [])
    blocked = answer_needs_professional_repair(str(output.get("answer") or ""))
    if blocked:
        output = controlled_source_insufficient_response(output, effective_sources)

    trace = {
        "app_version": app.version,
        "commit_hash": effective_app_revision(),
        "environment": accounting_runtime_environment(),
        "endpoint_name": endpoint_name,
        "intent": intent or output.get("intent"),
        "workflow": workflow or output.get("workflow"),
        "case_analysis_enabled": case_analysis_enabled,
        "retrieval_domains": retrieval_domains or ([output.get("legal_domain")] if output.get("legal_domain") else []),
        "selected_sources": accounting_log_doc_refs(effective_sources),
        "fallback_used": bool(output.get("fallback_mode")) if fallback_used is None else fallback_used,
        "answer_template_used": answer_template_used or output.get("response_style"),
        "generator_path": generator_path or output.get("model"),
        "guardrail_blocked": blocked,
    }
    if accounting_debug_enabled(request):
        output["debug_trace"] = trace
    return output


def should_use_financial_glossary(message: str) -> bool:
    query = (message or "").lower()
    return bool(re.search(
        r"tradu(?:ire|ction)|equivalent|équivalent|que veut dire|signification|definition|définition|"
        r"term[e]?\b|glossaire|en arabe|en anglais|en francais|en français|means\b|meaning\b",
        query,
        re.I,
    ))


def should_prefer_golden_kb(intent: str) -> bool:
    return intent in {"definition", "audit", "company_law", "comparison", "professional_formality"}


def preferred_answer_style(intent: str, prefer_golden_kb: bool) -> str:
    if intent in {"definition", "comparison", "audit", "company_law", "professional_formality"} and prefer_golden_kb:
        return "concept_brief"
    if intent in {"legal_basis", "tax_calculation", "accounting_treatment", "document_analysis"}:
        return "practical_analysis"
    return "flexible_expert"


def accounting_chat_max_tokens(answer_style: str, intent: str) -> int:
    if answer_style == "concept_brief":
        return 700
    if answer_style == "practical_analysis":
        return 1200 if intent in {"legal_basis", "tax_calculation"} else 1000
    return 1100


def prioritize_accounting_chat_routes(routes: list[dict], answer_style: str) -> list[dict]:
    def provider_rank(route: dict) -> tuple[int, str]:
        provider = route.get("provider", "")
        model = str(route.get("model", ""))
        if answer_style == "concept_brief":
            rank = {
                "pollinations": 0,
                "kilo": 1,
                "gemini": 2,
                "openrouter": 3,
            }.get(provider, 9)
        elif answer_style == "practical_analysis":
            rank = {
                "kilo": 0,
                "pollinations": 1,
                "gemini": 2,
                "openrouter": 3,
            }.get(provider, 9)
        else:
            rank = {
                "kilo": 0,
                "pollinations": 1,
                "gemini": 2,
                "openrouter": 3,
            }.get(provider, 9)
        return rank, model

    return sorted(routes, key=provider_rank)


def job_path(job_id: str, suffix: str) -> Path:
    safe_id = re.sub(r"[^a-f0-9-]", "", job_id.lower())
    return JOB_DIR / f"{safe_id}.{suffix}"


def write_job(job_id: str, payload: dict) -> None:
    status_path = job_path(job_id, "json")
    payload = {"job_id": job_id, **payload}
    temp_path = status_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(status_path)


def read_job(job_id: str) -> dict:
    status_path = job_path(job_id, "json")
    if not status_path.exists():
        raise HTTPException(status_code=404, detail="Job introuvable ou expire.")
    return json.loads(status_path.read_text(encoding="utf-8"))


async def run_document_job(
    job_id: str,
    content: bytes,
    filename: str,
    source_lang: str,
    target_lang: str | None,
    notes: str | None,
    output_format: str,
) -> None:
    write_job(job_id, {
        "status": "processing",
        "progress": 12,
        "message": "Document reçu. Détection du format et préparation.",
        "filename": filename,
    })
    cooldowns = [35, 90, 180, 300]
    max_attempts = len(cooldowns) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            write_job(job_id, {
                "status": "processing",
                "progress": min(85, 12 + (attempt - 1) * 8),
                "message": f"Traitement IA en cours avec Gemini et les fournisseurs de secours. Tentative {attempt}/{max_attempts}.",
                "filename": filename,
            })
            content_out, media_type, output_filename = await build_translated_document(
                content=content,
                filename=filename,
                source_lang=source_lang,
                target_lang=target_lang,
                notes=notes,
                output_format=output_format,
            )
            result_path = job_path(job_id, "bin")
            result_path.write_bytes(content_out)
            write_job(job_id, {
                "status": "completed",
                "progress": 100,
                "message": "Document traduit prêt.",
                "filename": filename,
                "output_filename": output_filename,
                "media_type": media_type,
                "bytes": len(content_out),
            })
            return
        except ProviderRateLimitError as error:
            if attempt >= max_attempts:
                write_job(job_id, {
                    "status": "failed",
                    "progress": 100,
                    "message": friendly_provider_error(error),
                    "filename": filename,
                })
                return
            delay = cooldowns[attempt - 1]
            write_job(job_id, {
                "status": "waiting",
                "progress": min(90, 18 + attempt * 10),
                "message": f"Fournisseur IA saturé (429). Nouvelle tentative automatique dans {delay} secondes.",
                "filename": filename,
                "retry_in_seconds": delay,
                "attempt": attempt,
                "max_attempts": max_attempts,
            })
            await asyncio.sleep(delay)
        except Exception as error:
            write_job(job_id, {
                "status": "failed",
                "progress": 100,
                "message": friendly_provider_error(error),
                "filename": filename,
            })
            return


@app.get("/health")
async def health() -> dict:
    version = version_payload()
    return {
        "ok": True,
        **version,
        "backend_revision": config.APP_REVISION,
        "accounting_chat_debug_enabled": os.getenv("ACCOUNTING_CHAT_DEBUG", "").lower() in {"1", "true", "yes", "on"},
        "model": config.LLM_MODEL,
        "llm_configured": bool(config.LLM_API_KEY),
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "gemini_ready": config.GEMINI_API_KEY_READY,
        "gemini_models": config.GEMINI_MODELS if config.GEMINI_API_KEY_READY else [],
        "native_formats": ["pdf", "docx", "pptx", "xlsx", "html", "txt"],
        "ocr_available": bool(shutil.which("tesseract")),
        "ocr_languages": ["ara", "fra", "eng"],
        "keyless_fallbacks_enabled": config.ENABLE_KEYLESS_FALLBACKS,
        "keyless_fallback_providers": ["pollinations", "kilo"] if config.ENABLE_KEYLESS_FALLBACKS else [],
        "active_skills": ACTIVE_SKILLS,
        "legal_corpus": corpus_status(),
        "golden_kb": golden_kb_status(),
    }


@app.get("/version")
async def version() -> dict:
    return version_payload()


@app.post("/v1/analyze-file", response_model=AnalyzeResponse)
async def analyze_file(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    text, notes = await asyncio.to_thread(parse_document, file.filename or "document.txt", content)
    return {
        "success": True,
        "text": text,
        "document_kind": detect_document_kind(text),
        "file_format": detect_file_format(file.filename or "document.txt", content),
        "structure_notes": notes,
        "active_skills": ACTIVE_SKILLS,
        "characters": len(text),
    }


@app.post("/v1/translate", response_model=TranslateResponse)
async def translate(request: TranslateRequest) -> dict:
    try:
        return await translate_text(
            text=request.text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            notes=request.notes,
            document_kind=request.document_kind,
            structure_notes=request.structure_notes,
        )
    except Exception as error:
        raise provider_http_error(error) from error


@app.post("/v1/accounting-chat")
async def accounting_chat(request: AccountingChatRequest) -> dict:
    request_id = uuid.uuid4().hex[:12]
    started_at = time.perf_counter()
    message = request.message.strip()
    context = (request.context or "").strip()
    language = request.language or "francais"
    context_block = context[:18000]
    query_intent = classify_query_intent(message, context_block)
    prefer_golden_kb = should_prefer_golden_kb(query_intent)
    answer_style = preferred_answer_style(query_intent, prefer_golden_kb)
    legal_query = f"{message}\n{context_block}"
    legal_domain = infer_query_domain(legal_query)
    commissariat_fastpath = fastpath_commissariat_texts_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if commissariat_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": commissariat_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": commissariat_fastpath.get("preferred_source"),
                "response_style": commissariat_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(commissariat_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": commissariat_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            commissariat_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=commissariat_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=commissariat_fastpath.get("model"),
        )
    loi_finances_tva_fastpath = fastpath_loi_finances_tva_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if loi_finances_tva_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": loi_finances_tva_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": loi_finances_tva_fastpath.get("preferred_source"),
                "response_style": loi_finances_tva_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(loi_finances_tva_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": loi_finances_tva_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            loi_finances_tva_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=loi_finances_tva_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=loi_finances_tva_fastpath.get("model"),
        )
    legal_hierarchy_fastpath = fastpath_legal_hierarchy_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if legal_hierarchy_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": legal_hierarchy_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": legal_hierarchy_fastpath.get("preferred_source"),
                "response_style": legal_hierarchy_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(legal_hierarchy_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": legal_hierarchy_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            legal_hierarchy_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=legal_hierarchy_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=legal_hierarchy_fastpath.get("model"),
        )
    fiscal_sources_fastpath = fastpath_fiscal_sources_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if fiscal_sources_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": fiscal_sources_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": fiscal_sources_fastpath.get("preferred_source"),
                "response_style": fiscal_sources_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(fiscal_sources_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": fiscal_sources_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            fiscal_sources_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=fiscal_sources_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=fiscal_sources_fastpath.get("model"),
        )
    fiscal_code_comparison_fastpath = fastpath_fiscal_code_comparison_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if fiscal_code_comparison_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": fiscal_code_comparison_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": fiscal_code_comparison_fastpath.get("preferred_source"),
                "response_style": fiscal_code_comparison_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(fiscal_code_comparison_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": fiscal_code_comparison_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            fiscal_code_comparison_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=fiscal_code_comparison_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=fiscal_code_comparison_fastpath.get("model"),
        )
    fiscal_framework_fastpath = fastpath_general_fiscal_framework_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if fiscal_framework_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": query_intent,
                "legal_domain": legal_domain,
                "preferred_source": fiscal_framework_fastpath.get("preferred_source"),
                "response_style": fiscal_framework_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(fiscal_framework_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": fiscal_framework_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            fiscal_framework_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=fiscal_framework_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=fiscal_framework_fastpath.get("model"),
        )
    tva_overview_fastpath = fastpath_tva_overview_answer(
        message=message,
        intent=query_intent,
        legal_domain=legal_domain,
    )
    if tva_overview_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": query_intent,
                "legal_domain": legal_domain,
                "preferred_source": tva_overview_fastpath.get("preferred_source"),
                "response_style": tva_overview_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(tva_overview_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": tva_overview_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            tva_overview_fastpath,
            request,
            workflow="fastpath",
            case_analysis_enabled=False,
            retrieval_domains=[legal_domain],
            selected_sources=tva_overview_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=tva_overview_fastpath.get("model"),
        )
    legal_sources = retrieve_legal_context(legal_query, limit=legal_source_limit(query_intent, prefer_golden_kb))
    legal_sources = case_analysis_sources(message, legal_sources)
    golden_kb_hits = retrieve_golden_kb(message, limit=3) if prefer_golden_kb else retrieve_golden_kb(message, limit=2)
    golden_kb_refs = [
        {
            "concept": row.get("concept"),
            "domain": row.get("domain"),
            "confidence": row.get("confidence_label"),
        }
        for row in golden_kb_hits[:5]
    ]
    case_analysis_fastpath = fastpath_case_analysis_answer(
        message=message,
        intent=query_intent,
        legal_domain=legal_domain,
        legal_sources=legal_sources,
    )
    if case_analysis_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": case_analysis_fastpath.get("intent"),
                "legal_domain": case_analysis_fastpath.get("legal_domain"),
                "preferred_source": case_analysis_fastpath.get("preferred_source"),
                "response_style": case_analysis_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": golden_kb_refs,
                "retrieved_legal_refs": accounting_log_doc_refs(case_analysis_fastpath.get("sources") or []),
                "result": "case_analysis_fastpath",
                "model": case_analysis_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            case_analysis_fastpath,
            request,
            workflow="case_analysis_fastpath",
            case_analysis_enabled=True,
            retrieval_domains=[case_analysis_fastpath.get("legal_domain") or legal_domain],
            selected_sources=case_analysis_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=case_analysis_fastpath.get("model"),
        )
    if query_intent == "professional_formality":
        seeded_formality_query = f"{message} inscription personne physique ordre professionnel attestation radiation suspension stagiaire"
        formality_hits = [
            row
            for row in retrieve_golden_kb(seeded_formality_query, limit=5)
            if row.get("domain") == "reglementation_professionnelle"
        ]
        if formality_hits:
            golden_kb_hits = formality_hits[:3]
    if answer_style == "concept_brief" and golden_kb_hits:
        fastpath = fastpath_concept_answer(
            message=message,
            intent=query_intent,
            legal_domain=legal_domain,
            golden_kb_hits=golden_kb_hits,
            legal_sources=legal_sources,
        )
        if fastpath:
            append_accounting_chat_log(
                {
                    "request_id": request_id,
                    "kind": "accounting_chat",
                    "message": message[:500],
                    "language": language,
                    "history_count": len(request.history or []),
                    "intent": query_intent,
                    "legal_domain": legal_domain,
                    "preferred_source": fastpath.get("preferred_source"),
                    "response_style": fastpath.get("response_style"),
                    "provider_attempts": [],
                    "golden_kb_refs": golden_kb_refs,
                    "retrieved_legal_refs": accounting_log_doc_refs(legal_sources),
                    "result": "fastpath",
                    "model": fastpath.get("model"),
                    "fallback_used": False,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
                }
            )
            return finalize_accounting_response(
                fastpath,
                request,
                workflow="golden_kb_fastpath",
                case_analysis_enabled=False,
                retrieval_domains=[legal_domain],
                selected_sources=legal_sources,
                fallback_used=False,
                generator_path=fastpath.get("model"),
            )
    glossary_hits = []
    if should_use_financial_glossary(message):
        glossary_hits = [row for row in search_financial_glossary(message, limit=5) if row.get("score", 0) >= 25]
    legal_context = build_legal_context_block(legal_sources, query_intent, answer_style)
    glossary_context = "\n".join(
        f"- FR: {row['fr']} | EN: {row['en']} | AR: {row['ar']} | page {row['page']}"
        for row in glossary_hits
    )
    golden_kb_context = "\n\n".join(
        "\n".join([
            f"Concept: {row['concept']} | domaine: {row.get('domain') or 'non precise'} | confiance: {row.get('confidence_label', 'high')} | revue: {row.get('last_reviewed') or 'non precisee'}",
            f"Definition canonique: {row['canonical_definition']}",
            f"Base legale/source d ancrage: {', '.join(row.get('legal_basis', [])) or 'non precisee'}",
            f"Concepts lies: {', '.join(row.get('related_concepts', [])) or 'aucun'}",
            f"Erreurs frequentes: {' ; '.join(row.get('common_mistakes', [])) or 'aucune'}",
        ])
        for row in golden_kb_hits
    )
    history_messages = []
    for item in request.history[-10:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = clean_translation_output(str(item.get("content") or "")).strip()
        if content:
            history_messages.append({"role": role, "content": content[:4000]})
    system_prompt = "\n".join([
        "Tu es un assistant IA conversationnel de haut niveau, comparable a ChatGPT ou Claude, mais specialise pour experts-comptables, commissaires aux comptes, auditeurs, fiscalistes, juristes fiscaux et cabinets comptables.",
        "Tu peux discuter librement avec l'utilisateur et l'aider sur: comptabilite generale, fiscalite tunisienne et francophone, lois de finances, TVA, IRPP, IS, retenue a la source, droits d'enregistrement, paie, CNSS, audit, commissariat aux comptes, controle interne, lettrage, rapprochements, bilan, grand livre, declarations, procedures cabinet, analyse de pieces, redaction de notes, consolidation, parties liees, regroupements d'entreprises, droit commercial, code des obligations et des contrats, code des societes commerciales, formalites d'inscription professionnelles, normes sectorielles bancaires, OPCVM, assurance, reassurance, takaful, retakaful, micro-credit, structures sportives privees, contrats de location, comptabilite simplifiee et organismes sans but lucratif, et traduction professionnelle quand elle est demandee.",
        "Tu reponds comme un expert de cabinet: clair, direct, pratique, structure, avec raisonnement professionnel et points de controle.",
        "Tu peux aussi repondre a des questions generales si elles aident le travail du cabinet, mais tu ramene toujours la valeur vers l'expertise comptable, fiscale, juridique ou organisationnelle.",
        "Tu verifies les montants, dates, taxes, debits/credits, tiers, periodes et hypotheses avant de conclure.",
        "Si une information manque, dis exactement ce qu'il faut demander au client.",
        "Pour les lois, ne pretend jamais qu'une regle est certaine ou a jour sans source/date. Donne la position probable, les reserves et ce qu'il faut verifier dans le texte officiel.",
        "Interdiction stricte: n'affirme jamais une mise a jour posterieure aux sources fournies, un taux, un seuil, une obligation electronique, une reforme ou une loi de finances recente si cette information n'apparait pas explicitement dans les sources recuperees. N'invente jamais des exemples du type 'eventuelle hausse en 2024'.",
        "Les corpus internes actuellement charges contiennent surtout des textes consolides autour de 2014-2022, puis quelques guides, circulaires professionnelles, formulaires de stage ou d'inscription et rapports institutionnels plus recents. Ne traite jamais un rapport moral, un guide pratique ou un formulaire comme une regle de droit contraignante au meme niveau qu'un code ou qu'une loi.",
        "Pour une reponse client finale, signale qu'il faut verifier les lois de finances, normes modificatives, interpretations ulterieures, circulaires, et textes sectoriels applicables, notamment en matiere bancaire, OPCVM, assurance, reassurance, takaful, micro-credit, OSBL, consolidation et reglementation professionnelle.",
        "Si des sources internes sont fournies, utilise-les avant ta connaissance generale et cite le titre/page dans la reponse quand c'est pertinent.",
        "Si une ou plusieurs entrees de Golden Knowledge Base sont fournies, traite-les comme couche canonique prioritaire pour les questions de definition, d'acronyme, de concept, de distinction simple ou de comparaison de notions proches.",
        "La Golden Knowledge Base est une couche redactionnelle haute confiance ancree sur les sources indexees; elle n'autorise pas a inventer des regles nouvelles ni a depasser les textes d'ancrage cites.",
        "Pour une question pratique, de calcul, de traitement comptable detaille, de base legale, de procedure, de contentieux ou d'application a un cas, la Golden Knowledge Base reste secondaire: la priorite revient alors au corpus legal/comptable recupere.",
        "Quand tu cites un texte, utilise son intitule juridique ou un intitule professionnel clair. Ne presente jamais un nom de fichier PDF, un identifiant interne ou une etiquette technique comme s'il s'agissait du titre officiel du texte.",
        "Le millesime d'un recueil documentaire indique sa date de mise a jour; il ne fait pas partie du nom de la loi ou du code sauf si le texte lui-meme le prevoit.",
        "Si un glossaire terminologique trilingue interne est fourni, utilise-le seulement comme aide terminologique secondaire pour les equivalences de termes FR/EN/AR. Ne le traite jamais comme une source normative de droit positif.",
        "Pour la Tunisie, prefere la terminologie locale: TVA, IRPP, IS, retenue a la source, droit de timbre, CNSS, matricule fiscal, regime reel/forfaitaire, liasse fiscale.",
        "Interdiction stricte supplementaire pour la fiscalite tunisienne: n'invente jamais un 'Code general des impots (CGI)' tunisien ni une structure fictive en Livres I/II/III/IV/V/VI si cette structure n'apparait pas explicitement dans les sources internes recuperees.",
        "Si l'utilisateur demande les principales lois fiscales tunisiennes, cite sobrement les textes recuperes tels qu'ils existent dans les sources: Code de l IRPP et de l IS, Code TVA, Code des droits et procedures fiscaux, Code des droits d enregistrement et du timbre, Code de la fiscalite locale, loi de finances, et notes generales si elles sont pertinentes.",
        "Si l'utilisateur demande les lois de TVA en Tunisie generalement, reponds directement que la TVA est principalement regie par le Code de la taxe sur la valeur ajoutee, complete par ses textes d'application, les lois de finances modificatives et le Code des droits et procedures fiscaux pour les aspects proceduraux. Ne donne pas de taux ou de seuil sans source explicite.",
        "Pour les reponses juridiques ou fiscales importantes, ajoute a la fin une courte section 'Sources utilisees' listant uniquement les titres/pages effectivement utilises dans la reponse.",
        "Le retrieval reste entierement interne. N'ecris jamais au client 'selon les documents indexes', 'dans le corpus', 'sources recuperees', 'la bonne reponse consiste a' ou toute autre description du fonctionnement de la base. Donne directement la conclusion professionnelle, puis cite les sources utilisees.",
        "Ne reponds pas comme un traducteur sauf si l'utilisateur demande une traduction. Par defaut, agis comme un assistant IA expert-comptable.",
        "Si l'utilisateur demande une presentation generale d'un sujet juridique ou fiscal, expose directement le cadre applicable et integre toute reserve de date dans une phrase professionnelle concise. Ne decris jamais la methode de recherche.",
        "Quand une reponse s'appuie d'abord sur la Golden Knowledge Base, conserve un ton de cabinet: definition nette, reserve utile, et distinction claire entre notion de base et application pratique.",
        "Respecte strictement le style de reponse demande dans le prompt utilisateur.",
        "Si le style demande est 'concept_brief', structure le champ answer avec exactement ces intertitres markdown dans cet ordre: 'Definition', 'Base legale', 'Points de vigilance', 'Sources utilisees'.",
        "Si le style demande est 'concept_brief', chaque section doit etre concise, utile au cabinet, et les sources citees doivent venir uniquement des sources effectivement fournies dans le contexte.",
        "Si le style demande est 'practical_analysis', structure le champ answer avec exactement ces intertitres markdown dans cet ordre: 'Reponse', 'Application pratique', 'Points de vigilance', 'Sources utilisees'.",
        "Pour un cas pratique, ne donne pas une definition generale. Commence par qualifier les faits, identifie les questions juridiques/comptables, applique les sources recuperees, puis liste les controles et pieces a demander.",
        "Pour un cas pratique multi-domaines, separe clairement le traitement comptable, fiscal, juridique et audit lorsque c'est utile. Ne cite pas une source IRPP/IS pour justifier une regle de TVA, ni une source d'audit pour justifier un traitement comptable.",
        "Si les sources recuperees ne contiennent pas l'article exact, formule la conclusion comme une verification a effectuer et non comme une certitude.",
        "Si le style demande est 'flexible_expert', tu peux garder une structure libre mais professionnelle; si des sources sont pertinentes, termine par 'Sources utilisees'.",
        "Style: professionnel, sans emoji, sans formule marketing, avec des etapes nettes et directement exploitables.",
        "Le champ 'answer' doit contenir uniquement la reponse principale. Ne colle jamais dedans les sections Assumptions, Next steps ou Warnings.",
        "Retourne uniquement un JSON valide avec exactement ces cles: answer, assumptions, next_steps, warnings.",
    ])
    user_prompt = "\n\n".join([
        f"Langue de reponse: {language}",
        f"Intent detecte cote orchestration: {query_intent}",
        f"Source preferentielle: {'golden_kb' if prefer_golden_kb else 'legal_corpus'}",
        f"Style de reponse attendu: {answer_style}",
        f"Domaine detecte cote retrieval: {legal_domain}",
        golden_kb_context and f"Golden Knowledge Base recuperee:\n{golden_kb_context}",
        legal_context and f"Sources internes recuperees dans le corpus fiscal/comptable tunisien:\n{legal_context}",
        glossary_context and f"Glossaire terminologique trilingue recupere:\n{glossary_context}",
        context_block and f"Contexte/document fourni:\n{context_block}",
        f"Question du cabinet:\n{message}",
    ]).strip()
    messages = [
        {"role": "system", "content": system_prompt},
        *history_messages,
        {"role": "user", "content": user_prompt},
    ]
    routes = prioritize_accounting_chat_routes(
        prioritized_translation_routes(f"{message}\n{context_block}", "expert-comptable assistant chat"),
        answer_style,
    )
    max_output_tokens = min(config.LLM_MAX_TOKENS, accounting_chat_max_tokens(answer_style, query_intent))
    last_error: Exception | None = None
    provider_attempts: list[dict] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(config.LLM_PROVIDER_TIMEOUT, connect=8.0)) as client:
        for route in routes:
            body = provider_body(route, messages, max_output_tokens, json_mode=True)
            try:
                response = await client.post(
                    route["endpoint"],
                    headers=route["headers"],
                    json=body,
                    timeout=provider_timeout(route, message, "expert-comptable assistant chat"),
                )
                if response.status_code == 400 and route.get("api_style") != "gemini":
                    body.pop("response_format", None)
                    response = await client.post(
                        route["endpoint"],
                        headers=route["headers"],
                        json=body,
                        timeout=provider_timeout(route, message, "expert-comptable assistant chat"),
                    )
                response.raise_for_status()
                provider_attempts.append(
                    {
                        "provider": route["provider"],
                        "model": route["model"],
                        "status": "ok",
                        "http_status": response.status_code,
                    }
                )
                parsed = extract_json(provider_content(route, response.json()))
                answer, assumptions, next_steps, warnings = normalize_chat_payload(parsed, answer_style)
                if not answer:
                    raise RuntimeError("Model returned an empty accounting answer.")
                if not answer_has_required_sections(answer, answer_style):
                    answer = build_structured_sections_from_answer(answer, answer_style, golden_kb_hits, legal_sources)
                if (
                    fiscal_answer_needs_repair(answer, legal_domain)
                    or fiscal_overview_answer_needs_repair(answer, message, legal_domain, query_intent)
                    or answer_needs_professional_repair(answer)
                ):
                    repair_messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "Reecris ta reponse en corrigeant une erreur juridique: "
                                "n'invente pas de 'Code general des impots (CGI)' tunisien, "
                                "n'invente pas une structure en Livres I/II/III/IV/V/VI, "
                                "cite uniquement les textes tunisiens effectivement recuperes dans les sources internes, "
                                "et pour une question generale sur la TVA, reste au niveau des textes de reference et des reserves de verification "
                                "sans affirmer par defaut des taux, seuils, periodicites ou regimes speciaux non explicitement recuperes. "
                                "N'ecris jamais 'we need to answer', ne montre jamais de JSON brut, "
                                "et ne decris jamais les sources internes, le corpus, le fallback ou le moteur conversationnel."
                            ),
                        },
                    ]
                    repair_body = provider_body(route, repair_messages, max_output_tokens, json_mode=True)
                    repair_response = await client.post(
                        route["endpoint"],
                        headers=route["headers"],
                        json=repair_body,
                        timeout=provider_timeout(route, message, "expert-comptable assistant chat"),
                    )
                    if repair_response.status_code == 400 and route.get("api_style") != "gemini":
                        repair_body.pop("response_format", None)
                        repair_response = await client.post(
                            route["endpoint"],
                            headers=route["headers"],
                            json=repair_body,
                            timeout=provider_timeout(route, message, "expert-comptable assistant chat"),
                        )
                    repair_response.raise_for_status()
                    repair_parsed = extract_json(provider_content(route, repair_response.json()))
                    answer, assumptions, next_steps, warnings = normalize_chat_payload(repair_parsed, answer_style)
                    if not answer:
                        raise RuntimeError("Accounting answer failed fiscal legal validation.")
                    if not answer_has_required_sections(answer, answer_style):
                        answer = build_structured_sections_from_answer(answer, answer_style, golden_kb_hits, legal_sources)
                    if (
                        fiscal_answer_needs_repair(answer, legal_domain)
                        or fiscal_overview_answer_needs_repair(answer, message, legal_domain, query_intent)
                        or answer_needs_professional_repair(answer)
                    ):
                        raise RuntimeError("Accounting answer failed fiscal legal validation.")
                result = {
                    "success": True,
                    "answer": answer,
                    "assumptions": assumptions,
                    "next_steps": next_steps,
                    "warnings": warnings,
                    "intent": query_intent,
                    "preferred_source": "golden_kb" if prefer_golden_kb else "legal_corpus",
                    "response_style": answer_style,
                    "golden_kb_hits": golden_kb_hits,
                    "sources": legal_sources,
                    "model": f"{route['provider']}/{route['model']}",
                }
                append_accounting_chat_log(
                    {
                        "request_id": request_id,
                        "kind": "accounting_chat",
                        "message": message[:500],
                        "language": language,
                        "history_count": len(request.history or []),
                        "intent": query_intent,
                        "legal_domain": legal_domain,
                        "preferred_source": result.get("preferred_source"),
                        "response_style": result.get("response_style"),
                        "provider_attempts": provider_attempts,
                        "golden_kb_refs": golden_kb_refs,
                        "retrieved_legal_refs": accounting_log_doc_refs(legal_sources),
                        "result": "provider_success",
                        "model": result.get("model"),
                        "fallback_used": False,
                        "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
                    }
                )
                return finalize_accounting_response(
                    result,
                    request,
                    workflow="llm_provider",
                    case_analysis_enabled=True,
                    retrieval_domains=[legal_domain],
                    selected_sources=legal_sources,
                    fallback_used=False,
                    generator_path=result.get("model"),
                )
            except Exception as error:
                provider_attempts.append(
                    {
                        "provider": route["provider"],
                        "model": route["model"],
                        "status": "error",
                        "error_type": type(error).__name__,
                        "error": clean_translation_output(str(error))[:280],
                    }
                )
                last_error = error
                continue
    if isinstance(last_error, RuntimeError):
        fallback = fallback_accounting_answer(
            message=message,
            intent=query_intent,
            answer_style=answer_style,
            legal_domain=legal_domain,
            golden_kb_hits=golden_kb_hits,
            legal_sources=case_analysis_sources(message, legal_sources),
        )
        if fallback:
            append_accounting_chat_log(
                {
                    "request_id": request_id,
                    "kind": "accounting_chat",
                    "message": message[:500],
                    "language": language,
                    "history_count": len(request.history or []),
                    "intent": query_intent,
                    "legal_domain": legal_domain,
                    "preferred_source": fallback.get("preferred_source"),
                    "response_style": fallback.get("response_style"),
                    "provider_attempts": provider_attempts,
                    "golden_kb_refs": golden_kb_refs,
                    "retrieved_legal_refs": accounting_log_doc_refs(fallback.get("sources") or []),
                    "result": "fallback_after_validation_failure",
                    "model": fallback.get("model"),
                    "fallback_used": True,
                    "last_error_type": type(last_error).__name__,
                    "last_error": clean_translation_output(str(last_error))[:280],
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
                }
            )
            return finalize_accounting_response(
                fallback,
                request,
                workflow="fallback_after_validation_failure",
                case_analysis_enabled=True,
                retrieval_domains=[legal_domain],
                selected_sources=fallback.get("sources") or [],
                fallback_used=True,
                generator_path=fallback.get("model"),
            )
    if is_rate_limit_error(last_error) or is_credit_error(last_error):
        fallback = fallback_accounting_answer(
            message=message,
            intent=query_intent,
            answer_style=answer_style,
            legal_domain=legal_domain,
            golden_kb_hits=golden_kb_hits,
            legal_sources=legal_sources,
        )
        if fallback:
            append_accounting_chat_log(
                {
                    "request_id": request_id,
                    "kind": "accounting_chat",
                    "message": message[:500],
                    "language": language,
                    "history_count": len(request.history or []),
                    "intent": query_intent,
                    "legal_domain": legal_domain,
                    "preferred_source": fallback.get("preferred_source"),
                    "response_style": fallback.get("response_style"),
                    "provider_attempts": provider_attempts,
                    "golden_kb_refs": golden_kb_refs,
                    "retrieved_legal_refs": accounting_log_doc_refs(legal_sources),
                    "result": "fallback_after_provider_failure",
                    "model": fallback.get("model"),
                    "fallback_used": True,
                    "last_error_type": type(last_error).__name__ if last_error else None,
                    "last_error": clean_translation_output(str(last_error))[:280] if last_error else None,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
                }
            )
            return finalize_accounting_response(
                fallback,
                request,
                workflow="fallback_after_provider_failure",
                case_analysis_enabled=True,
                retrieval_domains=[legal_domain],
                selected_sources=fallback.get("sources") or [],
                fallback_used=True,
                generator_path=fallback.get("model"),
            )
    if is_rate_limit_error(last_error):
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": query_intent,
                "legal_domain": legal_domain,
                "preferred_source": "golden_kb" if prefer_golden_kb else "legal_corpus",
                "response_style": answer_style,
                "provider_attempts": provider_attempts,
                "golden_kb_refs": golden_kb_refs,
                "retrieved_legal_refs": accounting_log_doc_refs(legal_sources),
                "result": "provider_failure",
                "model": None,
                "fallback_used": False,
                "last_error_type": type(last_error).__name__ if last_error else None,
                "last_error": clean_translation_output(str(last_error))[:280] if last_error else None,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        raise provider_http_error(ProviderRateLimitError(friendly_provider_error(last_error)))
    if is_credit_error(last_error):
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": query_intent,
                "legal_domain": legal_domain,
                "preferred_source": "golden_kb" if prefer_golden_kb else "legal_corpus",
                "response_style": answer_style,
                "provider_attempts": provider_attempts,
                "golden_kb_refs": golden_kb_refs,
                "retrieved_legal_refs": accounting_log_doc_refs(legal_sources),
                "result": "provider_failure",
                "model": None,
                "fallback_used": False,
                "last_error_type": type(last_error).__name__ if last_error else None,
                "last_error": clean_translation_output(str(last_error))[:280] if last_error else None,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        raise provider_http_error(ProviderCreditError(friendly_provider_error(last_error)))
    append_accounting_chat_log(
        {
            "request_id": request_id,
            "kind": "accounting_chat",
            "message": message[:500],
            "language": language,
            "history_count": len(request.history or []),
            "intent": query_intent,
            "legal_domain": legal_domain,
            "preferred_source": "golden_kb" if prefer_golden_kb else "legal_corpus",
            "response_style": answer_style,
            "provider_attempts": provider_attempts,
            "golden_kb_refs": golden_kb_refs,
            "retrieved_legal_refs": accounting_log_doc_refs(legal_sources),
            "result": "provider_failure",
            "model": None,
            "fallback_used": False,
            "last_error_type": type(last_error).__name__ if last_error else None,
            "last_error": clean_translation_output(str(last_error))[:280] if last_error else None,
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
        }
    )
    raise provider_http_error(last_error or RuntimeError("Aucun fournisseur IA disponible."))


@app.post("/v1/translate-file", response_model=TranslateResponse)
async def translate_file(
    file: UploadFile = File(...),
    source_lang: str = Form("auto"),
    target_lang: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict:
    content = await file.read()
    text, structure_notes = await asyncio.to_thread(parse_document, file.filename or "document.txt", content)
    try:
        return await translate_text(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            notes=notes,
            document_kind=detect_document_kind(text),
            structure_notes=structure_notes,
        )
    except Exception as error:
        raise provider_http_error(error) from error


@app.post("/v1/translation-jobs")
async def create_translation_job(
    file: UploadFile = File(...),
    source_lang: str = Form("auto"),
    target_lang: str | None = Form(None),
    notes: str | None = Form(None),
    output_format: str = Form("same"),
) -> dict:
    content = await file.read()
    job_id = str(uuid.uuid4())
    filename = file.filename or "document.txt"
    write_job(job_id, {
        "status": "queued",
        "progress": 1,
        "message": "Document ajouté à la file de traduction.",
        "filename": filename,
    })
    asyncio.create_task(run_document_job(job_id, content, filename, source_lang, target_lang, notes, output_format))
    return {
        "success": True,
        "job_id": job_id,
        "status": "queued",
        "progress": 1,
        "status_url": f"/v1/translation-jobs/{job_id}",
        "download_url": f"/v1/translation-jobs/{job_id}/download",
    }


@app.get("/v1/translation-jobs/{job_id}")
async def get_translation_job(job_id: str) -> dict:
    return read_job(job_id)


@app.get("/v1/translation-jobs/{job_id}/download")
async def download_translation_job(job_id: str) -> FileResponse:
    job = read_job(job_id)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail=job.get("message") or "Document pas encore prêt.")
    result_path = job_path(job_id, "bin")
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="Fichier traduit introuvable.")
    return FileResponse(
        result_path,
        media_type=job.get("media_type") or "application/octet-stream",
        filename=job.get("output_filename") or "translated-document",
    )


@app.post("/v1/render-document")
async def render_translated_document(
    request: TranslateRequest,
    output_format: str = "docx",
) -> StreamingResponse:
    try:
        translated = await translate_text(
            text=request.text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            notes=request.notes,
            document_kind=request.document_kind,
            structure_notes=request.structure_notes,
        )
        content, media_type, extension = render_document(
            translated["translation"],
            output_format,
            "Translated document",
        )
        return StreamingResponse(
            io.BytesIO(content),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="translated-document.{extension}"'},
        )
    except Exception as error:
        raise provider_http_error(error) from error


@app.post("/v1/translate-file-document")
async def translate_file_document(
    file: UploadFile = File(...),
    source_lang: str = Form("auto"),
    target_lang: str | None = Form(None),
    notes: str | None = Form(None),
    output_format: str = Form("same"),
) -> StreamingResponse:
    content = await file.read()
    try:
        content_out, media_type, output_filename = await build_translated_document(
            content=content,
            filename=file.filename or "document.txt",
            source_lang=source_lang,
            target_lang=target_lang,
            notes=notes,
            output_format=output_format,
        )
        return StreamingResponse(
            io.BytesIO(content_out),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{output_filename}"'},
        )
    except Exception as error:
        raise provider_http_error(error) from error


async def build_translated_document(
    content: bytes,
    filename: str,
    source_lang: str = "auto",
    target_lang: str | None = None,
    notes: str | None = None,
    output_format: str = "same",
) -> tuple[bytes, str, str]:
    file_format = detect_file_format(filename, content)
    if file_format == "pdf" and output_format in {"same", "pdf"}:
        text = ""
        structure_notes = "PDF visual translation: original pages are preserved as backgrounds; OCR is performed once during visual overlay."
        detected_kind = "presentation / visual PDF document"
    else:
        text, structure_notes = await asyncio.to_thread(parse_document, filename, content)
        detected_kind = detect_document_kind(text)

    async def translate_native_segments(segments: list[str], context: str) -> list[str]:
        async def translate_one_segment(text: str) -> str:
            """Translate a single segment as its own request. The single-segment
            path recovers even if markers are dropped."""
            payload = build_segment_payload([text])
            segment_notes = "\n".join(
                item
                for item in [
                    notes,
                    "Mode document natif: traduire uniquement le texte entre les marqueurs JT_SEG.",
                    "Conserver exactement chaque marqueur de debut et de fin; ne pas les traduire.",
                    "Ne pas fusionner, supprimer, renumeroter ou resumer les segments.",
                ]
                if item
            )
            result = await translate_text(
                text=payload,
                source_lang=source_lang,
                target_lang=target_lang,
                notes=segment_notes,
                document_kind=detected_kind,
                structure_notes=f"{structure_notes}\n{context}",
                use_llm_classifier=False,
            )
            parsed = parse_segmented_translation(result["translation"], 1)
            if parsed is None:
                parsed = split_by_segment_markers(result["translation"], 1)
            if parsed is None:
                parsed = [SEGMENT_LOOSE_RE.sub("", SEGMENT_ANY_RE.sub("", result["translation"])).strip()]
            return parsed[0]

        translated_segments = [""] * len(segments)
        cache: dict[str, str] = {}
        for batch in segment_batches(segments):
            batch_indexes = [index for index, value in batch if value not in cache]
            batch_values = [value for _index, value in batch if value not in cache]
            if not batch_values:
                for index, value in batch:
                    translated_segments[index] = cache[value]
                continue

            payload = build_segment_payload(batch_values)
            segment_notes = "\n".join(
                item
                for item in [
                    notes,
                    "Mode document natif: traduire uniquement le texte entre les marqueurs JT_SEG.",
                    "Conserver exactement chaque marqueur de debut et de fin; ne pas les traduire.",
                    "Ne pas fusionner, supprimer, renumeroter ou resumer les segments.",
                ]
                if item
            )
            result = await translate_text(
                text=payload,
                source_lang=source_lang,
                target_lang=target_lang,
                notes=segment_notes,
                document_kind=detected_kind,
                structure_notes=f"{structure_notes}\n{context}",
                use_llm_classifier=False,
            )
            parsed = parse_segmented_translation(result["translation"], len(batch_values))
            if parsed is None and len(batch_values) == 1:
                parsed = [SEGMENT_LOOSE_RE.sub("", SEGMENT_ANY_RE.sub("", result["translation"])).strip()]
            if parsed is None:
                # Positional fallback: same count, same order, markers may be corrupted.
                parsed = split_by_segment_markers(result["translation"], len(batch_values))
            if parsed is None and len(batch_values) > 1:
                # Final fallback: translate each segment individually so a single
                # flaky model response cannot sink the whole document.
                parsed = []
                for value in batch_values:
                    translated = await translate_one_segment(value)
                    parsed.append(translated)
            if parsed is None:
                raise ValueError("The model did not preserve native document segment markers.")
            # Strip any residual markers (including malformed ones) as a safety net
            # before writing into the document, so leaked markers never reach the file.
            parsed = [SEGMENT_LOOSE_RE.sub("", SEGMENT_ANY_RE.sub("", item)).strip() for item in parsed]
            for index, original, translated in zip(batch_indexes, batch_values, parsed):
                cache[original] = translated
                translated_segments[index] = translated
            for index, value in batch:
                translated_segments[index] = cache[value]
        return translated_segments

    if output_format == "same":
        if file_format == "pdf":
            output_format = "pdf"
        elif file_format == "docx":
            output_format = "docx"
        elif file_format == "pptx":
            output_format = "pptx"
        elif file_format == "xlsx":
            output_format = "xlsx"
        elif file_format == "html":
            output_format = "html"
        else:
            output_format = "txt"

    native_result = None
    if file_format == "docx" and output_format == "docx":
        native_result = await translate_docx_native(content, translate_native_segments)
    elif file_format == "pptx" and output_format == "pptx":
        native_result = await translate_pptx_native(content, translate_native_segments)
    elif file_format == "xlsx" and output_format == "xlsx":
        native_result = await translate_xlsx_native(content, translate_native_segments)
    elif file_format == "pdf" and output_format == "pdf":
        native_result = await translate_pdf_visual_native(content, translate_native_segments)

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.rsplit(".", 1)[0]).strip("-") or "document"
    if native_result is not None:
        content_out, media_type, extension, _changed = native_result
        return content_out, media_type, f"{safe_name}-translated.{extension}"

    translated = await translate_text(
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        notes=notes,
        document_kind=detected_kind,
        structure_notes=structure_notes,
    )
    content_out, media_type, extension = render_document(
        translated["translation"],
        output_format,
        "Translated document",
    )
    return content_out, media_type, f"{safe_name}-translated.{extension}"
