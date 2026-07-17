from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import config
from .cabinet_coverage import cabinet_coverage_status, detect_cabinet_workflow
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
    # Some browser/console paths can arrive already mojibake-damaged, with
    # accented letters replaced by "?". Keep matching resilient for routing.
    text = text.replace("cr?ance", "creance").replace("soci?t?", "societe")
    text = text.replace("cl?ture", "cloture").replace("r?cup?re", "recupere")
    text = text.replace("d?ductibilit?", "deductibilite").replace("document?es", "documentees")
    text = text.replace("apr?s", "apres").replace("ev?nement", "evenement")
    text = re.sub(r"(?<=[a-z])\?+(?=[a-z])", "e", text)
    text = text.replace("?", "e")
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
        support_level = source.get("support_level")
        if support_level == "direct_passage":
            suffix += " - passage cible"
        elif support_level == "framework_source":
            suffix += " - source-cadre, article precis a verifier"
        elif support_level == "missing_source":
            suffix += " - source manquante a indexer"
        lines.append(f"- {title}{suffix}")
    return "\n".join(lines)


def source_precision_note(sources: list[dict]) -> str:
    if not sources:
        return ""
    direct = [source for source in sources if source.get("support_level") == "direct_passage"]
    framework = [source for source in sources if source.get("support_level") == "framework_source"]
    missing = [source for source in sources if source.get("support_level") == "missing_source"]
    notes: list[str] = []
    if direct:
        notes.append("Niveau d'appui: au moins un passage cible a ete retrouve dans le corpus.")
    if framework:
        notes.append(
            "Limite: certaines conclusions restent a rattacher a l'article exact avant usage client."
        )
    if missing:
        notes.append("Source manquante: un texte indispensable a l'analyse doit etre ajoute au corpus.")
    return "\n".join(f"- {note}" for note in notes)


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


