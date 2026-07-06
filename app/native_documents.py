from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

import fitz
import pytesseract
from PIL import Image
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import load_workbook
from openpyxl.styles import Alignment
from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pytesseract import Output
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .renderer import arabic_display, register_pdf_font


TranslateBatch = Callable[[list[str], str], Awaitable[list[str]]]


@dataclass
class TextItem:
    text: str
    setter: Callable[[str], None]


def comparable_token(value: str) -> str:
    return re.sub(r"[,\s\u00A0]", "", str(value or "").upper())


def protected_tokens(source: str) -> list[str]:
    patterns = [
        r"\b(?:DTU|NF|ISO|API|PDF|PPTX|DOCX|XLSX|HTML|TVA|HT|TTC|IRPP|IS)\b(?:\s*\d+(?:[.,-]\d+)*)?",
        r"\bEurocode\s*\d+(?:[.,-]\d+)*",
        r"\b(?:article|art\.|loi|décret|decret|ordonnance|arrêté|arrete|clause|section)\s*[A-Z]?\d+(?:[.-]\d+)*",
        r"\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}",
        r"\d[\d\s.,]*(?:\s?(?:€|\$|%|HT|TTC|TVA))+",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, source or "", flags=re.I):
            token = match.group(0).strip()
            key = comparable_token(token)
            if token and key not in seen:
                seen.add(key)
                out.append(token)
    return out


def numeric_tokens(value: str) -> list[str]:
    return re.findall(r"\d[\d\s.,]*(?:\s?(?:%|€|\$|HT|TTC))?", value or "", flags=re.I)


def preserve_numeric_tokens(source: str, translated: str) -> str:
    source_nums = numeric_tokens(source)
    if not source_nums:
        return translated
    index = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal index
        replacement = source_nums[index] if index < len(source_nums) else match.group(0)
        index += 1
        return replacement

    return re.sub(r"\d[\d\s.,]*(?:\s?(?:%|€|\$|HT|TTC))?", repl, translated or "", flags=re.I)


def restore_missing_protected_tokens(source: str, translated: str) -> str:
    target_key = comparable_token(translated)
    missing = [token for token in protected_tokens(source) if comparable_token(token) not in target_key]
    if not missing:
        return translated
    suffix = "، ".join(missing)
    return f"{translated} ({suffix})" if translated else suffix


