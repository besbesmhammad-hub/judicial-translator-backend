from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import load_workbook
from openpyxl.styles import Alignment
from pptx import Presentation
from pptx.enum.text import PP_ALIGN


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
    if not paragraph.runs:
        paragraph.add_run().text = translated
    else:
        paragraph.runs[0].text = translated
        for run in paragraph.runs[1:]:
            run.text = ""
    if re.search(r"[\u0600-\u06FF]", translated or ""):
        paragraph.alignment = PP_ALIGN.RIGHT
        for run in paragraph.runs:
            run.font.language_id = "ar-SA"


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