def source_precision_rules(message: str) -> list[dict]:
    query = match_key(message)
    france_case = "france" in query or "francais" in query or "francaise" in query
    treaty_doc_ids = detected_treaty_doc_ids(query)
    if is_cross_border_service_case(query):
        rules = [
            {
                "doc_id": "tva_droit_consommation",
                "terms": [
                    "مــيدان التطــبيق",
                    "البــاب األول",
                    "تخضع العمليات",
                    "العمليات المنجزة",
                    "إسداء الخدمات",
                    "الخدمات",
                    "الفصل1",
                    "الفصل5",
                ],
                "min_matches": 2,
            },
            {
                "doc_id": "procedures_fiscales_2026",
                "terms": ["facture", "declaration", "controle", "recouvrement", "contentieux", "justificatifs"],
                "min_matches": 2,
            },
            {
                "doc_id": "code_irpp_is_2011",
                "terms": ["non resident", "retenue a la source", "redevance", "beneficiaire", "services"],
                "min_matches": 2,
            },
            {
                "doc_id": "loi_finances_2026",
                "terms": ["loi de finances", "2026", "retenue", "tva", "الأداء على القيمة المضافة"],
                "min_matches": 2,
            },
        ]
        if france_case:
            rules.extend([
                {
                    "doc_id": "convention_fiscale_france_tunisie",
                    "terms": ["etablissement stable", "chantier", "montage", "benefices des entreprises", "redevances"],
                    "min_matches": 2,
                },
                {
                    "doc_id": "convention_fiscale_france_tunisie_texte_1973",
                    "terms": ["etablissement stable", "benefices des entreprises", "revenus non commerciaux", "redevances"],
                    "min_matches": 2,
                },
                {
                    "doc_id": "boi_france_tunisie_convention_fiscale_2012",
                    "terms": ["etablissement stable", "benefices industriels et commerciaux", "revenus non commerciaux", "redevances"],
                    "min_matches": 2,
                },
            ])
        elif "vietnam" in query:
            rules.append({
                "doc_id": "convention_fiscale_tunisie_vietnam",
                "terms": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
                "min_matches": 2,
            })
        elif "yemen" in query or "yémen" in query:
            rules.append({
                "doc_id": "convention_fiscale_tunisie_yemen",
                "terms": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
                "min_matches": 2,
            })
        elif treaty_doc_ids:
            rules.extend(treaty_precision_rules(treaty_doc_ids))
        else:
            rules.append({
                "doc_id": "convention_fiscale_applicable",
                "title": "Convention fiscale applicable au pays du client",
                "missing": True,
            })
        return rules
    if is_treaty_overview_query(query) and treaty_doc_ids:
        return treaty_precision_rules(treaty_doc_ids)
    procedure_rules = tax_procedure_precision_rules(query)
    if procedure_rules:
        return procedure_rules
    if is_mixed_dividends_case(query):
        rules = [
            {"doc_id": "code_irpp_is_2011", "terms": ["article 52", "c bis", "revenus distribues", "10%"], "min_matches": 2},
            {"doc_id": "loi_finances_2026", "terms": ["dividende", "retenue", "2026"], "min_matches": 2},
            {"doc_id": "procedures_fiscales_2026", "terms": ["declaration", "reversement", "certificat", "retenue"], "min_matches": 2},
        ]
        if france_case:
            rules.extend([
                {"doc_id": "convention_fiscale_france_tunisie", "terms": ["dividendes", "resident", "etat contractant", "retenue"], "min_matches": 2},
                {"doc_id": "convention_fiscale_france_tunisie_texte_1973", "terms": ["dividendes", "resident", "etat contractant", "impot de distribution"], "min_matches": 2},
                {"doc_id": "boi_france_tunisie_convention_fiscale_2012", "terms": ["dividendes", "revenus de capitaux mobiliers", "retenue", "tunisie"], "min_matches": 2},
            ])
        elif "non resident" in query or "non-resident" in query:
            rules.append({
                "doc_id": "convention_fiscale_applicable",
                "title": "Convention fiscale applicable a l'associe non-resident",
                "missing": True,
            })
        return rules
    if is_revenue_cutoff_tva_case(query):
        return [
            {"doc_id": "nc_03_revenus", "terms": ["revenu", "prestation de services", "realisation", "exercice"], "min_matches": 2},
            {"doc_id": "nc_01_norme_generale", "terms": ["periodicite", "rattachement", "produits", "exercice"], "min_matches": 2},
            {"doc_id": "tva_droit_consommation", "terms": ["الفصل5", "إسداء الخدمات", "الفاتورة", "الأداء على القيمة المضافة"], "min_matches": 2},
            {"doc_id": "code_irpp_is_2011", "terms": ["benefice imposable", "produits", "exercice", "charges"], "min_matches": 2},
        ]
    if is_receivable_subsequent_recovery_case(query):
        return [
            {"doc_id": "nc_01_norme_generale", "terms": ["creances", "depreciation", "provision", "recouvrement"], "min_matches": 2},
            {"doc_id": "ias_37_provisions_passifs_actifs_eventuels", "terms": ["provision", "obligation", "estimation", "creances douteuses"], "min_matches": 2},
            {"doc_id": "ias_10_evenements_post_cloture", "terms": ["evenements posterieurs", "date de cloture", "ajuster", "non ajuster"], "min_matches": 2},
            {"doc_id": "code_irpp_is_2011", "terms": ["creances douteuses", "provision", "deductible", "depreciation"], "min_matches": 2},
        ]
    if is_fixed_asset_component_depreciation_case(query):
        return [
            {"doc_id": "nc_05_immobilisations_corporelles", "terms": ["amortissement", "duree d'utilisation", "composants", "valeur residuelle", "mise en service"], "min_matches": 2},
            {"doc_id": "ias_16_immobilisations_corporelles", "terms": ["amortissement", "pret a etre utilisee", "composant", "parties", "duree d'utilite"], "min_matches": 2},
            {"doc_id": "code_irpp_is_2011", "terms": ["amortissements", "mise en service", "composantes", "date d'acquisition", "exploitation"], "min_matches": 2},
            {"doc_id": "nc_01_norme_generale", "terms": ["immobilisations", "amortissements", "etats financiers", "estimation"], "min_matches": 2},
        ]
    if is_going_concern_case(query):
        return [
            {"doc_id": "cadre_conceptuel_comptable", "terms": ["continuite de l'exploitation", "entreprise poursuit", "avenir previsible"], "min_matches": 2},
            {"doc_id": "nc_01_norme_generale", "terms": ["continuite", "etats financiers", "informations"], "min_matches": 2},
            {"doc_id": "audit_resume_gaida_normes_missions", "terms": ["continuite", "rapport", "opinion", "elements probants"], "min_matches": 2},
            {"doc_id": "audit_resume_acceptation_controle_qualite", "terms": ["planification", "risque", "rapport", "documentation"], "min_matches": 2},
        ]
    if is_related_party_property_case(query):
        return [
            {"doc_id": "nc_39_parties_liees", "terms": ["parties liees", "transactions", "informations", "dirigeants"], "min_matches": 2},
            {"doc_id": "code_societes_commerciales_2022", "terms": ["conventions", "dirigeants", "autorisation", "associes"], "min_matches": 2},
            {"doc_id": "code_irpp_is_2011", "terms": ["acte anormal", "benefice imposable", "reintegre", "avantage"], "min_matches": 2},
            {"doc_id": "audit_resume_gaida_normes_missions", "terms": ["parties liees", "risque", "rapport", "documentation"], "min_matches": 2},
        ]
    if is_cash_consulting_evidence_case(query):
        return [
            {"doc_id": "loi_comptable", "terms": ["pieces justificatives", "enregistrement", "journal", "operation"], "min_matches": 2},
            {"doc_id": "code_irpp_is_2011", "terms": ["charges", "deduction", "benefice imposable", "justifie"], "min_matches": 2},
            {"doc_id": "procedures_fiscales_2026", "terms": ["controle", "justificatifs", "facture", "paiement"], "min_matches": 2},
            {"doc_id": "nc_01_norme_generale", "terms": ["objectivite", "preuves", "transactions", "charges"], "min_matches": 2},
        ]
    if is_accounting_tax_bridge_case(query):
        return [
            {"doc_id": "ias_37_provisions_passifs_actifs_eventuels", "terms": ["provision", "obligation", "estimation", "passif"], "min_matches": 2},
            {"doc_id": "nc_14_eventualites_post_cloture", "terms": ["provision", "eventualite", "probable", "estimation"], "min_matches": 2},
            {"doc_id": "code_irpp_is_2011", "terms": ["provision", "deductible", "benefice imposable", "reintegr"], "min_matches": 2},
            {"doc_id": "ias_12_impots_resultat", "terms": ["impot differe", "difference temporaire", "resultat fiscal"], "min_matches": 2},
        ]
    if ("bofip" in query or "boi-int-cvb" in query or "convention fiscale france tunisie" in query or "convention fiscale france-tunisie" in query) and ("france" in query or "tunisie" in query):
        return [
            {"doc_id": "boi_france_tunisie_convention_fiscale_2012", "terms": ["etablissement stable", "benefices industriels et commerciaux", "revenus non commerciaux", "redevances"], "min_matches": 2},
            {"doc_id": "convention_fiscale_france_tunisie_texte_1973", "terms": ["etablissement stable", "benefices des entreprises", "revenus non commerciaux", "redevances"], "min_matches": 2},
            {"doc_id": "convention_fiscale_france_tunisie", "terms": ["etablissement stable", "benefices des entreprises", "redevances"], "min_matches": 2},
        ]
    if "dividende" in query or "dividendes" in query:
        return [
            {
                "doc_id": "code_irpp_is_2011",
                "terms": ["article 52", "c bis", "revenus distribues", "10%"],
                "min_matches": 2,
            },
            {
                "doc_id": "loi_finances_2026",
                "terms": ["dividende", "retenue a la source", "distribution"],
                "min_matches": 2,
            },
            {
                "doc_id": "procedures_fiscales_2026",
                "terms": ["declaration", "reversement", "retenue", "certificat", "paiement"],
                "min_matches": 2,
            },
        ]
    if ("prestations de services" in query or "prestation informatique" in query) and (
        "france" in query or "client etabli" in query or "client francais" in query
    ):
        return [
            {
                "doc_id": "tva_droit_consommation",
                "terms": [
                    "مــيدان التطــبيق",
                    "البــاب األول",
                    "مــيدان التطــبيق",
                    "العـملـيات الخـاضـعـة",
                    "تخضع العمليات",
                    "العمليات المنجزة",
                    "بالبلاد التونسية",
                    "الأداء على القيمة المضافة",
                    "إسداء الخدمات",
                    "الخدمات",
                    "الفصل1",
                    "الفصل5",
                ],
                "min_matches": 2,
            },
            {
                "doc_id": "procedures_fiscales_2026",
                "terms": ["facture", "declaration", "controle", "recouvrement", "contentieux"],
                "min_matches": 2,
            },
            {
                "doc_id": "loi_finances_2026",
                "terms": ["loi de finances", "2026", "tva", "الأداء على القيمة المضافة"],
                "min_matches": 2,
            },
            {
                "doc_id": "convention_fiscale_france_tunisie_texte_1973",
                "terms": ["etablissement stable", "benefices des entreprises", "revenus non commerciaux", "redevances"],
                "min_matches": 2,
            },
            {
                "doc_id": "boi_france_tunisie_convention_fiscale_2012",
                "terms": ["etablissement stable", "benefices industriels et commerciaux", "revenus non commerciaux", "redevances"],
                "min_matches": 2,
            },
        ]
    if "fraude" in query and ("commissaire aux comptes" in query or "rapport" in query):
        return [
            {
                "doc_id": "audit_resume_gaida_normes_missions",
                "terms": ["fraude", "anomalie", "rapport", "documentation", "evenements posterieurs"],
                "min_matches": 2,
            },
            {
                "doc_id": "audit_resume_acceptation_controle_qualite",
                "terms": ["fraude", "anomalie", "planification", "rapport", "documentation"],
                "min_matches": 2,
            },
            {
                "doc_id": "code_societes_commerciales_2022",
                "terms": ["commissaire aux comptes", "rapport", "fraude", "information"],
                "min_matches": 2,
            },
        ]
    if "amortissement" in query and ("immobilisation" in query or "corporelle" in query):
        return [
            {
                "doc_id": "nc_05_immobilisations_corporelles",
                "terms": ["amortissement", "duree d'utilite", "base amortissable", "valeur residuelle", "mise en service"],
                "min_matches": 2,
            },
            {
                "doc_id": "ias_16_immobilisations_corporelles",
                "terms": ["amortissement", "duree d'utilite", "valeur residuelle", "pret a etre utilisee", "base amortissable"],
                "min_matches": 2,
            },
            {
                "doc_id": "nc_01_norme_generale",
                "terms": ["immobilisations", "amortissement", "etats financiers", "estimation"],
                "min_matches": 2,
            },
        ]
    if ("creances douteuses" in query or "creance douteuse" in query) and (
        "deductible" in query or "deductibilite" in query or "deductibile" in query
    ):
        return [
            {
                "doc_id": "code_irpp_is_2011",
                "terms": ["creances douteuses", "provision", "deductible", "depreciation", "recouvrement"],
                "min_matches": 2,
            },
            {
                "doc_id": "nc_01_norme_generale",
                "terms": ["provision", "recouvrement", "depreciation", "creances"],
                "min_matches": 2,
            },
            {
                "doc_id": "ias_37_provisions_passifs_actifs_eventuels",
                "terms": ["provision", "obligation", "estimation", "depreciation", "creances douteuses"],
                "min_matches": 2,
            },
            {
                "doc_id": "procedures_fiscales_2026",
                "terms": ["controle", "justificatifs", "declaration", "contentieux"],
                "min_matches": 2,
            },
        ]
    coverage_workflow = detect_cabinet_workflow(query)
    if coverage_workflow:
        if coverage_workflow.family == "paie_social":
            social_rules: list[dict] = []
            if any(term in query for term in ("deces", "décès", "survivant", "survivants", "capital deces")):
                social_rules.extend([
                    {"doc_id": "cnss_p57_demande_indemnite_deces", "terms": ["indemnite de deces", "acte de deces", "assure social", "conjoint"], "min_matches": 2},
                    {"doc_id": "cnss_a144bis_pension_capital_deces_survivants", "terms": ["pension", "capital deces", "survivants", "conjoint survivant", "orphelins"], "min_matches": 2},
                    {"doc_id": "cnss_p58_constat_medical_de_deces", "terms": ["constat medical de deces", "cause de deces", "medecin traitant", "accident"], "min_matches": 2},
                ])
            if (
                ("pension alimentaire" in query or "rente de divorce" in query or "abandon de famille" in query)
                and "fonds" in query
                and not any(term in query for term in ("effectif", "beneficiaires", "bénéficiaires", "montant", "montants", "depenses", "dépenses", "evolution", "évolution", "2015", "2017", "2020"))
            ):
                social_rules.extend([
                    {"doc_id": "cnss_p314_fonds_garantie_pension_alimentaire", "terms": ["fonds de garantie", "pension alimentaire", "rente de divorce", "abandon de famille"], "min_matches": 2},
                    {"doc_id": "cnss_p314bis_engagement_fonds_garantie_pension_alimentaire", "terms": ["fonds de garantie", "pension alimentaire", "rente de divorce", "engagement"], "min_matches": 2},
                ])
            elif "demande de pension" in query or "pension de retraite" in query or "vieillesse" in query or "invalidite" in query or "invalidité" in query or "retraite anticipee" in query or "retraite anticipée" in query:
                social_rules.append({"doc_id": "cnss_a144_demande_pension", "terms": ["demande de pension", "vieillesse", "invalidite", "retraite anticipee"], "min_matches": 2})
            if "fille orpheline" in query or ("orpheline" in query and "sans revenu" in query):
                social_rules.append({"doc_id": "cnss_n104_declaration_fille_orpheline", "terms": ["fille orpheline", "non mariee", "sans revenu", "defunt"], "min_matches": 2})
            if "orphelin" in query and ("infirmit" in query or "maladie incurable" in query):
                social_rules.append({"doc_id": "cnss_n102_declaration_orphelin_infirme", "terms": ["orphelin", "infirmit", "maladie incurable", "sans revenu"], "min_matches": 2})
            if "pret logement" in query or "prêt logement" in query:
                social_rules.append({"doc_id": "cnss_f56bis_demande_pret_logement", "terms": ["pret logement", "construction", "acquisition", "terrain viabilise"], "min_matches": 2})
            if "accident non professionnel" in query or "accidents non professionnels" in query:
                social_rules.append({"doc_id": "cnss_n66_declaration_accident_non_professionnel", "terms": ["accident non professionnel", "declaration d accident", "temoins", "circonstances"], "min_matches": 2})
            if "non salarie" in query or "non salaries" in query or "non salarié" in query or "non salariés" in query:
                social_rules.append({"doc_id": "cnss_p212_affiliation_travailleurs_non_salaries", "terms": ["travailleurs non salaries", "secteurs agricole", "secteur non agricole", "affiliation"], "min_matches": 2})
            if "etranger" in query or "étranger" in query:
                social_rules.append({"doc_id": "cnss_p304_affiliation_travailleurs_tunisiens_etranger", "terms": ["travailleurs tunisiens a l etranger", "tunisiens a l etranger", "affiliation"], "min_matches": 2})
            if "declaration trimestrielle" in query or "déclaration trimestrielle" in query or "salaires declares" in query or "salaires déclarés" in query:
                if "agricole" in query:
                    social_rules.extend([
                        {"doc_id": "cnss_i27_declaration_trimestrielle_salaries_agricoles", "terms": ["declaration trimestrielle", "secteur agricole", "salaries", "qualification professionnelle"], "min_matches": 2},
                        {"doc_id": "cnss_i28_etat_recapitulatif_salaires_agricoles", "terms": ["etat recapitulatif", "salaires declares", "secteur agricole", "cotisations"], "min_matches": 2},
                    ])
                else:
                    social_rules.extend([
                        {"doc_id": "cnss_i16_declaration_trimestrielle_salaires", "terms": ["declaration trimestrielle", "remuneration mensuelle", "salaires declares", "trimestre"], "min_matches": 2},
                        {"doc_id": "cnss_i3_etat_recapitulatif_salaires_declares", "terms": ["etat recapitulatif", "salaires declares", "cotisations", "penalites de retard"], "min_matches": 2},
                    ])
            if "salaire unique" in query or "majoration" in query:
                social_rules.append({"doc_id": "cnss_c084_majoration_salaire_unique", "terms": ["majoration pour salaire unique", "salaire unique", "conjoint", "engagement"], "min_matches": 2})
            if "enfant handicape" in query or "enfant handicapé" in query or "maladie incurable" in query or "infirmit" in query:
                social_rules.append({"doc_id": "cnss_n101_declaration_enfant_handicape", "terms": ["enfant handicape", "infirmit", "maladie incurable", "declaration sur l honneur"], "min_matches": 2})
            if "pret universitaire" in query or "prêt universitaire" in query:
                social_rules.append({"doc_id": "cnss_f52_demande_pret_universitaire", "terms": ["pret universitaire", "etudiant", "inscription", "delai de 30 jours"], "min_matches": 2})
            if "ayant droit" in query or "ayants droit" in query or "enfants a charge" in query or "parents a charge" in query:
                social_rules.append({"doc_id": "cnss_p100_inscription_ayants_droit", "terms": ["ayants droit", "conjoint", "enfants a charge", "parents a charge"], "min_matches": 2})
            if "immatriculation" in query and ("etudiant" in query or "étudiant" in query or "stagiaire" in query or "diplome" in query or "diplômé" in query):
                social_rules.append({"doc_id": "cnss_p112_immatriculation_etudiant_stagiaire_diplome", "terms": ["immatriculation", "etudiant", "stagiaire", "diplome"], "min_matches": 2})
            if "inscription" in query and ("travailleur salarie" in query or "travailleur salarié" in query or "salarie" in query or "salarié" in query):
                social_rules.append({"doc_id": "cnss_n45_inscription_travailleur_salarie", "terms": ["inscription", "travailleur salarie", "employeur", "secteur agricole"], "min_matches": 2})
            if "attestation contentieuse" in query or ("contentieux" in query and "attestation" in query):
                social_rules.append({"doc_id": "cnss_n74_attestation_contentieuse", "terms": ["attestation contentieuse", "contentieux", "litige", "numero d affiliation"], "min_matches": 2})
            if "non assujettissement" in query or "non-assujettissement" in query:
                social_rules.append({"doc_id": "cnss_n124_attestation_non_assujettissement", "terms": ["attestation de non assujettissement", "non assujettissement", "identifiant fiscal", "registre de commerce"], "min_matches": 2})
            if "attestation de solde" in query:
                social_rules.append({"doc_id": "cnss_n75_attestation_de_solde", "terms": ["attestation de solde", "numero d affiliation", "raison sociale", "exemplaires"], "min_matches": 2})
            if "accident du travail" in query or "accidents du travail" in query or "maladie professionnelle" in query or "maladies professionnelles" in query:
                social_rules.append({"doc_id": "cnss_accidents_travail_maladies_professionnelles", "terms": ["accidents du travail", "maladies professionnelles", "incapacite permanente", "cotisations"], "min_matches": 2})
            if "guide de l employeur" in query or "guide de l'employeur" in query or ("secteur non agricole" in query and ("employeur" in query or "cotisation" in query or "declaration" in query)):
                social_rules.append({"doc_id": "cnss_guide_employeur_secteur_non_agricole", "terms": ["guide de l employeur", "secteur non agricole", "declaration des salaires", "penalite de retard"], "min_matches": 2})
            if "compte bancaire" in query or "comptes bancaires" in query or "rib" in query or (("bureau regional" in query or "bureau local" in query) and ("banque" in query or "bancaire" in query or "rib" in query)):
                social_rules.append({"doc_id": "cnss_liste_comptes_bancaires_bureaux_regionaux", "terms": ["comptes bancaires", "rib", "bureau regional", "stb"], "min_matches": 2})
            if "autorisation de debit" in query or "autorisation de débit" in query or "prelevement" in query or "prélèvement" in query:
                social_rules.append({"doc_id": "cnss_autorisation_debit_bancaire_postal", "terms": ["autorisation de debit", "compte bancaire", "compte postal", "prelevement"], "min_matches": 2})
            if "regime complementaire des pensions" in query or "régime complémentaire des pensions" in query or "rcp" in query or "retraite complementaire" in query:
                social_rules.append({"doc_id": "cnss_affiliation_regime_complementaire_pensions", "terms": ["regime complementaire des pensions", "rcp", "retraite complementaire", "smig"], "min_matches": 2})
            if ("service sms" in query or "85785" in query or ("sms" in query and "cnss" in query)) and ("mandat" in query or "cotisation" in query or "salaire" in query or "85785" in query or "inscrire" in query or "inscription" in query):
                social_rules.append({"doc_id": "cnss_service_sms", "terms": ["service sms", "85785", "mandats electroniques", "cotisations", "salaires declares"], "min_matches": 2})
            elif "service sms" in query or ("sms" in query and "cnss" in query):
                social_rules.append({"doc_id": "cnss_flyer_sms", "terms": ["sms", "telephone portable", "service sms", "notification"], "min_matches": 2})
            if ("convention bilaterale" in query or "conventions bilaterales" in query or "convention bilatérale" in query or "conventions bilatérales" in query or "tuniso-marocaine" in query or "tuniso-bulgare" in query or "tuniso-tcheque" in query or "tuniso-tchèque" in query) and ("securite sociale" in query or "sécurité sociale" in query or "cnss" in query):
                social_rules.append({"doc_id": "cnss_conventions_bilaterales_securite_sociale_2017", "terms": ["convention bilaterale", "securite sociale", "tuniso-marocaine", "tuniso-bulgare", "tuniso-tcheque"], "min_matches": 2})
            if ("administration plus proche" in query or "maison de service" in query or "maisons de service" in query or "service de proximite" in query or "service de proximité" in query) and "cnss" in query:
                social_rules.append({"doc_id": "cnss_maisons_service_administration_proche", "terms": ["administration plus proche", "maison de service", "gouvernorat", "affiliation", "immatriculation"], "min_matches": 2})
            if ("smig" in query or "smag" in query or "salaire minimum garanti" in query or "salaire minimum agricole" in query) and ("cnss" in query or "2020" in query or "decret" in query or "décret" in query):
                social_rules.append({"doc_id": "cnss_smig_smag_2020", "terms": ["salaire minimum garanti", "smig", "smag", "decret 2020-1069", "decret 2020-1070"], "min_matches": 2})
            if ("pret universitaire" in query or "prêt universitaire" in query or "prets universitaires" in query or "prêts universitaires" in query) and ("nouveautes" in query or "nouveautés" in query or "2017" in query or "taux d interet" in query or "taux d'intérêt" in query or "interets de retard" in query):
                social_rules.append({"doc_id": "cnss_communique_prets_universitaires_2017", "terms": ["prets universitaires", "decret gouvernemental 2017-369", "taux d interet", "interets de retard", "48 tranches"], "min_matches": 2})
            if "presentation cnss" in query or "présentation cnss" in query or "missions de la cnss" in query or "caisse nationale de securite sociale" in query:
                social_rules.append({"doc_id": "cnss_presentation_institutionnelle", "terms": ["caisse nationale de securite sociale", "loi n 60-30", "prestations familiales", "pensions"], "min_matches": 2})
            if "prets sociaux" in query or "prêts sociaux" in query:
                if "2010" in query and "2020" in query:
                    social_rules.append({"doc_id": "cnss_prets_sociaux_nombre_montants_2010_2020", "terms": ["prets sociaux", "nombre et montants", "2010", "2020"], "min_matches": 2})
                if ("effectif" in query or "effectifs" in query or "beneficiaires" in query or "bénéficiaires" in query) and "2000" in query and "2020" in query:
                    social_rules.append({"doc_id": "cnss_prets_sociaux_effectifs_nature_2000_2020", "terms": ["prets sociaux", "effectifs par nature", "pret personnel", "pret universitaire"], "min_matches": 2})
                if ("montant" in query or "montants" in query or "depenses" in query or "dépenses" in query) and "2000" in query and "2020" in query:
                    social_rules.append({"doc_id": "cnss_prets_sociaux_montants_nature_2000_2020", "terms": ["prets sociaux", "montants par nature", "pret voiture", "pret logement"], "min_matches": 2})
                if "2000" in query:
                    social_rules.append({"doc_id": "cnss_prets_sociaux_effectifs_montants_2000", "terms": ["prets sociaux", "pret logement", "pret personnel", "pret universitaire", "annee 2000"], "min_matches": 2})
                if "2020" in query:
                    social_rules.append({"doc_id": "cnss_prets_sociaux_effectifs_montants_2020", "terms": ["prets sociaux", "pret logement", "pret personnel", "pret universitaire", "annee 2020"], "min_matches": 2})
            if "fonds de garantie" in query and ("pension alimentaire" in query or "rente de divorce" in query or "divorce" in query):
                if "2015" in query or "2020" in query or "evolution" in query or "évolution" in query:
                    social_rules.append({"doc_id": "cnss_fonds_garantie_pension_divorce_2015_2020", "terms": ["fonds de garantie", "pension alimentaire", "rente de divorce", "2015", "2020"], "min_matches": 2})
                if "effectif" in query or "beneficiaires" in query or "bénéficiaires" in query:
                    social_rules.append({"doc_id": "cnss_fonds_garantie_effectif_2017", "terms": ["fonds de garantie", "effectif", "beneficiaires", "pension alimentaire", "2017"], "min_matches": 2})
                if "montant" in query or "montants" in query or "depenses" in query or "dépenses" in query:
                    social_rules.append({"doc_id": "cnss_fonds_garantie_montants_2017", "terms": ["fonds de garantie", "montants", "depenses", "pension alimentaire", "2017"], "min_matches": 2})
            if ("sommaire" in query and "2020" in query and "cnss" in query) or ("statistiques" in query and "2020" in query and "cnss" in query):
                social_rules.append({"doc_id": "cnss_sommaire_statistique_2020", "terms": ["sommaire", "assures sociaux", "employeurs", "recettes", "depenses"], "min_matches": 2})
            if ("bilan" in query or "etat de resultat" in query or "état de résultat" in query or "flux de tresorerie" in query or "flux de trésorerie" in query) and "cnss" in query:
                social_rules.append({"doc_id": "cnss_publication_financiere_2018", "terms": ["bilan", "etat de resultat", "flux de tresorerie", "capitaux propres", "2018"], "min_matches": 2})
            if ("evolution des cotisations" in query or "évolution des cotisations" in query or "cotisations cnss" in query) and ("2000" in query or "2020" in query):
                social_rules.append({"doc_id": "cnss_evolution_cotisations_2000_2020", "terms": ["evolution des cotisations", "cotisations cnss", "ensemble des regimes", "2000", "2020"], "min_matches": 2})
            if ("evolution des depenses" in query or "évolution des dépenses" in query or "depenses de prestations" in query or "dépenses de prestations" in query or "prestations servies" in query) and ("2000" in query or "2020" in query):
                social_rules.append({"doc_id": "cnss_evolution_depenses_prestations_2000_2020", "terms": ["evolution des depenses", "prestations servies", "pensions", "prestations familiales", "2000"], "min_matches": 2})
            if "prestations familiales" in query and "2020" in query:
                social_rules.append({"doc_id": "cnss_prestations_familiales_2020", "terms": ["prestations familiales", "allocations familiales", "majoration pour salaire unique", "2020"], "min_matches": 2})
            if ("prestations en especes" in query or "prestations en espèces" in query or "assurances sociales" in query or "capital deces" in query or "capital décès" in query) and "2020" in query:
                social_rules.append({"doc_id": "cnss_prestations_assurances_sociales_especes_2020", "terms": ["prestations en especes", "assurances sociales", "indemnite de deces", "capital deces"], "min_matches": 2})
            if ("depenses de pension" in query or "dépenses de pension" in query or "les pensions" in query) and "2020" in query:
                social_rules.append({"doc_id": "cnss_depenses_pensions_regime_nature_2020", "terms": ["depenses de pension", "regime complementaire", "retraite", "survie conjoints"], "min_matches": 2})
            if ("effectif des assures sociaux" in query or "effectif des assur" in query or ("assures sociaux" in query and "pensionnes" in query)) and ("2000" in query or "2020" in query):
                social_rules.append({"doc_id": "cnss_evolution_effectif_assures_sociaux_2000_2020", "terms": ["effectif des assures sociaux", "actifs", "pensionnes", "ensemble des regimes"], "min_matches": 2})
            if ("assures sociaux actifs" in query or ("assur" in query and "sociaux actifs" in query)) and ("regime" in query or "rÃ©gime" in query):
                social_rules.append({"doc_id": "cnss_repartition_assures_actifs_regime_2000_2020", "terms": ["assures sociaux actifs", "par regime", "travailleurs non salaries", "2000"], "min_matches": 2})
            if "titulaires de pensions" in query and ("regime" in query or "rÃ©gime" in query):
                social_rules.append({"doc_id": "cnss_repartition_titulaires_pensions_regime_2000_2020", "terms": ["titulaires de pensions", "par regime", "salaries non agricoles", "2020"], "min_matches": 2})
            if "titulaires de pensions" in query and ("nature" in query or "orphelins" in query or "conjoints survivants" in query):
                social_rules.append({"doc_id": "cnss_repartition_titulaires_pensions_nature_2000_2020", "terms": ["titulaires de pensions", "nature de pension", "retraites", "orphelins"], "min_matches": 2})
            if "rapport demographique" in query or "rapport dÃ©mographique" in query:
                social_rules.append({"doc_id": "cnss_rapport_demographique_2000_2020", "terms": ["rapport demographique", "nombre des actifs", "beneficiaire de pension", "2020"], "min_matches": 2})
            if ("effectif des employeurs" in query or ("employeurs" in query and "secteur" in query)) and ("2000" in query or "2020" in query):
                social_rules.append({"doc_id": "cnss_evolution_effectif_employeurs_2000_2020", "terms": ["effectif des employeurs", "secteur non agricole", "secteur agricole", "2000"], "min_matches": 2})
            if ("employeurs par regime" in query or "employeurs par rÃ©gime" in query or ("repartition employeurs" in query and ("regime" in query or "rÃ©gime" in query))) and ("2000" in query or "2020" in query):
                social_rules.append({"doc_id": "cnss_repartition_employeurs_regime_2000_2020", "terms": ["employeurs par regime", "salaries non agricoles", "travailleurs a faible revenu", "2020"], "min_matches": 2})
            if ("notes aux etats financiers" in query or "notes aux Ã©tats financiers" in query or "etat2018" in query) and ("2018" in query or "cnss" in query):
                social_rules.append({"doc_id": "cnss_notes_etats_financiers_2018", "terms": ["notes aux etats financiers", "normes comptables tunisiennes", "cotisants", "produits techniques"], "min_matches": 2})
            if "budget 2022" in query and "cnss" in query:
                social_rules.append({"doc_id": "cnss_budget_2022", "terms": ["budget 2022", "produits techniques", "charges techniques", "resultat technique"], "min_matches": 2})
            tender_exact_01ca = "climatiseur" in query or "01/ca/2020" in query or "01 ca 2020" in query
            tender_exact_it = ("oracle" in query or "systeme d information" in query or "système d information" in query or "pmsi" in query or "informatique" in query) and "cnss" in query
            tender_exact_it_equipment = ("equipements informatiques" in query or "équipements informatiques" in query or "cablage informatique" in query or "câblage informatique" in query or "switch" in query or "video-surveillance" in query or "vidéo-surveillance" in query or "16/2016" in query or "16/2017" in query or "10/ca/2017" in query) and "cnss" in query
            tender_exact_works = ("travaux" in query or "construction" in query or "amenagement" in query or "aménagement" in query or "bureau regional" in query) and "cnss" in query
            tender_linux = ("03/ca/2018" in query or "03 ca 2018" in query or "linux" in query) and "cnss" in query
            tender_mahdia = ("01/ca/2017" in query or "01 ca 2017" in query or ("mahdia" in query and "extension" in query)) and "cnss" in query
            tender_oracle_report = ("20/2017" in query or "20 2017" in query or ("oracle" in query and "report" in query)) and "cnss" in query
            tender_iso22301 = ("09/ca/2017" in query or "09 ca 2017" in query or "iso 22301" in query or "continuite des activites" in query or "continuité des activités" in query) and "cnss" in query
            tender_rolling_stock = ("02/2020" in query or "02 2020" in query or "materiel roulant" in query or "matériel roulant" in query or "voiture de service" in query or "camion fourgon" in query) and "cnss" in query
            tender_si_video_2020 = ("01/si/2020" in query or "01 si 2020" in query or ("video-surveillance" in query and "2020" in query) or ("vidéo-surveillance" in query and "2020" in query)) and "cnss" in query
            if ("appel d offres" in query or "appels d offres" in query or "appel d'offre" in query or "appels d'offre" in query or "appel d’offres" in query or "appels d’offres" in query or "marches publics" in query or "marchés publics" in query or "طلب العروض" in query) and ("cnss" in query or "الصندوق" in query) and not (tender_exact_01ca or tender_exact_it or tender_exact_it_equipment or tender_exact_works or tender_linux or tender_mahdia or tender_oracle_report or tender_iso22301 or tender_rolling_stock or tender_si_video_2020):
                social_rules.extend([
                    {"doc_id": "cnss_appels_offres_resultats_ar_2016_2017", "terms": ["طلب العروض", "اسناد الصفقة", "غير مثمر", "اقتناء"], "min_matches": 2},
                    {"doc_id": "cnss_appels_offres_informatique_2015_2017", "terms": ["appel d offres", "systeme d information", "oracle", "pmsi"], "min_matches": 2},
                    {"doc_id": "cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017", "terms": ["equipements informatiques", "cablage informatique", "switchs", "video-surveillance"], "min_matches": 2},
                    {"doc_id": "cnss_appels_offres_travaux_2015_2017", "terms": ["appel d offres", "construction", "amenagement", "bureau regional"], "min_matches": 2},
                    {"doc_id": "cnss_avis_appel_offres_climatiseurs_01ca2020", "terms": ["avis d appel d offres", "01 ca 2020", "climatiseurs", "tuneps"], "min_matches": 2},
                    {"doc_id": "cnss_avis_03ca2018_linux_tuneps", "terms": ["03 ca 2018", "linux", "souscription et maintenance", "tuneps"], "min_matches": 2},
                    {"doc_id": "cnss_avis_01ca2017_extension_bureau_mahdia", "terms": ["01 ca 2017", "extension", "bureau regional de mahdia", "travaux"], "min_matches": 2},
                    {"doc_id": "cnss_report_ao20_2017_licences_oracle", "terms": ["20 2017", "licences oracle", "report", "14 fevrier 2018"], "min_matches": 2},
                    {"doc_id": "cnss_avis_09ca2017_iso22301_continuite_activites", "terms": ["09 ca 2017", "iso 22301", "continuite des activites", "management"], "min_matches": 2},
                    {"doc_id": "cnss_ao02_2020_materiel_roulant_tuneps", "terms": ["02 2020", "materiel roulant", "voiture", "camion fourgon", "tuneps"], "min_matches": 2},
                    {"doc_id": "cnss_consultation_01si2020_videosurveillance_tuneps", "terms": ["01 si 2020", "video-surveillance", "tuneps", "signature electronique"], "min_matches": 2},
                ])
            if tender_exact_01ca and "cnss" in query:
                social_rules.append({"doc_id": "cnss_avis_appel_offres_climatiseurs_01ca2020", "terms": ["avis d appel d offres", "01 ca 2020", "climatiseurs", "tuneps"], "min_matches": 2})
            if tender_exact_it_equipment:
                social_rules.append({"doc_id": "cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017", "terms": ["equipements informatiques", "cablage informatique", "switchs", "video-surveillance"], "min_matches": 2})
            if tender_exact_it and not (tender_exact_it_equipment or tender_oracle_report):
                social_rules.append({"doc_id": "cnss_appels_offres_informatique_2015_2017", "terms": ["appel d offres", "systeme d information", "oracle", "pmsi"], "min_matches": 2})
            if tender_exact_works and not tender_mahdia:
                social_rules.append({"doc_id": "cnss_appels_offres_travaux_2015_2017", "terms": ["appel d offres", "construction", "amenagement", "bureau regional"], "min_matches": 2})
            if tender_linux:
                social_rules.append({"doc_id": "cnss_avis_03ca2018_linux_tuneps", "terms": ["03 ca 2018", "linux", "souscription et maintenance", "tuneps"], "min_matches": 2})
            if tender_mahdia:
                social_rules.append({"doc_id": "cnss_avis_01ca2017_extension_bureau_mahdia", "terms": ["01 ca 2017", "extension", "bureau regional de mahdia", "travaux"], "min_matches": 2})
            if tender_oracle_report:
                social_rules.append({"doc_id": "cnss_report_ao20_2017_licences_oracle", "terms": ["20 2017", "licences oracle", "report", "14 fevrier 2018"], "min_matches": 2})
            if tender_iso22301:
                social_rules.append({"doc_id": "cnss_avis_09ca2017_iso22301_continuite_activites", "terms": ["09 ca 2017", "iso 22301", "continuite des activites", "management"], "min_matches": 2})
            if tender_rolling_stock:
                social_rules.append({"doc_id": "cnss_ao02_2020_materiel_roulant_tuneps", "terms": ["02 2020", "materiel roulant", "voiture", "camion fourgon", "tuneps"], "min_matches": 2})
            if tender_si_video_2020:
                social_rules.append({"doc_id": "cnss_consultation_01si2020_videosurveillance_tuneps", "terms": ["01 si 2020", "video-surveillance", "tuneps", "signature electronique"], "min_matches": 2})
            if ("fiches des services" in query or "delais des services" in query or "délais des services" in query or "services cnss" in query or "قائمة خدمات الصندوق" in query or "آجال الحصول" in query) and ("cnss" in query or "الصندوق" in query):
                social_rules.append({"doc_id": "cnss_fiches_services_octobre_2020", "terms": ["fiches des services", "delais", "آجال", "الخدمة", "الإنخراط", "الشهادات", "prestations"], "min_matches": 2})
            if ("engagements envers le citoyen" in query or ("engagement" in query and "citoyen" in query) or "service du citoyen" in query or "relations avec le citoyen" in query or "reseau de bureaux" in query or "réseau de bureaux" in query or "bureau regional" in query or "bureaux regionaux" in query or "bureau local" in query or "bureaux locaux" in query) and "cnss" in query:
                social_rules.append({"doc_id": "cnss_engagements_citoyen_reseau", "terms": ["engagement", "citoyen", "bureau regional", "bureau local", "delai"], "min_matches": 2})
            explicit_doc_ids = {rule["doc_id"] for rule in social_rules}
            existing_doc_ids = set(explicit_doc_ids)
            social_rules.extend(
                {"doc_id": doc_id, "terms": list(terms), "min_matches": min_matches}
                for doc_id, terms, min_matches in coverage_workflow.source_terms
                if doc_id not in existing_doc_ids
            )
            statistical_doc_ids = {
                "cnss_evolution_cotisations_2000_2020",
                "cnss_evolution_depenses_prestations_2000_2020",
                "cnss_prestations_familiales_2020",
                "cnss_prestations_assurances_sociales_especes_2020",
                "cnss_depenses_pensions_regime_nature_2020",
                "cnss_prets_sociaux_nombre_montants_2010_2020",
                "cnss_prets_sociaux_effectifs_nature_2000_2020",
                "cnss_prets_sociaux_montants_nature_2000_2020",
                "cnss_prets_sociaux_effectifs_montants_2000",
                "cnss_prets_sociaux_effectifs_montants_2020",
                "cnss_fonds_garantie_pension_divorce_2015_2020",
                "cnss_fonds_garantie_effectif_2017",
                "cnss_fonds_garantie_montants_2017",
                    "cnss_sommaire_statistique_2020",
                    "cnss_publication_financiere_2018",
                    "cnss_evolution_effectif_assures_sociaux_2000_2020",
                    "cnss_repartition_assures_actifs_regime_2000_2020",
                    "cnss_repartition_titulaires_pensions_regime_2000_2020",
                    "cnss_repartition_titulaires_pensions_nature_2000_2020",
                    "cnss_rapport_demographique_2000_2020",
                    "cnss_evolution_effectif_employeurs_2000_2020",
                    "cnss_repartition_employeurs_regime_2000_2020",
                    "cnss_notes_etats_financiers_2018",
                    "cnss_budget_2022",
                }
            if "formulaire" not in query and "demande" not in query:
                explicit_statistical_doc_ids = statistical_doc_ids.intersection(explicit_doc_ids)
                social_rules = [rule for rule in social_rules if rule["doc_id"] in explicit_statistical_doc_ids] + [
                    rule for rule in social_rules if rule["doc_id"] not in explicit_statistical_doc_ids
                ]
            return social_rules
        return [
            {"doc_id": doc_id, "terms": list(terms), "min_matches": min_matches}
            for doc_id, terms, min_matches in coverage_workflow.source_terms
        ]
    return []


