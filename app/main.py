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
CLIENT_SOURCE_TITLES = {
    "code_irpp_is_2011": "Code de l'impôt sur le revenu des personnes physiques et de l'impôt sur les sociétés (IRPP et IS)",
    "tva_droit_consommation": "Ministère des Finances, recueil TVA et droit de consommation, mis à jour au 1er janvier 2026",
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
                "Definition": definition or "Les sources internes permettent d'identifier la notion, mais une verification contextuelle reste utile.",
                "Base legale": base_legale or "Documents internes indexes.",
                "Points de vigilance": points,
                "Sources utilisees": sources_used or "- Base documentaire interne",
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
                "Sources utilisees": sources_used or "- Base documentaire interne",
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

    fallback_preferred_source = "golden_kb" if answer_style == "concept_brief" and golden_kb_hits else "legal_corpus"

    if answer_style == "concept_brief":
        top = golden_kb_hits[0] if golden_kb_hits else None
        definition = top.get("canonical_definition") if top else "Les documents actuellement indexes permettent d'identifier la notion, mais une verification contextuelle reste utile."
        legal_basis = ", ".join(top.get("legal_basis", [])) if top else (
            ", ".join({source.get("title", "") for source in legal_sources[:2] if source.get("title")}) or "Documents internes indexes"
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
        response = "Les sources actuellement recuperees permettent de donner une premiere reponse de cabinet, mais la formulation ci-dessous doit etre relue a la lumiere du texte officiel applicable."
        if legal_sources:
            response = f"Les sources internes recuperées orientent la réponse vers le cadre suivant: {legal_sources[0].get('title', 'source interne')}."
        practical = "- Identifier le texte exact applicable au cas du client.\n- Verifier la date de la version du texte et les modifications ulterieures.\n- Contrôler les pieces, montants, periodes et hypotheses avant conclusion."
        vigilance = "- Reponse de secours generee sans moteur conversationnel complet.\n- Confirmer le texte, la date et les seuils applicables avant usage client."
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
        "assumptions": [
            "Reponse de secours produite a partir du Golden KB et/ou du corpus interne, sans completion par un fournisseur conversationnel externe."
        ],
        "next_steps": [
            "Relancer la question quand un fournisseur IA est disponible pour obtenir une reponse plus developpee si necessaire."
        ],
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
    if legal_domain != "fiscalite":
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
    ]
    return any(re.search(pattern, answer_text, re.I) for pattern in forbidden_patterns)


def is_fiscal_overview_query(message: str, legal_domain: str, intent: str) -> bool:
    if legal_domain != "fiscalite":
        return False
    query = (message or "").lower()
    if intent not in {"general", "legal_basis", "flexible_expert"}:
        return False
    return bool(re.search(
        r"lois? de tva|tva .*g[ée]n[ée]ralement|donnez[- ]moi les lois de tva|"
        r"pr[ée]sentation de la tva|cadre g[ée]n[ée]ral de la tva|r[ée]gime tva g[ée]n[ée]ral",
        query,
        re.I,
    ))


def is_general_fiscal_framework_query(message: str, legal_domain: str) -> bool:
    if legal_domain != "fiscalite":
        return False
    query = (message or "").lower()
    return bool(re.search(
        r"quelles sont les lois de fiscalit|quelles sont les lois fiscal|"
        r"cadre juridique de la fiscalit|cadre fiscal tunisien|principaux textes fiscaux|"
        r"lois de fiscalite en tunisie|lois fiscales en tunisie",
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
    return {
        "ok": True,
        "backend_revision": config.APP_REVISION,
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
    message = request.message.strip()
    context = (request.context or "").strip()
    language = request.language or "francais"
    context_block = context[:18000]
    query_intent = classify_query_intent(message, context_block)
    prefer_golden_kb = should_prefer_golden_kb(query_intent)
    answer_style = preferred_answer_style(query_intent, prefer_golden_kb)
    legal_query = f"{message}\n{context_block}"
    legal_domain = infer_query_domain(legal_query)
    fiscal_framework_fastpath = fastpath_general_fiscal_framework_answer(
        message=message,
        legal_domain=legal_domain,
    )
    if fiscal_framework_fastpath:
        return fiscal_framework_fastpath
    tva_overview_fastpath = fastpath_tva_overview_answer(
        message=message,
        intent=query_intent,
        legal_domain=legal_domain,
    )
    if tva_overview_fastpath:
        return tva_overview_fastpath
    legal_sources = retrieve_legal_context(legal_query, limit=legal_source_limit(query_intent, prefer_golden_kb))
    golden_kb_hits = retrieve_golden_kb(message, limit=3) if prefer_golden_kb else retrieve_golden_kb(message, limit=2)
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
            return fastpath
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
                parsed = extract_json(provider_content(route, response.json()))
                answer, assumptions, next_steps, warnings = normalize_chat_payload(parsed, answer_style)
                if not answer:
                    raise RuntimeError("Model returned an empty accounting answer.")
                if not answer_has_required_sections(answer, answer_style):
                    answer = build_structured_sections_from_answer(answer, answer_style, golden_kb_hits, legal_sources)
                if fiscal_answer_needs_repair(answer, legal_domain) or fiscal_overview_answer_needs_repair(answer, message, legal_domain, query_intent):
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
                                "sans affirmer par defaut des taux, seuils, periodicites ou regimes speciaux non explicitement recuperes."
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
                    if fiscal_answer_needs_repair(answer, legal_domain) or fiscal_overview_answer_needs_repair(answer, message, legal_domain, query_intent):
                        raise RuntimeError("Accounting answer failed fiscal legal validation.")
                return {
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
            except Exception as error:
                last_error = error
                continue
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
            return fallback
    if is_rate_limit_error(last_error):
        raise provider_http_error(ProviderRateLimitError(friendly_provider_error(last_error)))
    if is_credit_error(last_error):
        raise provider_http_error(ProviderCreditError(friendly_provider_error(last_error)))
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
