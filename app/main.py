from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import config
from .legal_corpus import corpus_status, retrieve_legal_context
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
    legal_sources = retrieve_legal_context(f"{message}\n{context_block}", limit=5)
    legal_context = "\n\n".join(
        "\n".join([
            f"Source: {source['title']} | page {source['page']} | {source.get('heading') or 'extrait'}",
            source["excerpt"],
        ])
        for source in legal_sources
    )
    history_messages = []
    for item in request.history[-10:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = clean_translation_output(str(item.get("content") or "")).strip()
        if content:
            history_messages.append({"role": role, "content": content[:4000]})
    system_prompt = "\n".join([
        "Tu es un assistant IA conversationnel de haut niveau, comparable a ChatGPT ou Claude, mais specialise pour experts-comptables, commissaires aux comptes, auditeurs, fiscalistes, juristes fiscaux et cabinets comptables.",
        "Tu peux discuter librement avec l'utilisateur et l'aider sur: comptabilite generale, fiscalite tunisienne et francophone, lois de finances, TVA, IRPP, IS, retenue a la source, droits d'enregistrement, paie, CNSS, audit, commissariat aux comptes, controle interne, lettrage, rapprochements, bilan, grand livre, declarations, procedures cabinet, analyse de pieces, redaction de notes, normes sectorielles bancaires et OPCVM, et traduction professionnelle quand elle est demandee.",
        "Tu reponds comme un expert de cabinet: clair, direct, pratique, structure, avec raisonnement professionnel et points de controle.",
        "Tu peux aussi repondre a des questions generales si elles aident le travail du cabinet, mais tu ramene toujours la valeur vers l'expertise comptable, fiscale, juridique ou organisationnelle.",
        "Tu verifies les montants, dates, taxes, debits/credits, tiers, periodes et hypotheses avant de conclure.",
        "Si une information manque, dis exactement ce qu'il faut demander au client.",
        "Pour les lois, ne pretend jamais qu'une regle est certaine ou a jour sans source/date. Donne la position probable, les reserves et ce qu'il faut verifier dans le texte officiel.",
        "Les corpus internes actuellement charges contiennent des textes mis a jour autour de 2017; pour une reponse client finale, signale qu'il faut verifier les lois de finances, normes modificatives, interpretations ulterieures, circulaires, et textes sectoriels applicables, notamment en matiere bancaire et OPCVM.",
        "Si des sources internes sont fournies, utilise-les avant ta connaissance generale et cite le titre/page dans la reponse quand c'est pertinent.",
        "Pour la Tunisie, prefere la terminologie locale: TVA, IRPP, IS, retenue a la source, droit de timbre, CNSS, matricule fiscal, regime reel/forfaitaire, liasse fiscale.",
        "Ne reponds pas comme un traducteur sauf si l'utilisateur demande une traduction. Par defaut, agis comme un assistant IA expert-comptable.",
        "Style: professionnel, sans emoji, sans formule marketing, avec des etapes nettes et directement exploitables.",
        "Retourne uniquement un JSON valide avec: answer, assumptions, next_steps, warnings.",
    ])
    user_prompt = "\n\n".join([
        f"Langue de reponse: {language}",
        legal_context and f"Sources internes recuperees dans le corpus fiscal/comptable tunisien:\n{legal_context}",
        context_block and f"Contexte/document fourni:\n{context_block}",
        f"Question du cabinet:\n{message}",
    ]).strip()
    messages = [
        {"role": "system", "content": system_prompt},
        *history_messages,
        {"role": "user", "content": user_prompt},
    ]
    routes = prioritized_translation_routes(f"{message}\n{context_block}", "expert-comptable assistant chat")
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(config.LLM_PROVIDER_TIMEOUT, connect=8.0)) as client:
        for route in routes:
            body = provider_body(route, messages, min(config.LLM_MAX_TOKENS, 2200), json_mode=True)
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
                answer = clean_translation_output(str(parsed.get("answer") or parsed.get("translation") or "")).strip()
                if not answer:
                    raise RuntimeError("Model returned an empty accounting answer.")
                assumptions = parsed.get("assumptions") if isinstance(parsed.get("assumptions"), list) else []
                next_steps = parsed.get("next_steps") if isinstance(parsed.get("next_steps"), list) else []
                warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
                return {
                    "success": True,
                    "answer": answer,
                    "assumptions": [clean_translation_output(str(item)) for item in assumptions],
                    "next_steps": [clean_translation_output(str(item)) for item in next_steps],
                    "warnings": [clean_translation_output(str(item)) for item in warnings],
                    "sources": legal_sources,
                    "model": f"{route['provider']}/{route['model']}",
                }
            except Exception as error:
                last_error = error
                continue
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