TREATY_SOURCE_TERMS: dict[str, list[str]] = {
    "convention_fiscale_tunisie_tchecoslovaquie_slovaquie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_soudan": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_suede": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_suisse": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_oman": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_syrie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_turquie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_union_maghreb_arabe": ["etablissement stable", "benefices des entreprises", "double imposition", "assistance", "recouvrement"],
    "convention_fiscale_tunisie_pays_bas": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_pologne": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_portugal": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_qatar": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_republique_tcheque": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_roumanie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_royaume_uni": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "gains en capital"],
    "convention_fiscale_tunisie_senegal": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "assistance"],
    "convention_fiscale_tunisie_serbie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_singapour": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_liban": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "protocole_convention_fiscale_tunisie_liban": ["protocole", "article 5", "dispositions plus avantageuses", "republique libanaise"],
    "convention_fiscale_tunisie_luxembourg": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_libye": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_mali": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "assistance"],
    "convention_fiscale_tunisie_malte": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_maroc": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_mauritanie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_norvege": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_pakistan": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_koweit": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_ethiopie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_france_local": ["etablissement stable", "assistance mutuelle", "revenus non commerciaux", "redevances"],
    "convention_fiscale_tunisie_grece": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "gains en capital"],
    "convention_fiscale_tunisie_hongrie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_ile_maurice": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_indonesie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_iran": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_italie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_jordanie": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "capital"],
    "convention_fiscale_tunisie_burkina_faso": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_cameroun": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_canada": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_chine": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_coree_sud": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_cote_ivoire": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_danemark": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_egypte": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "gains en capital"],
    "convention_fiscale_tunisie_emirats_arabes_unis": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
    "convention_fiscale_tunisie_espagne": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
    "convention_fiscale_tunisie_belgique": ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances", "fortune"],
}