def repair_arabic_terms(source: str, translated: str) -> str:
    value = translated or ""
    replacements = [
        (r"الاكتشاف", "المعاينة"),
        (r"الاضطرابات", "العيوب"),
        (r"تآكل التعزيزات", "تآكل حديد التسليح"),
        (r"المواصفات الفنية", "دفتر الشروط الفنية"),
        (r"المؤسسة", "الهيكل الإنشائي"),
        (r"الدرجة", "البند"),
        (r"غير شاملة الضريبة", "دون احتساب الرسوم"),
        (r"إصلاح التشخيص", "التشخيص ← الإصلاح"),
        (r"التشخيص\s*→\s*الإصلاح", "التشخيص ← الإصلاح"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    return value


def finalize_native_translation(source: str, translated: str) -> str:
    value = (translated or "").strip() or source
    if re.search(r"[\u0600-\u06FF]", value):
        value = repair_arabic_terms(source, value)
    value = preserve_numeric_tokens(source, value)
    value = restore_missing_protected_tokens(source, value)
    return value.strip()


def apply_docx_rtl(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    ppr = paragraph._p.get_or_add_pPr()
    bidi = ppr.find(qn("w:bidi"))
    if bidi is None:
        bidi = OxmlElement("w:bidi")
        ppr.append(bidi)
    bidi.set(qn("w:val"), "1")
    for run in paragraph.runs:
        run.font.rtl = True


def should_translate(value: str | None) -> bool:
    text = (value or "").strip()
    if len(text) < 2:
        return False
    if text.startswith("="):
        return False
    if re.fullmatch(r"[\W\d_]+", text, flags=re.UNICODE):
        return False
    if re.fullmatch(r"https?://\S+|\S+@\S+\.\S+", text, flags=re.I):
        return False
    return True


def replace_paragraph_text(paragraph, translated: str) -> None:
    if not paragraph.runs:
        paragraph.add_run(translated)
    else:
        paragraph.runs[0].text = translated
        for run in paragraph.runs[1:]:
            run.text = ""
    if re.search(r"[\u0600-\u06FF]", translated or ""):
        apply_docx_rtl(paragraph)


def iter_docx_paragraphs(container):
    for paragraph in getattr(container, "paragraphs", []):
        yield paragraph
    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                yield from iter_docx_paragraphs(cell)


def collect_docx_items(document: Document) -> list[TextItem]:
    items: list[TextItem] = []
    containers = [document]
    for section in document.sections:
        containers.extend([section.header, section.footer])

    for container in containers:
        for paragraph in iter_docx_paragraphs(container):
            text = paragraph.text
            if should_translate(text):
                items.append(TextItem(text=text, setter=lambda value, p=paragraph: replace_paragraph_text(p, value)))
    return items


def replace_pptx_paragraph_text(paragraph, translated: str) -> None:
    text_frame = getattr(getattr(paragraph, "_parent", None), "text_frame", None)
    if text_frame is not None:
        text_frame.word_wrap = True
        try:
            text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
    if not paragraph.runs:
        paragraph.add_run().text = translated
    else:
        paragraph.runs[0].text = translated
        for run in paragraph.runs[1:]:
            run.text = ""
    if re.search(r"[\u0600-\u06FF]", translated or ""):
        paragraph.alignment = PP_ALIGN.RIGHT
        ppr = paragraph._p.get_or_add_pPr()
        ppr.set("rtl", "1")
        for run in paragraph.runs:
            run.font.name = "Arial"
            try:
                if run.font.size:
                    run.font.size = int(run.font.size * 0.9)
            except Exception:
                pass


def collect_pptx_shape_items(shape) -> list[TextItem]:
    items: list[TextItem] = []
    if getattr(shape, "shape_type", None) == 6:
        for subshape in shape.shapes:
            items.extend(collect_pptx_shape_items(subshape))
        return items

    if getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            text = "".join(run.text for run in paragraph.runs).strip() or paragraph.text.strip()
            if should_translate(text):
                items.append(TextItem(text=text, setter=lambda value, p=paragraph: replace_pptx_paragraph_text(p, value)))

    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip() or paragraph.text.strip()
                    if should_translate(text):
                        items.append(TextItem(text=text, setter=lambda value, p=paragraph: replace_pptx_paragraph_text(p, value)))
    return items


def collect_pptx_items(presentation: Presentation) -> list[TextItem]:
    items: list[TextItem] = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            items.extend(collect_pptx_shape_items(shape))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            for paragraph in notes.paragraphs:
                text = "".join(run.text for run in paragraph.runs).strip() or paragraph.text.strip()
                if should_translate(text):
                    items.append(TextItem(text=text, setter=lambda value, p=paragraph: replace_pptx_paragraph_text(p, value)))
    return items


def collect_xlsx_items(workbook) -> list[TextItem]:
    items: list[TextItem] = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and should_translate(cell.value):
                    items.append(TextItem(text=cell.value, setter=lambda value, c=cell: setattr(c, "value", value)))
    return items


async def apply_translations(items: list[TextItem], translate_batch: TranslateBatch, context: str) -> int:
    if not items:
        return 0
    source_texts = [item.text for item in items]
    translated = await translate_batch(source_texts, context)
    if len(translated) != len(items):
        raise ValueError("Native document translation returned a mismatched segment count.")
    for item, value in zip(items, translated):
        item.setter(finalize_native_translation(item.text, value))
    return len(items)


async def translate_docx_native(content: bytes, translate_batch: TranslateBatch) -> tuple[bytes, str, str, int]:
    document = Document(io.BytesIO(content))
    changed = await apply_translations(collect_docx_items(document), translate_batch, "DOCX native in-place translation")
    stream = io.BytesIO()
    document.save(stream)
    return (
        stream.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
        changed,
    )


async def translate_pptx_native(content: bytes, translate_batch: TranslateBatch) -> tuple[bytes, str, str, int]:
    presentation = Presentation(io.BytesIO(content))
    changed = await apply_translations(collect_pptx_items(presentation), translate_batch, "PPTX native in-place translation")
    stream = io.BytesIO()
    presentation.save(stream)
    return (
        stream.getvalue(),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
        changed,
    )


async def translate_xlsx_native(content: bytes, translate_batch: TranslateBatch) -> tuple[bytes, str, str, int]:
    workbook = load_workbook(io.BytesIO(content))
    changed = await apply_translations(collect_xlsx_items(workbook), translate_batch, "XLSX native in-place translation")
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and re.search(r"[\u0600-\u06FF]", cell.value):
                    current = cell.alignment.copy()
                    cell.alignment = Alignment(
                        horizontal="right",
                        vertical=current.vertical,
                        wrap_text=True,
                        text_rotation=current.text_rotation,
                        shrink_to_fit=current.shrink_to_fit,
                        indent=current.indent,
                        readingOrder=2,
                    )
    stream = io.BytesIO()
    workbook.save(stream)
    return (
        stream.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
        changed,
    )


def group_ocr_lines(data: dict, scale: float) -> list[dict]:
    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, text in enumerate(data.get("text", [])):
        if not should_translate(text):
            continue
        try:
            conf = float(data.get("conf", ["-1"])[index])
        except (TypeError, ValueError):
            conf = -1
        if conf >= 0 and conf < 35:
            continue
        key = (
            int(data.get("block_num", [0])[index]),
            int(data.get("par_num", [0])[index]),
            int(data.get("line_num", [0])[index]),
        )
        grouped.setdefault(key, []).append(index)

    lines: list[dict] = []
    for indexes in grouped.values():
        words = [str(data["text"][index]).strip() for index in indexes if str(data["text"][index]).strip()]
        if not words:
            continue
        left = min(int(data["left"][index]) for index in indexes) / scale
        top = min(int(data["top"][index]) for index in indexes) / scale
        right = max(int(data["left"][index]) + int(data["width"][index]) for index in indexes) / scale
        bottom = max(int(data["top"][index]) + int(data["height"][index]) for index in indexes) / scale
        text = " ".join(words)
        if should_translate(text):
            lines.append({"text": text, "left": left, "top": top, "right": right, "bottom": bottom})
    return lines


def collect_pdf_visual_items(content: bytes) -> tuple[list[dict], list[dict]]:
    scale = 2.5
    pages: list[dict] = []
    items: list[dict] = []
    with fitz.open(stream=content, filetype="pdf") as pdf:
        for page_index, page in enumerate(pdf):
            rect = page.rect
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image_bytes = pixmap.tobytes("png")
            image = Image.open(io.BytesIO(image_bytes))
            data = pytesseract.image_to_data(
                image,
                lang="ara+fra+eng",
                config="--psm 6 -c preserve_interword_spaces=1",
                output_type=Output.DICT,
            )
            lines = group_ocr_lines(data, scale)
            page_record = {
                "width": float(rect.width),
                "height": float(rect.height),
                "image": image_bytes,
                "lines": lines,
            }
            pages.append(page_record)
            for line in lines:
                items.append({"page": page_index, "line": line, "text": line["text"]})
    return pages, items


def draw_wrapped_overlay(pdf, text: str, box: dict, page_height: float, font_name: str) -> None:
    x = box["left"]
    y_top = box["top"]
    width = max(30, box["right"] - box["left"])
    height = max(12, box["bottom"] - box["top"])
    rtl = bool(re.search(r"[\u0600-\u06FF]", text or ""))
    font_size = max(6, min(13, height * 0.72))
    max_chars = max(8, int(width / max(font_size * 0.42, 3)))
    chunks = [text[index:index + max_chars] for index in range(0, len(text), max_chars)] or [text]

    y = page_height - y_top - font_size
    for chunk in chunks[: max(1, int(height // max(font_size, 1)) + 1)]:
        pdf.setFont(font_name, font_size)
        if rtl:
            pdf.drawRightString(x + width, y, arabic_display(chunk))
        else:
            pdf.drawString(x, y, chunk)
        y -= font_size + 2


async def translate_pdf_visual_native(content: bytes, translate_batch: TranslateBatch) -> tuple[bytes, str, str, int]:
    pages, items = collect_pdf_visual_items(content)
    if not items:
        raise ValueError("No OCR text blocks found for visual PDF translation.")
    translated = await translate_batch([item["text"] for item in items], "PDF visual in-place overlay translation")
    if len(translated) != len(items):
        raise ValueError("Visual PDF translation returned a mismatched segment count.")
    for item, value in zip(items, translated):
        item["line"]["translated"] = finalize_native_translation(item["text"], value)

    stream = io.BytesIO()
    first = pages[0]
    pdf = canvas.Canvas(stream, pagesize=(first["width"], first["height"]))
    font_name = register_pdf_font()
    for page_index, page in enumerate(pages):
        if page_index:
            pdf.setPageSize((page["width"], page["height"]))
        pdf.drawImage(ImageReader(io.BytesIO(page["image"])), 0, 0, width=page["width"], height=page["height"])
        for line in page["lines"]:
            translated_line = (line.get("translated") or "").strip()
            if not translated_line:
                continue
            x = line["left"]
            y = page["height"] - line["bottom"]
            w = max(1, line["right"] - line["left"])
            h = max(1, line["bottom"] - line["top"])
            pdf.setFillColorRGB(1, 1, 1)
            pdf.rect(x - 1, y - 1, w + 2, h + 3, stroke=0, fill=1)
            pdf.setFillColorRGB(0.05, 0.05, 0.05)
            draw_wrapped_overlay(pdf, translated_line, line, page["height"], font_name)
        pdf.showPage()
    pdf.save()
    return stream.getvalue(), "application/pdf", "pdf", len(items)
