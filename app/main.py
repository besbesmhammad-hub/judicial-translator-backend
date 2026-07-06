from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config
from .native_documents import translate_docx_native, translate_pptx_native, translate_xlsx_native
from .parser import detect_file_format, parse_document
from .renderer import render_document
from .schemas import AnalyzeResponse, TranslateRequest, TranslateResponse
from .skills import ACTIVE_SKILLS, detect_document_kind
from .translator import ProviderCreditError, ProviderRateLimitError, friendly_provider_error, translate_text
import io
import re


SEGMENT_PATTERN = re.compile(r"\[\[\[JT_SEG_(\d{4})\]\]\]([\s\S]*?)(?:\[\[\[/JT_SEG_\1\]\]\]|$)")

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


def build_segment_payload(segments: list[str]) -> str:
    parts = []
    for index, text in enumerate(segments):
        marker = f"{index:04d}"
        parts.append(f"[[[JT_SEG_{marker}]]]\n{text}\n[[[/JT_SEG_{marker}]]]")
    return "\n\n".join(parts)


def segment_batches(segments: list[str], max_chars: int = 1800) -> list[list[tuple[int, str]]]:
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


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "model": config.LLM_MODEL,
        "llm_configured": bool(config.LLM_API_KEY),
        "native_formats": ["pdf", "docx", "pptx", "xlsx", "html", "txt"],
        "keyless_fallbacks_enabled": config.ENABLE_KEYLESS_FALLBACKS,
        "keyless_fallback_providers": ["pollinations"] if config.ENABLE_KEYLESS_FALLBACKS else [],
        "active_skills": ACTIVE_SKILLS,
    }


@app.post("/v1/analyze-file", response_model=AnalyzeResponse)
async def analyze_file(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    text, notes = parse_document(file.filename or "document.txt", content)
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


@app.post("/v1/translate-file", response_model=TranslateResponse)
async def translate_file(
    file: UploadFile = File(...),
    source_lang: str = Form("auto"),
    target_lang: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict:
    content = await file.read()
    text, structure_notes = parse_document(file.filename or "document.txt", content)
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
    filename = file.filename or "document.txt"
    text, structure_notes = parse_document(filename, content)
    file_format = detect_file_format(filename, content)
    detected_kind = detect_document_kind(text)

    async def translate_native_segments(segments: list[str], context: str) -> list[str]:
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
                parsed = [re.sub(r"\[\[\[/?JT_SEG_\d{4}\]\]\]", "", result["translation"]).strip()]
            if parsed is None:
                raise ValueError("The model did not preserve native document segment markers.")
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
    try:
        native_result = None
        if file_format == "docx" and output_format == "docx":
            native_result = await translate_docx_native(content, translate_native_segments)
        elif file_format == "pptx" and output_format == "pptx":
            native_result = await translate_pptx_native(content, translate_native_segments)
        elif file_format == "xlsx" and output_format == "xlsx":
            native_result = await translate_xlsx_native(content, translate_native_segments)

        if native_result is not None:
            content_out, media_type, extension, _changed = native_result
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.rsplit(".", 1)[0]).strip("-") or "document"
            return StreamingResponse(
                io.BytesIO(content_out),
                media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="{safe_name}-translated.{extension}"'},
            )

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
            f"Translated - {filename}",
        )
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.rsplit(".", 1)[0]).strip("-") or "document"
        return StreamingResponse(
            io.BytesIO(content_out),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}-translated.{extension}"'},
        )
    except Exception as error:
        raise provider_http_error(error) from error