TREATY_COUNTRY_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("republique tcheque", "tcheque"), "convention_fiscale_tunisie_republique_tcheque"),
    (("slovaquie", "tchecoslovaquie"), "convention_fiscale_tunisie_tchecoslovaquie_slovaquie"),
    (("soudan", "sudan"), "convention_fiscale_tunisie_soudan"),
    (("suede",), "convention_fiscale_tunisie_suede"),
    (("suisse",), "convention_fiscale_tunisie_suisse"),
    (("oman",), "convention_fiscale_tunisie_oman"),
    (("syrie", "syrienne"), "convention_fiscale_tunisie_syrie"),
    (("turquie",), "convention_fiscale_tunisie_turquie"),
    (("protocole liban", "protocol liban"), "protocole_convention_fiscale_tunisie_liban"),
    (("liban",), "convention_fiscale_tunisie_liban"),
    (("luxembourg",), "convention_fiscale_tunisie_luxembourg"),
    (("libye", "lybie"), "convention_fiscale_tunisie_libye"),
    (("mali",), "convention_fiscale_tunisie_mali"),
    (("malte",), "convention_fiscale_tunisie_malte"),
    (("maroc",), "convention_fiscale_tunisie_maroc"),
    (("mauritanie",), "convention_fiscale_tunisie_mauritanie"),
    (("norvege",), "convention_fiscale_tunisie_norvege"),
    (("pakistan",), "convention_fiscale_tunisie_pakistan"),
    (("koweit",), "convention_fiscale_tunisie_koweit"),
    (("ethiopie", "ethioupie"), "convention_fiscale_tunisie_ethiopie"),
    (("france",), "convention_fiscale_tunisie_france_local"),
    (("grece",), "convention_fiscale_tunisie_grece"),
    (("hongrie",), "convention_fiscale_tunisie_hongrie"),
    (("ile maurice", "ile-de-maurice", "maurice"), "convention_fiscale_tunisie_ile_maurice"),
    (("indonesie",), "convention_fiscale_tunisie_indonesie"),
    (("iran",), "convention_fiscale_tunisie_iran"),
    (("italie",), "convention_fiscale_tunisie_italie"),
    (("jordanie",), "convention_fiscale_tunisie_jordanie"),
    (("burkina", "burkina faso", "burkina-faso"), "convention_fiscale_tunisie_burkina_faso"),
    (("cameroun",), "convention_fiscale_tunisie_cameroun"),
    (("canada",), "convention_fiscale_tunisie_canada"),
    (("chine",), "convention_fiscale_tunisie_chine"),
    (("coree du sud", "coree", "corée du sud", "corée"), "convention_fiscale_tunisie_coree_sud"),
    (("cote d'ivoire", "cote d ivoire", "côte d'ivoire", "côte d ivoire"), "convention_fiscale_tunisie_cote_ivoire"),
    (("danemark",), "convention_fiscale_tunisie_danemark"),
    (("egypte", "égypte"), "convention_fiscale_tunisie_egypte"),
    (("emirats arabes unis", "emirates arabes unis", "emirats", "emirates", "dubai", "abu dhabi"), "convention_fiscale_tunisie_emirats_arabes_unis"),
    (("espagne",), "convention_fiscale_tunisie_espagne"),
    (("belgique",), "convention_fiscale_tunisie_belgique"),
    (("union du maghreb arabe", "u.m.a", "maghreb"), "convention_fiscale_union_maghreb_arabe"),
    (("pays bas", "pays-bas", "netherlands", "hollande"), "convention_fiscale_tunisie_pays_bas"),
    (("pologne",), "convention_fiscale_tunisie_pologne"),
    (("portugal",), "convention_fiscale_tunisie_portugal"),
    (("qatar",), "convention_fiscale_tunisie_qatar"),
    (("roumanie",), "convention_fiscale_tunisie_roumanie"),
    (("royaume uni", "royaume-uni", "grande bretagne", "bretagne", "irlande du nord", "united kingdom", "uk"), "convention_fiscale_tunisie_royaume_uni"),
    (("senegal",), "convention_fiscale_tunisie_senegal"),
    (("serbie",), "convention_fiscale_tunisie_serbie"),
    (("singapour", "singapore"), "convention_fiscale_tunisie_singapour"),
    (("vietnam",), "convention_fiscale_tunisie_vietnam"),
    (("yemen",), "convention_fiscale_tunisie_yemen"),
)


def detected_treaty_doc_ids(query: str) -> list[str]:
    found: list[str] = []
    for terms, doc_id in TREATY_COUNTRY_PATTERNS:
        if any(term in query for term in terms) and doc_id not in found:
            found.append(doc_id)
    return found


def is_treaty_overview_query(query: str) -> bool:
    return any(
        term in query
        for term in (
            "convention fiscale",
            "accord fiscal",
            "double imposition",
            "impots sur le revenu",
            "impot sur le revenu",
            "impots sur la fortune",
            "etablissement stable",
            "redevances",
        )
    )


def treaty_precision_rules(doc_ids: list[str]) -> list[dict]:
    return [
        {
            "doc_id": doc_id,
            "terms": TREATY_SOURCE_TERMS.get(
                doc_id,
                ["etablissement stable", "benefices des entreprises", "dividendes", "interets", "redevances"],
            ),
            "min_matches": 2,
        }
        for doc_id in doc_ids
    ]


def tax_procedure_precision_rules(query: str) -> list[dict]:
    rules: list[dict] = []
    if "licoba" in query or "comptes bancaires" in query or "comptes postaux" in query or "listecomptes" in query:
        if "xsd" in query or "schema" in query:
            rules.append({
                "doc_id": "schema_licoba_liste_comptes_trimestrielle_2026",
                "terms": ["ComptesBancaires", "ListeComptes", "RIB", "Trimestre"],
                "min_matches": 2,
            })
        rules.append({
            "doc_id": "cahier_charges_licoba_depot_trimestriel_comptes_2026",
            "terms": ["LICOBA", "DEPOT TRIMESTRIEL", "COMPTES BANCAIRES", "PERIODICITE"],
            "min_matches": 2,
        })
        return rules
    if "declaration mensuelle" in query or "mensuelle" in query:
        if "2025" in query:
            rules.append({
                "doc_id": "formulaire_declaration_mensuelle_ar_2025",
                "terms": ["التصريح الشهري", "الأداءات", "الشهر", "السنة"],
                "min_matches": 2,
            })
        if "2026" in query:
            rules.append({
                "doc_id": "formulaire_declaration_mensuelle_ar_2026",
                "terms": ["التصريح الشهري", "الأداءات", "الشهر", "السنة"],
                "min_matches": 2,
            })
        if not rules:
            rules.extend([
                {
                    "doc_id": "formulaire_declaration_mensuelle_ar_2026",
                    "terms": ["التصريح الشهري", "الأداءات", "الشهر", "السنة"],
                    "min_matches": 2,
                },
                {
                    "doc_id": "formulaire_declaration_mensuelle_ar_2025",
                    "terms": ["التصريح الشهري", "الأداءات", "الشهر", "السنة"],
                    "min_matches": 2,
                },
            ])
        return rules
    if "impot sur la fortune" in query or "impÃ´t sur la fortune" in query or "fortune" in query:
        return [{
            "doc_id": "formulaire_impot_fortune_2026",
            "terms": ["الضريبة على الثروة", "الفصل 88", "قانون المالية", "المكاسب"],
            "min_matches": 2,
        }]
    if "declaration is" in query or "impot sur les societes" in query or "impÃ´t sur les sociÃ©tÃ©s" in query:
        return [{
            "doc_id": "formulaire_declaration_is_2026",
            "terms": ["الضريبة على الشركات", "نتائج سنة", "السنة المالية", "الاسم الاجتماعي"],
            "min_matches": 2,
        }]
    if "teleliquidation" in query or "tÃ©lÃ©liquidation" in query or "adhesion" in query or "adhÃ©sion" in query:
        return [{
            "doc_id": "formulaire_adhesion_teleliquidation_impots",
            "terms": ["اﻻﺗﺤﻴﻴﻦ", "اﺣﺘﺴﺎب", "دﻓﻌ", "impots"],
            "min_matches": 1,
        }]
    if "declaration employeur" in query or "employeur" in query:
        return [{
            "doc_id": "formulaire_declaration_employeur_2025",
            "terms": ["تصريح", "المؤجر", "السنة", "الملاحق"],
            "min_matches": 2,
        }]
    if "plus-value" in query or "plus value" in query or "cession d actions" in query or "cession actions" in query:
        return [{
            "doc_id": "formulaire_plus_value_actions_ar_2025",
            "terms": ["القيمة الزائدة", "التفويت", "الأسهم", "المنابات الاجتماعية"],
            "min_matches": 2,
        }]
    if "declaration impot sur le revenu" in query or "irpp" in query:
        return [{
            "doc_id": "formulaire_declaration_irpp_ar_2025",
            "terms": ["الضريبة على دخل", "الأشخاص الطبيعيين", "المعرف الجبائي", "السنة المالية"],
            "min_matches": 2,
        }]
    return []


def is_cross_border_service_case(query: str) -> bool:
    foreign_markers = [
        "france", "francais", "italie", "italien", "allemagne", "allemand",
        "emirats", "dubai", "uae", "algerie", "algerien", "vietnam", "yemen", "yémen",
        "slovaquie", "tchecoslovaquie", "soudan", "sudan", "suede", "suède", "suisse",
        "oman", "syrie", "turquie", "maroc", "libye", "mauritanie", "maghreb",
        "pays bas", "pays-bas", "pologne", "portugal", "qatar", "republique tcheque",
        "roumanie", "royaume uni", "royaume-uni", "grande bretagne", "bretagne",
        "irlande du nord", "senegal", "serbie", "singapour", "singapore",
        "liban", "luxembourg", "libye", "lybie", "mali", "malte",
        "norvege", "pakistan",
        "koweit", "ethiopie", "ethioupie", "grece", "hongrie",
        "ile maurice", "ile-de-maurice", "maurice", "indonesie",
        "iran", "italie", "jordanie", "burkina", "burkina faso",
        "cameroun", "canada", "chine", "coree du sud", "corée du sud",
        "cote d'ivoire", "cote d ivoire", "côte d'ivoire", "côte d ivoire",
        "danemark", "egypte", "égypte", "emirats arabes unis",
        "emirates arabes unis", "espagne", "belgique",
        "client etranger",
        "societe algerienne", "societe allemande", "societe italienne",
        "non resident", "hors de tunisie", "eur", "euro",
    ]
    service_markers = [
        "prestation", "services", "informatique", "logiciel", "installation",
        "formation", "licence", "redevance", "assistance", "support",
        "parametrage", "maintenance", "consultants",
    ]
    tunisian_markers = ["societe tunisienne", "tunisie", "prestataire tunisien"]
    return (
        any(marker in query for marker in foreign_markers)
        and any(marker in query for marker in service_markers)
        and (
            any(marker in query for marker in tunisian_markers)
            or ("regime fiscal" in query and ("facture" in query or "facturee" in query))
        )
    )


def is_mixed_dividends_case(query: str) -> bool:
    distribution_markers = ["dividende", "dividendes", "benefices distribues", "revenus distribues", "distribution"]
    profile_markers = [
        "personne physique", "societe tunisienne", "personne morale", "associe",
        "actionnaire", "non resident", "resident", "beneficiaire", "certificat",
        "retenue", "reserves", "trois", "profils",
    ]
    return (
        (any(marker in query for marker in distribution_markers) and sum(1 for marker in profile_markers if marker in query) >= 2)
        or ("reserves" in query and "benefices distribues" in query)
    )


def is_revenue_cutoff_tva_case(query: str) -> bool:
    service_markers = ["maintenance", "contrat annuel", "abonnement", "support", "service annuel", "assistance", "prestation annuelle"]
    timing_markers = ["avance", "upfront", "paye", "payee", "facture", "encaisse", "12 mois", "annuel"]
    cutoff_markers = ["2025", "2026", "cloture", "cut off", "cut-off", "produit constate d'avance", "rattachement", "periode"]
    return (
        any(marker in query for marker in service_markers)
        and any(marker in query for marker in timing_markers)
        and sum(1 for marker in cutoff_markers if marker in query) >= 1
    )


def is_receivable_subsequent_recovery_case(query: str) -> bool:
    has_receivable = (
        ("creance" in query and ("client" in query or "douteuse" in query or "douteuses" in query))
        or "facture client" in query
        or "client doit" in query
        or "client conteste" in query
        or "client est en retard" in query
        or ("client" in query and "solde" in query and "provision" in query)
        or ("client" in query and "impayee" in query and "provision" in query)
    )
    has_age_or_doubt = (
        "14 mois" in query
        or "11 mois" in query
        or "8 mois" in query
        or "echue" in query
        or "impayee" in query
        or "en retard" in query
        or "conteste" in query
        or "relance" in query
        or "relances" in query
        or "provision" in query
        or "provisionner" in query
        or "depreciation" in query
        or "balance agee" in query
    )
    return (
        has_receivable
        and has_age_or_doubt
        and (
            "cloture" in query
            or "cleture" in query
            or "post cloture" in query
            or "apres la cloture" in query
            or "posterieur" in query
            or "deductibilite" in query
            or "deductible" in query
            or "deduire" in query
            or "fiscal" in query
        )
    )


def is_fixed_asset_component_depreciation_case(query: str) -> bool:
    asset_markers = ["machine", "immobilisation", "equipement", "ligne de production", "actif", "moteur"]
    issue_markers = [
        "amortissement", "amortir", "depreciation", "installation", "tests",
        "mise en service", "mise en production", "pret a fonctionner", "pret a etre utilise",
        "production", "composant", "piece majeure", "taux fiscal", "duree comptable",
    ]
    return any(marker in query for marker in asset_markers) and sum(1 for marker in issue_markers if marker in query) >= 2


def is_going_concern_case(query: str) -> bool:
    if "cnss" in query and any(marker in query for marker in ("appel d offres", "appel d offre", "consultation", "tuneps", "marches publics")):
        return False
    return (
        "continuite" in query
        or "going concern" in query
        or "cessation d activite" in query
        or "continuer son exploitation" in query
        or "risque de cessation" in query
        or ("tresorerie" in query and ("insuffisante" in query or "negative" in query or "rupture" in query))
        or ("fournisseurs" in query and ("impayes" in query or "retard" in query))
        or ("capitaux propres" in query and ("negatifs" in query or "negative" in query))
        or ("financement bancaire" in query and "non confirme" in query)
        or ("soutien bancaire" in query and "non confirme" in query)
        or ("budget de tresorerie" in query and ("conclure" in query or "hypothese" in query))
    )


def is_related_party_property_case(query: str) -> bool:
    property_markers = ["immeuble", "bien immobilier", "propriete", "terrain", "local", "actif immobilier", "vehicule", "actif"]
    related_markers = ["gerant", "dirigeant", "associe", "actionnaire", "partie liee", "administrateur", "societe soeur"]
    risk_markers = [
        "valeur de marche", "dessous", "inferieur", "prix bas", "prix tres bas",
        "rabais", "expertise", "convention reglementee", "autorisation",
        "approbation", "loyer superieur", "marche", "validation comptable",
    ]
    return (
        (any(marker in query for marker in property_markers) or "convention" in query or "vente" in query)
        and (any(marker in query for marker in related_markers) or "partie liee" in query)
        and any(marker in query for marker in risk_markers)
    )


def is_cash_consulting_evidence_case(query: str) -> bool:
    service_markers = ["consulting", "consultant", "conseil", "honoraires", "prestation externe", "mission", "service"]
    evidence_markers = ["facture", "contrat", "livrable", "rapport", "justificatif", "preuve", "bon de commande"]
    payment_markers = ["especes", "cash", "liquide", "virement", "paiement", "banque"]
    issue_markers = ["deduire", "deductible", "deductibilite", "risque", "controle", "repondre"]
    return (
        any(marker in query for marker in service_markers)
        and any(marker in query for marker in evidence_markers)
        and (any(marker in query for marker in payment_markers) or any(marker in query for marker in issue_markers))
        and not ("retenue a la source" in query and ("non resident" in query or "irpp" in query))
    )


def is_accounting_tax_bridge_case(query: str) -> bool:
    return (
        ("provision" in query or "charge" in query)
        and ("comptable" in query or "comptabilisee" in query or "comptabilite" in query or "ecritures" in query or "traitement" in query)
        and (
            "non deductible" in query
            or "non deductibilite" in query
            or "pas deductible" in query
            or "pas fiscalement deductible" in query
            or "fiscalement deductible" in query
            or "deduction" in query
            or "deductibilite" in query
            or "base fiscale" in query
            or "difference temporaire" in query
            or "impot differe" in query
            or "reintegr" in query
        )
        and ("fiscal" in query or "fiscalement" in query or "fiscaux" in query or "fiscales" in query or "fiscaliste" in query)
    )


def missing_source_row(doc_id: str, title: str) -> dict:
    return {
        "id": f"missing:{doc_id}",
        "doc_id": doc_id,
        "title": title,
        "filename": None,
        "page": None,
        "heading": "",
        "excerpt": "",
        "source_tier": "missing_primary_source",
        "authority": "Source officielle a indexer",
        "year": None,
        "score": 0.0,
        "matched_terms": [],
        "support_level": "missing_source",
    }


def best_precision_source(doc_id: str, terms: list[str], min_matches: int) -> dict | None:
    normalized_terms = [match_key(term) for term in terms if match_key(term)]
    best: dict | None = None
    best_score = -1.0
    for record in load_corpus():
        if record.get("doc_id") != doc_id:
            continue
        haystack = match_key(" ".join([record.get("title", ""), record.get("heading", ""), record.get("text", "")]))
        matched_terms = [term for term in normalized_terms if term and term in haystack]
        if not matched_terms:
            continue
        heading = record.get("heading", "")
        text = record.get("text", "") or ""
        score = len(matched_terms) * 10 + min(len(record.get("text", "") or "") / 1000, 3)
        if re.search(r"article|art\.|chapitre|section|titre|الفصل|باب|القسم", heading, re.I):
            score += 5
        if "................................" in text:
            score -= 12
        if score > best_score:
            best_score = score
            best = {
                "id": record.get("id"),
                "doc_id": doc_id,
                "title": record.get("title") or "Source interne",
                "filename": record.get("filename"),
                "page": record.get("page"),
                "heading": heading,
                "excerpt": compact_excerpt(record.get("text", ""), 1000),
                "source_tier": record.get("source_tier", ""),
                "authority": record.get("authority", ""),
                "year": record.get("year"),
                "score": round(score, 3),
                "matched_terms": matched_terms,
                "support_level": "direct_passage" if len(matched_terms) >= min_matches else "framework_source",
            }
    return best


def semantically_adjust_support_level(message: str, source: dict) -> dict:
    if source.get("support_level") != "direct_passage":
        return source
    query = match_key(message)
    doc_id = source.get("doc_id")
    haystack = match_key(" ".join([
        str(source.get("title") or ""),
        str(source.get("heading") or ""),
        str(source.get("excerpt") or ""),
    ]))

    required_any: list[str] = []
    if "fraude" in query and doc_id == "code_societes_commerciales_2022":
        required_any = [
            "commissaire aux comptes",
            "fraude",
            "irregularite",
            "delit",
            "revelation",
            "alerte",
            "rapport special",
        ]
    elif is_fixed_asset_component_depreciation_case(query) and doc_id in {"nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles", "code_irpp_is_2011"}:
        required_any = ["amortissement", "mise en service", "pret a etre utilise", "composant", "duree d'utilisation", "duree d'utilite"]
    elif is_receivable_subsequent_recovery_case(query) and doc_id in {"nc_01_norme_generale", "ias_37_provisions_passifs_actifs_eventuels", "ias_10_evenements_post_cloture", "code_irpp_is_2011"}:
        required_any = ["creance", "provision", "depreciation", "recouvrement", "evenement posterieur", "cloture"]

    if required_any and not any(term in haystack for term in required_any):
        adjusted = dict(source)
        adjusted["support_level"] = "framework_source"
        adjusted.setdefault("matched_terms", [])
        adjusted["semantic_relevance_warning"] = "direct passage downgraded: excerpt does not match the case issue"
        return adjusted
    return source


def precision_sources_for_case(message: str, fallback_sources: list[dict]) -> list[dict]:
    rules = source_precision_rules(message)
    if not rules:
        return fallback_sources
    selected: list[dict] = []
    fallback_by_doc = {source.get("doc_id"): source for source in fallback_sources if source.get("doc_id")}
    for rule in rules:
        doc_id = str(rule["doc_id"])
        if rule.get("missing"):
            selected.append(missing_source_row(doc_id, str(rule.get("title") or doc_id)))
            continue
        source = best_precision_source(doc_id, list(rule["terms"]), int(rule.get("min_matches") or 1))
        if source is None:
            source = fallback_by_doc.get(doc_id)
        if source is None:
            source_list = legal_sources_by_doc_ids([doc_id])
            source = source_list[0] if source_list else None
        if source is None:
            continue
        if source.get("support_level") != "direct_passage":
            source = dict(source)
            source["support_level"] = "framework_source"
            source.setdefault("matched_terms", [])
        source = semantically_adjust_support_level(message, source)
        selected.append(source)
    return merge_priority_sources(selected, fallback_sources, limit=max(5, len(selected)))


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


def fastpath_document_analysis_without_document_answer(
    message: str,
    context: str,
    intent: str,
    legal_domain: str,
) -> dict | None:
    if intent != "document_analysis" or context.strip():
        return None
    query = match_key(message)
    if not any(term in query for term in ("document", "piece", "dossier", "risques comptables", "risques fiscaux")):
        return None

    sources = legal_sources_by_doc_ids([
        "loi_comptable",
        "nc_01_norme_generale",
        "code_irpp_is_2011",
        "procedures_fiscales_2026",
    ])
    source_lines = summarize_source_titles(sources, limit=4)
    answer = compose_structured_answer(
        "practical_analysis",
        {
            "Reponse": (
                "Je peux faire l'analyse cabinet, mais il manque la piece principale: le document a analyser. "
                "Sans le contenu du document, je ne peux pas identifier de risques propres au dossier sans inventer des faits. "
                "La bonne demarche est donc de recuperer le document, puis de qualifier separement les risques comptables, fiscaux, juridiques et de preuve."
            ),
            "Application pratique": (
                "- Pieces a fournir: document complet, annexes, dates, montants, parties concernees, statut fiscal, contrat, facture et justificatifs de paiement si disponibles.\n"
                "- Risques comptables a examiner apres lecture: cut-off, rattachement charges/produits, immobilisations, provisions, creances douteuses, parties liees et evenements posterieurs.\n"
                "- Risques fiscaux a examiner apres lecture: deductibilite des charges, TVA, retenue a la source, declarations, justificatifs, reintegrations extra-comptables et risques de controle.\n"
                "- Methode: extraire les faits, lister les zones d'incertitude, rattacher chaque conclusion a une source et signaler les informations manquantes.\n"
                "- Conclusion prudente: tant que le document n'est pas fourni, la reponse doit rester une checklist de travail, pas une conclusion client."
            ),
            "Points de vigilance": (
                "- Ne pas donner une conclusion fiscale ou comptable sans avoir lu le document.\n"
                "- Ne pas inventer de taux, article, montant, date ou risque specifique absent du dossier.\n"
                "- Si le document est scanne ou incomplet, verifier l'OCR et demander les pages manquantes avant conclusion."
            ),
            "Sources utilisees": source_lines,
        },
    )
    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "document_analysis",
        "preferred_source": "legal_corpus",
        "response_style": "practical_analysis",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/document-analysis-missing-input",
        "fallback_mode": False,
        "legal_domain": legal_domain,
        "question": message,
    }


def fastpath_document_analysis_with_context_answer(
    message: str,
    context: str,
    intent: str,
    legal_domain: str,
) -> dict | None:
    if intent != "document_analysis" or not context.strip():
        return None
    query = match_key(f"{message}\n{context}")
    if not any(term in query for term in ("document", "piece", "dossier", "risque", "facture", "charge", "vente", "comptable", "fiscal")):
        return None

    sources = legal_sources_by_doc_ids([
        "loi_comptable",
        "nc_01_norme_generale",
        "code_irpp_is_2011",
        "procedures_fiscales_2026",
        "tva_droit_consommation",
    ])
    source_lines = summarize_source_titles(sources, limit=5)
    context_preview = clean_translation_output(context).strip()
    if len(context_preview) > 900:
        context_preview = f"{context_preview[:900].rstrip()}..."
    answer = compose_structured_answer(
        "practical_analysis",
        {
            "Reponse": (
                "Sur la base du contenu fourni, l'analyse doit rester une revue de risques et non une conclusion definitive. "
                f"Le document decrit semble contenir les elements suivants: {context_preview}"
            ),
            "Application pratique": (
                "- Risques comptables: verifier le rattachement des ventes et charges a la bonne periode, l'exhaustivite des factures, la justification des charges, les cut-off, provisions eventuelles et soldes clients/fournisseurs.\n"
                "- Risques fiscaux: identifier les charges sans pieces probantes, la TVA collectee ou deductible, les retenues a la source possibles, les declarations concernees et les reintegrations extra-comptables si une charge n'est pas justifiee.\n"
                "- Preuves a rapprocher: factures, contrats, bons de livraison ou rapports de mission, moyens de paiement, releves bancaires, journaux comptables, declarations fiscales et grand livre.\n"
                "- Conclusion de travail: les factures non justifiees sont le risque principal; elles doivent etre documentees ou isolees avant toute deduction comptable/fiscale client."
            ),
            "Points de vigilance": (
                "- Ne pas deduire fiscalement une charge sans lien avec l'exploitation, facture reguliere et preuve suffisante.\n"
                "- Ne pas recuperer la TVA si la facture ou l'affectation taxable n'est pas suffisamment etablie.\n"
                "- Si le document est un resume, demander les pieces originales avant de chiffrer un ajustement ou une provision."
            ),
            "Sources utilisees": source_lines,
        },
    )
    return {
        "success": True,
        "answer": answer,
        "assumptions": [],
        "next_steps": [],
        "warnings": [],
        "intent": "document_analysis",
        "preferred_source": "legal_corpus",
        "response_style": "practical_analysis",
        "golden_kb_hits": [],
        "sources": sources,
        "model": "internal/document-analysis-context",
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
    treaty_doc_ids = detected_treaty_doc_ids(query)

    if is_cross_border_service_case(query):
        priority_doc_ids = ["tva_droit_consommation", "procedures_fiscales_2026", "code_irpp_is_2011", "loi_finances_2026"]
        if "france" in query or "francais" in query or "francaise" in query:
            priority_doc_ids.extend([
                "convention_fiscale_france_tunisie",
                "convention_fiscale_france_tunisie_texte_1973",
                "boi_france_tunisie_convention_fiscale_2012",
            ])
        elif "vietnam" in query:
            priority_doc_ids.append("convention_fiscale_tunisie_vietnam")
        elif "yemen" in query or "yémen" in query:
            priority_doc_ids.append("convention_fiscale_tunisie_yemen")
        for treaty_doc_id in treaty_doc_ids:
            if treaty_doc_id not in priority_doc_ids:
                priority_doc_ids.append(treaty_doc_id)
        blocked_doc_ids = {
            "code_societes_commerciales_2022",
            "guide_creation_sarl_tunisie",
            "fiscalite_locale",
            "code_commerce_2014",
            "code_obligations_contrats_2015",
        }
    elif is_treaty_overview_query(query) and treaty_doc_ids:
        priority_doc_ids = treaty_doc_ids
        blocked_doc_ids = {
            "loi_comptable",
            "nc_01_norme_generale",
            "nc_03_revenus",
            "nc_04_stocks",
            "nc_05_immobilisations_corporelles",
            "fiscalite_locale",
            "code_societes_commerciales_2022",
        }
    elif ("bofip" in query or "boi-int-cvb" in query or "convention fiscale france tunisie" in query or "convention fiscale france-tunisie" in query) and ("france" in query or "tunisie" in query):
        priority_doc_ids = [
            "boi_france_tunisie_convention_fiscale_2012",
            "convention_fiscale_france_tunisie_texte_1973",
            "convention_fiscale_france_tunisie",
            "code_irpp_is_2011",
            "procedures_fiscales_2026",
        ]
        blocked_doc_ids = {"loi_comptable", "nc_01_norme_generale", "nc_03_revenus", "nc_04_stocks", "nc_05_immobilisations_corporelles"}
    elif is_mixed_dividends_case(query):
        priority_doc_ids = ["code_irpp_is_2011", "loi_finances_2026", "procedures_fiscales_2026"]
        blocked_doc_ids = {"fiscalite_locale", "droits_taxes_hors_codes", "code_commerce_2014"}
    elif is_revenue_cutoff_tva_case(query):
        priority_doc_ids = ["nc_03_revenus", "nc_01_norme_generale", "tva_droit_consommation", "code_irpp_is_2011"]
        blocked_doc_ids = {"audit_resume_gaida_normes_missions", "ias_7_tableau_flux_tresorerie", "fiscalite_locale"}
    elif is_receivable_subsequent_recovery_case(query):
        priority_doc_ids = ["nc_01_norme_generale", "ias_37_provisions_passifs_actifs_eventuels", "ias_10_evenements_post_cloture", "code_irpp_is_2011"]
        blocked_doc_ids = {"fiscalite_locale", "code_commerce_2014", "nct_44_takaful_controle_interne"}
    elif is_fixed_asset_component_depreciation_case(query):
        priority_doc_ids = ["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles", "code_irpp_is_2011", "nc_01_norme_generale"]
        blocked_doc_ids = {
            "droits_taxes_hors_codes",
            "fiscalite_locale",
            "ias_7_tableau_flux_tresorerie",
            "audit_resume_gaida_normes_missions",
            "audit_resume_chakroun_scan",
            "audit_resume_acceptation_controle_qualite",
            "cours_audit_chiheb_ghanmi",
            "audit_controle_qualite_imed_ennouri",
            "cours_audit_imed_ennouri",
        }
    elif is_going_concern_case(query):
        priority_doc_ids = ["cadre_conceptuel_comptable", "nc_01_norme_generale", "audit_resume_gaida_normes_missions", "audit_resume_acceptation_controle_qualite"]
        blocked_doc_ids = {"code_societes_commerciales_2022", "fiscalite_locale", "code_irpp_is_2011"}
    elif is_related_party_property_case(query):
        priority_doc_ids = ["nc_39_parties_liees", "code_societes_commerciales_2022", "code_irpp_is_2011", "audit_resume_gaida_normes_missions"]
        blocked_doc_ids = {"ias_7_tableau_flux_tresorerie", "fiscalite_locale", "tva_droit_consommation"}
    elif is_cash_consulting_evidence_case(query):
        priority_doc_ids = ["loi_comptable", "code_irpp_is_2011", "procedures_fiscales_2026", "nc_01_norme_generale"]
        blocked_doc_ids = {"ias_7_tableau_flux_tresorerie", "audit_resume_gaida_normes_missions", "fiscalite_locale"}
    elif is_accounting_tax_bridge_case(query):
        priority_doc_ids = ["ias_37_provisions_passifs_actifs_eventuels", "nc_14_eventualites_post_cloture", "code_irpp_is_2011", "ias_12_impots_resultat"]
        blocked_doc_ids = {"ias_7_tableau_flux_tresorerie", "fiscalite_locale", "code_commerce_2014"}
    elif coverage_workflow := detect_cabinet_workflow(query):
        priority_doc_ids = list(coverage_workflow.source_doc_ids)
        for treaty_doc_id in reversed(treaty_doc_ids):
            if treaty_doc_id not in priority_doc_ids:
                priority_doc_ids.insert(0, treaty_doc_id)
        blocked_doc_ids = set()
        if coverage_workflow.family == "procedure_fiscale":
            procedure_priority: list[str] = []
            if "licoba" in query or "comptes bancaires" in query or "comptes postaux" in query or "listecomptes" in query or "xsd" in query:
                procedure_priority.extend([
                    "cahier_charges_licoba_depot_trimestriel_comptes_2026",
                    "schema_licoba_liste_comptes_trimestrielle_2026",
                ])
            if "declaration mensuelle" in query or "mensuelle" in query:
                if "2025" in query:
                    procedure_priority.append("formulaire_declaration_mensuelle_ar_2025")
                if "2026" in query:
                    procedure_priority.append("formulaire_declaration_mensuelle_ar_2026")
                if not any(doc_id.startswith("formulaire_declaration_mensuelle") for doc_id in procedure_priority):
                    procedure_priority.extend(["formulaire_declaration_mensuelle_ar_2026", "formulaire_declaration_mensuelle_ar_2025"])
            if "impot sur la fortune" in query or "impÃ´t sur la fortune" in query or "fortune" in query:
                procedure_priority.append("formulaire_impot_fortune_2026")
            if "declaration is" in query or "impot sur les societes" in query or "impÃ´t sur les sociÃ©tÃ©s" in query:
                procedure_priority.append("formulaire_declaration_is_2026")
            if "teleliquidation" in query or "tÃ©lÃ©liquidation" in query or "adhesion" in query or "adhÃ©sion" in query:
                procedure_priority.append("formulaire_adhesion_teleliquidation_impots")
            if "declaration employeur" in query or "employeur" in query:
                procedure_priority.append("formulaire_declaration_employeur_2025")
            if "plus-value" in query or "plus value" in query or "cession d actions" in query or "cession actions" in query:
                procedure_priority.append("formulaire_plus_value_actions_ar_2025")
            if "declaration impot sur le revenu" in query or "irpp" in query:
                procedure_priority.append("formulaire_declaration_irpp_ar_2025")
            for doc_id in reversed(procedure_priority):
                if doc_id in priority_doc_ids:
                    priority_doc_ids.remove(doc_id)
                priority_doc_ids.insert(0, doc_id)
        if coverage_workflow.family == "paie_social":
            social_priority: list[str] = []
            if any(term in query for term in ("deces", "décès", "survivant", "survivants", "capital deces")):
                social_priority.extend([
                    "cnss_p57_demande_indemnite_deces",
                    "cnss_a144bis_pension_capital_deces_survivants",
                    "cnss_p58_constat_medical_de_deces",
                ])
            if (
                ("pension alimentaire" in query or "rente de divorce" in query or "abandon de famille" in query)
                and "fonds" in query
                and not any(term in query for term in ("effectif", "beneficiaires", "bénéficiaires", "montant", "montants", "depenses", "dépenses", "evolution", "évolution", "2015", "2017", "2020"))
            ):
                social_priority.extend([
                    "cnss_p314_fonds_garantie_pension_alimentaire",
                    "cnss_p314bis_engagement_fonds_garantie_pension_alimentaire",
                ])
            elif "demande de pension" in query or "pension de retraite" in query or "vieillesse" in query or "invalidite" in query or "invalidité" in query or "retraite anticipee" in query or "retraite anticipée" in query:
                social_priority.append("cnss_a144_demande_pension")
            if "fille orpheline" in query or ("orpheline" in query and "sans revenu" in query):
                social_priority.append("cnss_n104_declaration_fille_orpheline")
            if "orphelin" in query and ("infirmit" in query or "maladie incurable" in query):
                social_priority.append("cnss_n102_declaration_orphelin_infirme")
            if "pret logement" in query or "prêt logement" in query:
                social_priority.append("cnss_f56bis_demande_pret_logement")
            if "accident non professionnel" in query or "accidents non professionnels" in query:
                social_priority.append("cnss_n66_declaration_accident_non_professionnel")
            if "non salarie" in query or "non salaries" in query or "non salarié" in query or "non salariés" in query:
                social_priority.append("cnss_p212_affiliation_travailleurs_non_salaries")
            if "etranger" in query or "étranger" in query:
                social_priority.append("cnss_p304_affiliation_travailleurs_tunisiens_etranger")
            if "declaration trimestrielle" in query or "déclaration trimestrielle" in query or "salaires declares" in query or "salaires déclarés" in query:
                if "agricole" in query:
                    social_priority.extend([
                        "cnss_i27_declaration_trimestrielle_salaries_agricoles",
                        "cnss_i28_etat_recapitulatif_salaires_agricoles",
                    ])
                else:
                    social_priority.extend([
                        "cnss_i16_declaration_trimestrielle_salaires",
                        "cnss_i3_etat_recapitulatif_salaires_declares",
                    ])
            if "salaire unique" in query or "majoration" in query:
                social_priority.append("cnss_c084_majoration_salaire_unique")
            if "enfant handicape" in query or "enfant handicapé" in query or "maladie incurable" in query or "infirmit" in query:
                social_priority.append("cnss_n101_declaration_enfant_handicape")
            if "pret universitaire" in query or "prêt universitaire" in query:
                social_priority.append("cnss_f52_demande_pret_universitaire")
            if "ayant droit" in query or "ayants droit" in query or "enfants a charge" in query or "parents a charge" in query:
                social_priority.append("cnss_p100_inscription_ayants_droit")
            if "immatriculation" in query and ("etudiant" in query or "étudiant" in query or "stagiaire" in query or "diplome" in query or "diplômé" in query):
                social_priority.append("cnss_p112_immatriculation_etudiant_stagiaire_diplome")
            if "inscription" in query and ("travailleur salarie" in query or "travailleur salarié" in query or "salarie" in query or "salarié" in query):
                social_priority.append("cnss_n45_inscription_travailleur_salarie")
            if "attestation contentieuse" in query or ("contentieux" in query and "attestation" in query):
                social_priority.append("cnss_n74_attestation_contentieuse")
            if "non assujettissement" in query or "non-assujettissement" in query:
                social_priority.append("cnss_n124_attestation_non_assujettissement")
            if "attestation de solde" in query:
                social_priority.append("cnss_n75_attestation_de_solde")
            if "accident du travail" in query or "accidents du travail" in query or "maladie professionnelle" in query or "maladies professionnelles" in query:
                social_priority.append("cnss_accidents_travail_maladies_professionnelles")
            if "guide de l employeur" in query or "guide de l'employeur" in query or ("secteur non agricole" in query and ("employeur" in query or "cotisation" in query or "declaration" in query)):
                social_priority.append("cnss_guide_employeur_secteur_non_agricole")
            if "compte bancaire" in query or "comptes bancaires" in query or "rib" in query or "bureau regional" in query or "bureau local" in query:
                social_priority.append("cnss_liste_comptes_bancaires_bureaux_regionaux")
            if "autorisation de debit" in query or "autorisation de débit" in query or "prelevement" in query or "prélèvement" in query:
                social_priority.append("cnss_autorisation_debit_bancaire_postal")
            if "regime complementaire des pensions" in query or "régime complémentaire des pensions" in query or "rcp" in query or "retraite complementaire" in query:
                social_priority.append("cnss_affiliation_regime_complementaire_pensions")
            if "service sms" in query or ("sms" in query and "cnss" in query):
                social_priority.append("cnss_flyer_sms")
            if "presentation cnss" in query or "présentation cnss" in query or "missions de la cnss" in query or "caisse nationale de securite sociale" in query:
                social_priority.append("cnss_presentation_institutionnelle")
            if "prets sociaux" in query or "prêts sociaux" in query:
                if "2010" in query and "2020" in query:
                    social_priority.append("cnss_prets_sociaux_nombre_montants_2010_2020")
                if ("effectif" in query or "effectifs" in query or "beneficiaires" in query or "bénéficiaires" in query) and "2000" in query and "2020" in query:
                    social_priority.append("cnss_prets_sociaux_effectifs_nature_2000_2020")
                if ("montant" in query or "montants" in query or "depenses" in query or "dépenses" in query) and "2000" in query and "2020" in query:
                    social_priority.append("cnss_prets_sociaux_montants_nature_2000_2020")
                if "2000" in query:
                    social_priority.append("cnss_prets_sociaux_effectifs_montants_2000")
                if "2020" in query:
                    social_priority.append("cnss_prets_sociaux_effectifs_montants_2020")
            if "fonds de garantie" in query and ("pension alimentaire" in query or "rente de divorce" in query or "divorce" in query):
                if "2015" in query or "2020" in query or "evolution" in query or "évolution" in query:
                    social_priority.append("cnss_fonds_garantie_pension_divorce_2015_2020")
                if "effectif" in query or "beneficiaires" in query or "bénéficiaires" in query:
                    social_priority.append("cnss_fonds_garantie_effectif_2017")
                if "montant" in query or "montants" in query or "depenses" in query or "dépenses" in query:
                    social_priority.append("cnss_fonds_garantie_montants_2017")
            if ("sommaire" in query and "2020" in query and "cnss" in query) or ("statistiques" in query and "2020" in query and "cnss" in query):
                social_priority.append("cnss_sommaire_statistique_2020")
            if ("bilan" in query or "etat de resultat" in query or "état de résultat" in query or "flux de tresorerie" in query or "flux de trésorerie" in query) and "cnss" in query:
                social_priority.append("cnss_publication_financiere_2018")
            if ("evolution des cotisations" in query or "évolution des cotisations" in query or "cotisations cnss" in query) and ("2000" in query or "2020" in query):
                social_priority.append("cnss_evolution_cotisations_2000_2020")
            if ("evolution des depenses" in query or "évolution des dépenses" in query or "depenses de prestations" in query or "dépenses de prestations" in query or "prestations servies" in query) and ("2000" in query or "2020" in query):
                social_priority.append("cnss_evolution_depenses_prestations_2000_2020")
            if "prestations familiales" in query and "2020" in query:
                social_priority.append("cnss_prestations_familiales_2020")
            if ("prestations en especes" in query or "prestations en espèces" in query or "assurances sociales" in query or "capital deces" in query or "capital décès" in query) and "2020" in query:
                social_priority.append("cnss_prestations_assurances_sociales_especes_2020")
            if ("depenses de pension" in query or "dépenses de pension" in query or "les pensions" in query) and "2020" in query:
                social_priority.append("cnss_depenses_pensions_regime_nature_2020")
            if ("effectif des assures sociaux" in query or "effectif des assur" in query or ("assures sociaux" in query and "pensionnes" in query)) and ("2000" in query or "2020" in query):
                social_priority.append("cnss_evolution_effectif_assures_sociaux_2000_2020")
            if ("assures sociaux actifs" in query or ("assur" in query and "sociaux actifs" in query)) and ("regime" in query or "rÃ©gime" in query):
                social_priority.append("cnss_repartition_assures_actifs_regime_2000_2020")
            if "titulaires de pensions" in query and ("regime" in query or "rÃ©gime" in query):
                social_priority.append("cnss_repartition_titulaires_pensions_regime_2000_2020")
            if "titulaires de pensions" in query and ("nature" in query or "orphelins" in query or "conjoints survivants" in query):
                social_priority.append("cnss_repartition_titulaires_pensions_nature_2000_2020")
            if "rapport demographique" in query or "rapport dÃ©mographique" in query:
                social_priority.append("cnss_rapport_demographique_2000_2020")
            if ("effectif des employeurs" in query or ("employeurs" in query and "secteur" in query)) and ("2000" in query or "2020" in query):
                social_priority.append("cnss_evolution_effectif_employeurs_2000_2020")
            if ("employeurs par regime" in query or "employeurs par rÃ©gime" in query or ("repartition employeurs" in query and ("regime" in query or "rÃ©gime" in query))) and ("2000" in query or "2020" in query):
                social_priority.append("cnss_repartition_employeurs_regime_2000_2020")
            if ("notes aux etats financiers" in query or "notes aux Ã©tats financiers" in query or "etat2018" in query) and ("2018" in query or "cnss" in query):
                social_priority.append("cnss_notes_etats_financiers_2018")
            if "budget 2022" in query and "cnss" in query:
                social_priority.append("cnss_budget_2022")
            if ("service sms" in query or "85785" in query or ("sms" in query and "cnss" in query)) and ("mandat" in query or "cotisation" in query or "salaire" in query or "85785" in query or "inscrire" in query or "inscription" in query):
                social_priority.append("cnss_service_sms")
            if ("convention bilaterale" in query or "conventions bilaterales" in query or "convention bilatérale" in query or "conventions bilatérales" in query or "tuniso-marocaine" in query or "tuniso-bulgare" in query or "tuniso-tcheque" in query or "tuniso-tchèque" in query) and ("securite sociale" in query or "sécurité sociale" in query or "cnss" in query):
                social_priority.append("cnss_conventions_bilaterales_securite_sociale_2017")
            if ("administration plus proche" in query or "maison de service" in query or "maisons de service" in query or "service de proximite" in query or "service de proximité" in query) and "cnss" in query:
                social_priority.append("cnss_maisons_service_administration_proche")
            if ("smig" in query or "smag" in query or "salaire minimum garanti" in query or "salaire minimum agricole" in query) and ("cnss" in query or "2020" in query or "decret" in query or "décret" in query):
                social_priority.append("cnss_smig_smag_2020")
            if ("pret universitaire" in query or "prêt universitaire" in query or "prets universitaires" in query or "prêts universitaires" in query) and ("nouveautes" in query or "nouveautés" in query or "2017" in query or "taux d interet" in query or "taux d'intérêt" in query or "interets de retard" in query):
                social_priority.append("cnss_communique_prets_universitaires_2017")
            tender_exact_01ca = "climatiseur" in query or "01/ca/2020" in query or "01 ca 2020" in query
            tender_exact_it = ("oracle" in query or "systeme d information" in query or "système d information" in query or "pmsi" in query or "informatique" in query) and "cnss" in query
            tender_exact_it_equipment = ("equipements informatiques" in query or "équipements informatiques" in query or "cablage informatique" in query or "câblage informatique" in query or "switch" in query or "video-surveillance" in query or "vidéo-surveillance" in query or "16/2016" in query or "16/2017" in query or "10/ca/2017" in query) and "cnss" in query
            tender_exact_works = ("travaux" in query or "construction" in query or "amenagement" in query or "aménagement" in query or "bureau regional" in query) and "cnss" in query
            tender_linux = ("03/ca/2018" in query or "03 ca 2018" in query or "linux" in query) and "cnss" in query
            tender_mahdia = ("01/ca/2017" in query or "01 ca 2017" in query or ("mahdia" in query and "extension" in query)) and "cnss" in query
            tender_oracle_report = ("20/2017" in query or "20 2017" in query or ("oracle" in query and "report" in query)) and "cnss" in query
            tender_iso22301 = ("09/ca/2017" in query or "09 ca 2017" in query or "iso 22301" in query or "continuite des activites" in query or "continuité des activités" in query) and "cnss" in query
            tender_rolling_stock = ("02/2020" in query or "02 2020" in query or "materiel roulant" in query or "matériel roulant" in query or "voiture de service" in query or "camion fourgon" in query) and "cnss" in query
            tender_si_video_2020 = ("01/si/2020" in query or "01 si 2020" in query or ("video-surveillance" in query and "2020" in query) or ("vidéo-surveillance" in query and "2020" in query)) and "cnss" in query
            if ("appel d offres" in query or "appels d offres" in query or "appel d'offre" in query or "appels d'offre" in query or "appel d’offres" in query or "appels d’offres" in query or "marches publics" in query or "marchés publics" in query or "طلب العروض" in query) and ("cnss" in query or "الصندوق" in query) and not (tender_exact_01ca or tender_exact_it or tender_exact_it_equipment or tender_exact_works or tender_linux or tender_mahdia or tender_oracle_report or tender_iso22301 or tender_rolling_stock or tender_si_video_2020):
                social_priority.extend([
                    "cnss_appels_offres_resultats_ar_2016_2017",
                    "cnss_appels_offres_informatique_2015_2017",
                    "cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017",
                    "cnss_appels_offres_travaux_2015_2017",
                    "cnss_avis_appel_offres_climatiseurs_01ca2020",
                    "cnss_avis_03ca2018_linux_tuneps",
                    "cnss_avis_01ca2017_extension_bureau_mahdia",
                    "cnss_report_ao20_2017_licences_oracle",
                    "cnss_avis_09ca2017_iso22301_continuite_activites",
                    "cnss_ao02_2020_materiel_roulant_tuneps",
                    "cnss_consultation_01si2020_videosurveillance_tuneps",
                ])
            if tender_exact_01ca and "cnss" in query:
                social_priority.append("cnss_avis_appel_offres_climatiseurs_01ca2020")
            if tender_exact_it_equipment:
                social_priority.append("cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017")
            if tender_exact_it and not (tender_exact_it_equipment or tender_oracle_report):
                social_priority.append("cnss_appels_offres_informatique_2015_2017")
            if tender_exact_works and not tender_mahdia:
                social_priority.append("cnss_appels_offres_travaux_2015_2017")
            if tender_linux:
                social_priority.append("cnss_avis_03ca2018_linux_tuneps")
            if tender_mahdia:
                social_priority.append("cnss_avis_01ca2017_extension_bureau_mahdia")
            if tender_oracle_report:
                social_priority.append("cnss_report_ao20_2017_licences_oracle")
            if tender_iso22301:
                social_priority.append("cnss_avis_09ca2017_iso22301_continuite_activites")
            if tender_rolling_stock:
                social_priority.append("cnss_ao02_2020_materiel_roulant_tuneps")
            if tender_si_video_2020:
                social_priority.append("cnss_consultation_01si2020_videosurveillance_tuneps")
            if ("fiches des services" in query or "delais des services" in query or "délais des services" in query or "services cnss" in query or "قائمة خدمات الصندوق" in query or "آجال الحصول" in query) and ("cnss" in query or "الصندوق" in query):
                social_priority.append("cnss_fiches_services_octobre_2020")
            if ("engagements envers le citoyen" in query or ("engagement" in query and "citoyen" in query) or "service du citoyen" in query or "relations avec le citoyen" in query or "reseau de bureaux" in query or "réseau de bureaux" in query or "bureau regional" in query or "bureaux regionaux" in query or "bureau local" in query or "bureaux locaux" in query) and "cnss" in query:
                social_priority.append("cnss_engagements_citoyen_reseau")
            if social_priority:
                statistical_doc_ids = {
                    "cnss_evolution_cotisations_2000_2020",
                    "cnss_evolution_depenses_prestations_2000_2020",
                    "cnss_prestations_familiales_2020",
                    "cnss_prestations_assurances_sociales_especes_2020",
                    "cnss_depenses_pensions_regime_nature_2020",
                    "cnss_prets_sociaux_nombre_montants_2010_2020",
                    "cnss_prets_sociaux_effectifs_nature_2000_2020",
                    "cnss_prets_sociaux_montants_nature_2000_2020",
                    "cnss_prets_sociaux_effectifs_montants_2000",
                    "cnss_prets_sociaux_effectifs_montants_2020",
                    "cnss_fonds_garantie_pension_divorce_2015_2020",
                    "cnss_fonds_garantie_effectif_2017",
                    "cnss_fonds_garantie_montants_2017",
                    "cnss_sommaire_statistique_2020",
                    "cnss_publication_financiere_2018",
                    "cnss_evolution_effectif_assures_sociaux_2000_2020",
                    "cnss_repartition_assures_actifs_regime_2000_2020",
                    "cnss_repartition_titulaires_pensions_regime_2000_2020",
                    "cnss_repartition_titulaires_pensions_nature_2000_2020",
                    "cnss_rapport_demographique_2000_2020",
                    "cnss_evolution_effectif_employeurs_2000_2020",
                    "cnss_repartition_employeurs_regime_2000_2020",
                    "cnss_notes_etats_financiers_2018",
                    "cnss_budget_2022",
                    "cnss_appels_offres_resultats_ar_2016_2017",
                    "cnss_appels_offres_informatique_2015_2017",
                    "cnss_appels_offres_travaux_2015_2017",
                    "cnss_avis_appel_offres_climatiseurs_01ca2020",
                    "cnss_fiches_services_octobre_2020",
                    "cnss_engagements_citoyen_reseau",
                    "cnss_conventions_bilaterales_securite_sociale_2017",
                    "cnss_maisons_service_administration_proche",
                    "cnss_smig_smag_2020",
                    "cnss_service_sms",
                    "cnss_communique_prets_universitaires_2017",
                    "cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017",
                    "cnss_avis_03ca2018_linux_tuneps",
                    "cnss_avis_01ca2017_extension_bureau_mahdia",
                    "cnss_report_ao20_2017_licences_oracle",
                    "cnss_avis_09ca2017_iso22301_continuite_activites",
                    "cnss_ao02_2020_materiel_roulant_tuneps",
                    "cnss_consultation_01si2020_videosurveillance_tuneps",
                }
                if "formulaire" not in query and "demande" not in query:
                    social_priority = [doc_id for doc_id in social_priority if doc_id in statistical_doc_ids] + [
                        doc_id for doc_id in social_priority if doc_id not in statistical_doc_ids
                    ]
                priority_doc_ids = social_priority + [doc_id for doc_id in priority_doc_ids if doc_id not in set(social_priority)]
        if coverage_workflow.family == "tva":
            blocked_doc_ids = {"code_societes_commerciales_2022", "ias_7_tableau_flux_tresorerie", "fiscalite_locale"}
        elif coverage_workflow.family == "fiscalite_directe":
            blocked_doc_ids = {"ias_7_tableau_flux_tresorerie", "fiscalite_locale"}
        elif coverage_workflow.family == "comptabilite":
            blocked_doc_ids = {"fiscalite_locale", "code_commerce_2014"}
        elif coverage_workflow.family == "audit_cac":
            blocked_doc_ids = {"fiscalite_locale", "tva_droit_consommation"}
        elif coverage_workflow.family == "droit_societes":
            blocked_doc_ids = {"ias_7_tableau_flux_tresorerie", "fiscalite_locale"}
    elif "dividende" in query or "dividendes" in query:
        priority_doc_ids = ["code_irpp_is_2011", "loi_finances_2026", "procedures_fiscales_2026"]
        blocked_doc_ids = {
            "code_societes_commerciales_2022",
            "guide_creation_sarl_tunisie",
            "droits_taxes_hors_codes",
            "fiscalite_locale",
        }
    elif ("prestations de services" in query or "prestation informatique" in query) and ("france" in query or "client etabli" in query or "client francais" in query):
        priority_doc_ids = [
            "tva_droit_consommation",
            "convention_fiscale_france_tunisie",
            "convention_fiscale_france_tunisie_texte_1973",
            "boi_france_tunisie_convention_fiscale_2012",
            "procedures_fiscales_2026",
            "loi_finances_2026",
        ]
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
    merged = merge_priority_sources(priority, filtered, limit=len(priority_doc_ids) if priority_doc_ids else 5)
    return precision_sources_for_case(message, merged)


def fastpath_case_analysis_answer(message: str, intent: str, legal_domain: str, legal_sources: list[dict]) -> dict | None:
    query = match_key(message)
    sources = case_analysis_sources(message, legal_sources)
    source_lines = summarize_source_titles(sources, limit=5)
    precision_note = source_precision_note(sources)
    if precision_note:
        source_lines = f"{source_lines}\n{precision_note}" if source_lines else precision_note
    if not sources:
        return None

    answer: str | None = None
    returned_intent = intent
    returned_domain = legal_domain
    workflow_name = "case_analysis_fastpath"
    facts_summary = compact_excerpt(message, 520)
    france_case = "france" in query or "francais" in query or "francaise" in query
    treaty_label = "convention fiscale France-Tunisie" if france_case else "convention fiscale applicable au pays du client"
    foreign_client_label = "francais" if france_case else "etranger"

    if is_cross_border_service_case(query):
        workflow_name = "level3_multi_domain_case_analysis"
        returned_intent = "legal_basis"
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Ce dossier doit etre traite comme une analyse fiscale transfrontaliere multi-issues, et non comme une simple question IRPP/IS. "
                    f"Les faits transmis doivent etre qualifies sans les remplacer par un cas standard: {facts_summary}. "
                    "L'analyse doit separer au minimum la TVA tunisienne, la retenue a la source ou le risque d'imposition "
                    f"sur le paiement transfrontalier, la {treaty_label}, le risque d'etablissement stable, la facturation et les justificatifs."
                ),
                "Application pratique": (
                    "- TVA: verifier dans le Code de la taxe sur la valeur ajoutee si la prestation est localisee, utilisee ou exploitee en Tunisie ou hors de Tunisie, "
                    "et si le traitement releve d'une exportation de services, d'une exonération ou d'un autre regime. Ne pas fonder cette partie sur le Code IRPP/IS.\n"
                    "- Nature de la remuneration: decomposer la facture entre service informatique, assistance technique, installation, formation, maintenance eventuelle, "
                    "licence de logiciel ou redevance. La qualification peut changer le traitement fiscal.\n"
                    "- Retenue a la source: verifier dans le Code de l'IRPP et de l'IS si le paiement a un non-resident ou la remuneration d'une prestation technique, "
                    "d'une licence ou d'une redevance declenche une retenue; ne pas conclure sur un taux sans article direct.\n"
                    f"- Convention fiscale: verifier obligatoirement la {treaty_label} avant toute conclusion sur retenue, redevances, benefices d'entreprise "
                    "ou etablissement stable.\n"
                    "- Etablissement stable: analyser la duree de presence a l'etranger, la nature de l'installation/formation, les pouvoirs des consultants, "
                    "l'existence d'un chantier ou d'une installation fixe, et les seuils conventionnels applicables. La seule duree indiquee dans le dossier ne suffit pas pour conclure.\n"
                    "- Facturation: verifier les mentions de facture, devise, client etranger, lieu d'execution, description detaillee des prestations, traitement TVA retenu "
                    "et reference documentaire justifiant l'exoneration ou le regime applique.\n"
                    f"- Justificatifs: conserver contrat, commande, facture, preuve du statut et de l'etablissement du client {foreign_client_label}, preuves de paiement, feuilles de mission, "
                    "dates de deplacement, livrables, PV d'installation/formation et ventilation du prix par nature de prestation.\n"
                    "- Informations manquantes: statut TVA du client, clauses contractuelles, propriete ou licence du logiciel, lieu d'utilisation effective, ventilation du prix, "
                    "pouvoirs des consultants, pays de paiement, existence d'un avenant de maintenance et texte exact de la convention fiscale applicable. "
                    "Sans contrat, lieu d'execution, duree de presence ou nature exacte des services, le cabinet ne peut pas conclure le regime fiscal."
                ),
                "Points de vigilance": (
                    "- Ne pas repondre par un cadre IRPP/IS unique: la TVA, la convention fiscale, l'etablissement stable, la facturation et les justificatifs sont des issues distinctes.\n"
                    f"- Ne pas affirmer un taux de retenue, une absence de TVA ou une absence d'etablissement stable sans passage direct du Code TVA, du Code IRPP/IS et de la {treaty_label}.\n"
                    "- Si la convention applicable n'est pas indexee ou si le passage exact manque, la conclusion sur etablissement stable, redevances et retenue doit rester sous reserve professionnelle.\n"
                    "- Si une partie du prix correspond a une licence ou a une redevance logicielle, l'analyse peut differer d'une prestation de services pure."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_mixed_dividends_case(query):
        workflow_name = "shareholder_split_tax_analysis"
        returned_intent = "tax_calculation"
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Cette distribution doit etre analysee beneficiaire par beneficiaire. Faits transmis: {facts_summary}. "
                    "Le dossier ne peut pas recevoir une reponse globale, car les profils de beneficiaires ne portent pas le meme risque fiscal. "
                    "Pour chacun, il faut verifier la retenue a la source, la declaration et le reversement, le certificat ou "
                    f"la preuve de retenue, et pour un non-resident la {treaty_label}."
                ),
                "Application pratique": (
                    "- Personne physique residente: verifier dans le Code de l'IRPP et de l'IS le regime des revenus distribues, la retenue a la source applicable, "
                    "son caractere eventuellement liberatoire ou imputable, et la justification remise au beneficiaire.\n"
                    "- Societe tunisienne ou personne morale residente: verifier si le regime differe selon la qualite de personne morale residente, le traitement dans le resultat fiscal, "
                    "et l'existence d'une retenue ou d'une dispense documentee.\n"
                    f"- Associe non-resident: verifier la retenue interne tunisienne, puis la {treaty_label} avant de retenir un taux, "
                    "une limitation ou une condition de residence beneficiale.\n"
                    "- Declaration et reversement: identifier l'obligation declarative, la periode de reversement et les pieces a conserver pour chaque beneficiaire.\n"
                    "- Certificats et justificatifs: conserver decision de distribution, PV, identite fiscale des beneficiaires, preuve de residence du non-resident, calcul brut/retenue/net et certificat de retenue.\n"
                    "- Informations manquantes: forme exacte des associes, residence fiscale, beneficiaire effectif, convention applicable, article/taux direct, echeance declarative et origine des reserves distribuees."
                ),
                "Points de vigilance": (
                    "- Ne pas appliquer le meme traitement aux trois associes.\n"
                    "- Ne pas affirmer de taux ou d'article tant que le passage direct sur dividendes n'est pas indexe.\n"
                    f"- La {treaty_label} doit etre verifiee pour tout beneficiaire non-resident avant d'arreter une conclusion client."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_revenue_cutoff_tva_case(query):
        workflow_name = "revenue_cutoff_tva_case"
        returned_intent = "accounting_treatment"
        returned_domain = "comptabilite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Un contrat annuel de maintenance paye d'avance doit etre analyse comme un cas de cut-off comptable et fiscal, pas comme une simple definition de TVA. "
                    f"Faits transmis: {facts_summary}. "
                    "Il faut distinguer la date de facturation ou d'encaissement, la periode de service, la part rattachee a 2025, la part rattachee a 2026, "
                    "les produits constates d'avance le cas echeant, le resultat fiscal et l'exigibilite TVA."
                ),
                "Application pratique": (
                    "- Comptabilite: reconnaitre le produit au rythme de la prestation de maintenance rendue; la part non acquise a la cloture doit etre examinee comme produit constate d'avance.\n"
                    "- Cut-off 2025/2026: ventiler le revenu selon la periode couverte par le contrat, et non uniquement selon la date de paiement.\n"
                    "- Fiscalite: verifier si le resultat fiscal suit le rattachement comptable ou si une regle fiscale specifique modifie le traitement.\n"
                    "- TVA: verifier le fait generateur et l'exigibilite selon facture, encaissement ou execution du service d'apres le Code TVA applicable.\n"
                    "- Facturation: rapprocher contrat, facture, periode de couverture, date d'encaissement, conditions de remboursement et obligations de service restantes.\n"
                    "- Informations manquantes: date de debut/fin du contrat, date de facture, date d'encaissement, montant HT/TVA, conditions de resiliation et prestations deja effectuees. "
                    "Si la periode couverte ou la facture manque, ou si la facture est non payee sans information d'exigibilite, le cabinet ne peut pas conclure prudemment sur la ventilation definitive."
                ),
                "Points de vigilance": (
                    "- Ne pas comptabiliser tout le montant en produit de 2025 si une partie remunere des services 2026.\n"
                    "- Ne pas confondre exigibilite TVA et reconnaissance comptable du revenu.\n"
                    "- Documenter la cle de ventilation et conserver le contrat."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_receivable_subsequent_recovery_case(query):
        workflow_name = "receivable_impairment_subsequent_event"
        returned_intent = "tax_calculation"
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Une creance client impayee ou douteuse doit etre analysee en deux temps. Faits transmis: {facts_summary}. "
                    "Il faut d'abord traiter la depreciation/provision a la date de cloture, "
                    "puis le traitement de l'encaissement posterieur comme evenement posterieur ajustant ou non ajustant selon ce qu'il prouve sur la situation existant a la cloture. "
                    "Si un recouvrement posterieur existe, l'exposition residuelle doit etre recalculee; s'il n'existe pas, l'estimation repose davantage sur les indices de recouvrabilite disponibles. "
                    "Il faut distinguer la constatation comptable de la depreciation et la deductibilite fiscale de la provision."
                ),
                "Application pratique": (
                    "- Classer la creance: identifier facture, echeance, anciennete, litige, garanties, relances et risque reel de non-recouvrement a la cloture.\n"
                    "- Anciennete: utiliser le retard, les relances et les litiges comme indices de doute, sans remplacer le jugement par une regle automatique.\n"
                    "- Montant: partir de la creance brute confirmee, tenir compte des encaissements posterieurs eventuels et calculer l'exposition restante avant de chiffrer la depreciation.\n"
                    "- Ecritures: constater ou ajuster la depreciation/provision sur la part estimee non recouvrable; comptabiliser tout encaissement posterieur en diminution de la creance client et revoir la dotation ou reprise necessaire.\n"
                    "- Evaluer la provision: limiter la depreciation a l'exposition restante apres analyse des chances de recouvrement.\n"
                    "- Encaissement apres cloture: determiner s'il confirme une information deja existante a la cloture; dans ce cas il peut ajuster l'estimation. "
                    "S'il resulte d'un evenement nouveau, il peut etre non ajustant mais a divulguer si significatif.\n"
                    "- Fiscalite: verifier les conditions de deductibilite, l'individualisation de la creance, les justificatifs, les actions de recouvrement et le calcul conserve au dossier.\n"
                    "- Documentation: balance agee, relances, correspondances, accord de paiement, preuve d'encaissement posterieur et note de jugement de direction. "
                    "Sans solde exact, balance agee, relances ou actions de recouvrement, le cabinet ne peut pas conclure a une provision fiscalement deductible."
                ),
                "Points de vigilance": (
                    "- Ne pas maintenir une provision brute si un recouvrement posterieur modifie l'exposition restante.\n"
                    "- Ne pas deduire fiscalement une provision globale sans dossier client par client.\n"
                    "- Distinguer clairement preuve posterieure d'une situation existante et evenement nouveau."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_fixed_asset_component_depreciation_case(query):
        workflow_name = "fixed_asset_component_depreciation_case"
        returned_intent = "accounting_treatment"
        returned_domain = "comptabilite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    "Ce dossier doit etre traite comme une immobilisation corporelle avec mise en service progressive et composant significatif. "
                    f"Faits transmis: {facts_summary}. "
                    "La date d'achat ou de facture ne suffit pas a declencher l'amortissement si la machine n'est pas encore prete a etre utilisee. "
                    "Il faut rapprocher acquisition, livraison, installation, tests et mise en production. "
                    "Si la date de production ou de disponibilite correspond a l'utilisation prevue, c'est cette date qui doit etre retenue pour le depart d'amortissement."
                ),
                "Application pratique": (
                    "- Cout d'entree: rattacher au cout de la machine les frais directement necessaires a sa mise en etat de fonctionner, selon les sources comptables applicables.\n"
                    "- Date de depart: distinguer acquisition, livraison, installation, tests et mise en service; l'amortissement commence lorsque l'actif est pret ou disponible pour son utilisation prevue.\n"
                    "- Base amortissable et mode d'amortissement: determiner le cout amortissable, la valeur residuelle eventuelle, la duree d'utilite et le mode d'amortissement coherent avec la consommation des avantages economiques.\n"
                    "- Tests: documenter si les tests jusqu'au 25 octobre conditionnent la disponibilite technique ou s'ils sont seulement des essais de performance apres mise en etat.\n"
                    "- Production: si la production commence seulement apres installation et tests, retenir prudemment cette date comme date probable de mise en service.\n"
                    "- Composants: la piece majeure remplacee tous les 3 ans doit etre analysee separement si sa duree d'utilisation differe de celle de la machine et si son montant est significatif.\n"
                    "- Fiscalite: comparer le traitement comptable avec les regles fiscales d'amortissement, notamment la date de mise en service/exploitation, les taux maximums et les limites de deductibilite.\n"
                    "- Documentation: conserver facture, bon de livraison, PV d installation, PV de tests, PV de mise en service, fiche immobilisation, ventilation composant/principal, durees d'utilite et tableau d'amortissement. "
                    "Sans PV de mise en service, rapport de tests ou preuve que l'actif est pret a fonctionner, le cabinet ne peut pas fixer definitivement le debut d'amortissement."
                ),
                "Points de vigilance": (
                    "- Ne pas router ce cas vers un recueil fiscal hors sujet: la question est d'abord comptable et fiscale sur immobilisations corporelles.\n"
                    "- Ne pas demarrer l'amortissement a la date d'achat par automatisme si la machine n'etait pas prete a fonctionner.\n"
                    "- Ne pas ignorer l'approche par composants lorsque la piece majeure a une duree de remplacement distincte.\n"
                    "- Ne pas confondre date comptable de mise en service et conditions fiscales de deductibilite."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_going_concern_case(query):
        workflow_name = "going_concern_case_analysis"
        returned_intent = "audit"
        returned_domain = "audit"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Ce cas concerne la continuite d'exploitation, pas une definition du commissaire aux comptes. Faits transmis: {facts_summary}. "
                    "Des capitaux propres negatifs, des retards de paiement fournisseurs "
                    "et un financement bancaire non confirme constituent des signaux d'incertitude qui doivent etre analyses par la direction puis audites."
                ),
                "Application pratique": (
                    "- Direction: obtenir l'evaluation de la continuite, le budget de tresorerie, les hypotheses commerciales, le plan de financement et les mesures de redressement.\n"
                    "- Financement bancaire: verifier si l'accord est confirme, conditionnel ou seulement verbal; une promesse non confirmee ne suffit pas.\n"
                    "- Fournisseurs: analyser l'anciennete des dettes, les plans d'echelonnement et les risques de rupture d'approvisionnement.\n"
                    "- Etats financiers: verifier si les notes decrivent correctement les incertitudes significatives et les hypotheses retenues.\n"
                    "- Refus ou absence d'information: si la direction refuse les disclosures, ne fournit pas de budget de tresorerie, de piece justificative ou de preuves suffisantes, l'auditeur ne peut pas conclure sans diligences complementaires.\n"
                    "- Audit: effectuer des procedures sur flux de tresorerie, evenements posterieurs, confirmations bancaires, covenants, plans de direction et coherence des hypotheses.\n"
                    "- Opinion: si les informations sont insuffisantes ou trompeuses, analyser l'impact possible sur le rapport et l'opinion avant de signer."
                ),
                "Points de vigilance": (
                    "- Ne pas conclure a la continuite seulement parce que la direction espere un financement.\n"
                    "- Les disclosures sont centrales: une incertitude significative mal presentee peut affecter le rapport.\n"
                    "- Documenter les jugements et les elements probants."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_related_party_property_case(query):
        workflow_name = "related_party_transaction_case"
        returned_intent = "legal_basis"
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"La transaction avec un gerant, associe, actionnaire ou autre partie liee doit etre analysee selon ses faits reels: {facts_summary}. "
                    "Une vente, location ou cession a un prix different de la valeur de marche doit etre analysee comme une transaction avec partie liee "
                    "et comme un risque fiscal potentiel. L'analyse doit couvrir la valeur de marche, l'information sur parties liees, l'acte anormal de gestion ou distribution dissimulee, "
                    "les autorisations societaires, le risque de redressement et les diligences d'audit."
                ),
                "Application pratique": (
                    "- Valeur: obtenir expertise independante, comparables, base de valorisation et justification du prix.\n"
                    "- Parties liees: identifier la relation, les conditions de la transaction et l'information a fournir dans les etats financiers.\n"
                    "- Fiscalite: verifier le risque de rehaussement, avantage occulte, acte anormal de gestion ou distribution dissimulee si l'ecart de prix n'est pas justifie.\n"
                    "- Droit des societes: verifier l'approbation, la procedure de convention reglementee ou l'autorisation applicable selon la forme sociale.\n"
                    "- Audit/gouvernance: communiquer le risque, evaluer l'incidence sur les comptes, les disclosures et l'opinion si l'operation est significative.\n"
                    "- Conclusion: sans documentation de prix, expertise, contrat, autorisation ou approbation lorsque requis, le cabinet ne peut pas valider l'operation comme une transaction ordinaire."
                ),
                "Points de vigilance": (
                    "- Ne pas accepter le prix contractuel sans preuve de juste valeur.\n"
                    "- Ne pas traiter l'operation comme une vente ordinaire si le dirigeant est partie liee.\n"
                    "- Les consequences fiscales exactes exigent les articles directs et les pieces de valorisation."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_cash_consulting_evidence_case(query):
        workflow_name = "expense_deductibility_evidence_case"
        returned_intent = "tax_calculation"
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Pour une charge de conseil, honoraires ou prestation externe, il faut partir des faits transmis: {facts_summary}. "
                    "Avec seulement une facture de consulting et un paiement en especes, la deductibilite ne peut pas etre confirmee prudemment. "
                    "Il faut prouver la realite du service, l'interet de l'entreprise, la documentation contractuelle, les livrables et la tracabilite du paiement."
                ),
                "Application pratique": (
                    "- Realite du service: demander contrat, bon de commande, rapport de mission, livrables, emails, planning, preuve d'intervention et validation interne.\n"
                    "- Interet de l'entreprise: rattacher la charge a l'activite, au besoin economique et au benefice attendu.\n"
                    "- Facture: verifier l'identite du prestataire, matricule fiscal, description precise, date, montant, TVA et coherence avec les livrables.\n"
                    "- Paiement: distinguer paiement en especes, liquide, cash, virement bancaire ou paiement bancaire; le cash augmente le risque de rejet, alors qu'un virement bancaire ne remplace pas les preuves de service.\n"
                    "- Partie liee et prix: si le prestataire est une partie liee, verifier en plus le prix de marche, l'interet social et les autorisations applicables.\n"
                    "- Fiscalite: examiner la deductibilite dans le Code de l'IRPP/IS, les conditions de justification et les risques de rejet en controle.\n"
                    "- Conclusion prudente: sans preuves autres que la facture et le cash, preparer une reserve et demander les justificatifs avant deduction."
                ),
                "Points de vigilance": (
                    "- Ne pas router ce cas vers une simple analyse de tresorerie: la question porte sur la deductibilite et la preuve.\n"
                    "- Une facture seule ne prouve pas toujours la prestation.\n"
                    "- Documenter pourquoi la charge est necessaire et normale pour l'entreprise."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif is_accounting_tax_bridge_case(query):
        workflow_name = "accounting_tax_bridge_case"
        returned_intent = "tax_calculation"
        returned_domain = "fiscalite"
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Une provision ou charge comptable doit etre analysee en pont comptabilite-fiscalite selon les faits transmis: {facts_summary}. "
                    "Elle peut etre comptabilisee tout en n'etant pas fiscalement deductible. Il faut separer le traitement comptable, fonde sur l'existence d'une obligation "
                    "ou d'un risque estimable, du traitement fiscal, qui peut imposer une reintegration extra-comptable."
                ),
                "Application pratique": (
                    "- Comptabilite: verifier si la provision repond aux criteres de reconnaissance, d'estimation fiable et de rattachement a l'exercice.\n"
                    "- Fiscalite: verifier si la provision entre dans une categorie deductible; sinon elle doit etre reintegree extra-comptablement dans le resultat fiscal.\n"
                    "- Impot differe: analyser seulement si le referentiel applique et les sources disponibles permettent de traiter une difference temporaire.\n"
                    "- Base fiscale: si la direction ne fournit aucune base fiscale, aucun article fiscal direct ou si la deduction n'est pas documentee, le cabinet ne peut pas accepter le traitement fiscal comme acquis.\n"
                    "- Nature du risque: distinguer litige, garantie, charge estimee, difference temporaire et reintegration definitive, car les consequences comptables et fiscales ne sont pas les memes.\n"
                    "- Documentation: conserver note de calcul, fait generateur, estimation, decision de direction, pieces justificatives, traitement fiscal retenu et justification de la reintegration.\n"
                    "- Informations manquantes: nature de la provision, exercice, base de calcul, texte fiscal applicable et referentiel comptable utilise."
                ),
                "Points de vigilance": (
                    "- Ne pas confondre comptabilisation et deductibilite fiscale.\n"
                    "- Rester strictement sur le pont comptabilite-fiscalite de la provision traitee.\n"
                    "- Toute conclusion fiscale doit etre rattachee a l'article applicable."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif coverage_workflow := detect_cabinet_workflow(query):
        workflow_name = coverage_workflow.id
        returned_intent = coverage_workflow.intent
        returned_domain = coverage_workflow.legal_domain
        issues = "\n".join(f"- {item}" for item in coverage_workflow.issue_split)
        missing = "\n".join(f"- {item}" for item in coverage_workflow.missing_facts)
        answer = compose_structured_answer(
            "practical_analysis",
            {
                "Reponse": (
                    f"Ce dossier releve de la famille cabinet suivante: {coverage_workflow.title}. "
                    f"Faits transmis: {facts_summary}. "
                    "La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, "
                    "rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct."
                ),
                "Application pratique": (
                    "Issues a traiter:\n"
                    f"{issues}\n\n"
                    "Faits et pieces a completer avant conclusion client:\n"
                    f"{missing}\n\n"
                    "Methode de reponse: appliquer les sources prioritaires de la famille, distinguer les impacts comptables, fiscaux, "
                    "societaires, audit ou procedure selon le cas, puis indiquer ce qui est directement supporte par un passage direct et ce qui reste source-cadre. "
                    "Les justificatifs doivent etre controles avant toute conclusion client."
                ),
                "Points de vigilance": (
                    "- Ne pas inventer de taux, delai, article, seuil ou conclusion juridique sans passage direct.\n"
                    "- Si les faits sont incomplets, conclure prudemment: le cabinet ne peut pas trancher sans les informations manquantes.\n"
                    "- Si une source exacte manque, marquer la limite comme source-cadre ou source manquante au lieu de presenter une certitude.\n"
                    "- Adapter la reponse au profil du contribuable, au resident/non-resident, aux dates, montants, pieces et contradictions du dossier."
                ),
                "Sources utilisees": source_lines,
            },
        )

    elif "dividende" in query or "dividendes" in query:
        returned_intent = "tax_calculation"
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
        "workflow": workflow_name,
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
        r"en premi[Ãèe]re analyse,\s*le point doit [Ãêe]tre rattach[Ãée] principalement au cadre suivant",
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
                "heading": row.get("heading") or "",
                "support_level": row.get("support_level") or "unclassified",
                "matched_terms": row.get("matched_terms") or [],
                "excerpt_preview": compact_excerpt(row.get("excerpt", ""), 280) if row.get("excerpt") else "",
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
    if not (os.getenv("SPACE_ID") or os.getenv("HF_SPACE_ID") or os.getenv("SPACE_REPOSITORY")):
        return None
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
    if os.getenv("SPACE_ID") or os.getenv("HF_SPACE_ID") or os.getenv("SPACE_REPOSITORY"):
        live_revision = public_space_revision()
        if live_revision:
            return live_revision
    return config.APP_REVISION or "unknown"


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
        "cabinet_coverage": cabinet_coverage_status(),
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
    missing_document_fastpath = fastpath_document_analysis_without_document_answer(
        message=message,
        context=context_block,
        intent=query_intent,
        legal_domain=legal_domain,
    )
    if missing_document_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": missing_document_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": missing_document_fastpath.get("preferred_source"),
                "response_style": missing_document_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(missing_document_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": missing_document_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            missing_document_fastpath,
            request,
            workflow="document_analysis_missing_input",
            case_analysis_enabled=True,
            retrieval_domains=[legal_domain],
            selected_sources=missing_document_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=missing_document_fastpath.get("model"),
        )
    document_context_fastpath = fastpath_document_analysis_with_context_answer(
        message=message,
        context=context_block,
        intent=query_intent,
        legal_domain=legal_domain,
    )
    if document_context_fastpath:
        append_accounting_chat_log(
            {
                "request_id": request_id,
                "kind": "accounting_chat",
                "message": message[:500],
                "language": language,
                "history_count": len(request.history or []),
                "intent": document_context_fastpath.get("intent"),
                "legal_domain": legal_domain,
                "preferred_source": document_context_fastpath.get("preferred_source"),
                "response_style": document_context_fastpath.get("response_style"),
                "provider_attempts": [],
                "golden_kb_refs": [],
                "retrieved_legal_refs": accounting_log_doc_refs(document_context_fastpath.get("sources") or []),
                "result": "fastpath",
                "model": document_context_fastpath.get("model"),
                "fallback_used": False,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            }
        )
        return finalize_accounting_response(
            document_context_fastpath,
            request,
            workflow="document_analysis_context",
            case_analysis_enabled=True,
            retrieval_domains=[legal_domain],
            selected_sources=document_context_fastpath.get("sources") or [],
            fallback_used=False,
            generator_path=document_context_fastpath.get("model"),
        )
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
            workflow=case_analysis_fastpath.get("workflow") or "case_analysis_fastpath",
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
