from __future__ import annotations

import io
import re

import fitz
import pytesseract
from PIL import Image, ImageFilter, ImageOps


CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
MEANINGFUL_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+|[\u0600-\u06FF]+")


def normalize_text(value: str) -> str:
    return (
        (value or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\x00", "")
        .replace("\u00a0", " ")
        .replace("\u200f", " ")
        .replace("\u200e", " ")
        .strip()
    )


def meaningful_text(value: str) -> str:
    return "".join(MEANINGFUL_RE.findall(normalize_text(value)))


def text_quality_score(value: str) -> float:
    text = normalize_text(value)
    if not text:
        return -100.0
    total = max(len(text), 1)
    meaningful = meaningful_text(text)
    arabic = len(re.findall(r"[\u0600-\u06FF]", text))
    latin = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
    digits = len(re.findall(r"\d", text))
    weird = len(CONTROL_RE.findall(text))
    replacement = text.count("�")
    punctuation_noise = len(re.findall(r"[^\w\s\u0600-\u06FFÀ-ÿ.,;:!?()/%\-'\"]", text))
    words = len(re.findall(r"[A-Za-zÀ-ÿ]{3,}|[\u0600-\u06FF]{2,}", text))
    return (
        len(meaningful) * 0.22
        + words * 3.5
        + arabic * 0.15
        + latin * 0.12
        + digits * 0.04
        - weird * 5.0
        - replacement * 6.0
        - punctuation_noise * 0.12
        - max(0, total - len(text.strip())) * 0.01
    )


def is_low_quality_text(value: str) -> bool:
    text = normalize_text(value)
    compact = meaningful_text(text)
    if len(compact) < 20:
        return True
    if CONTROL_RE.search(text):
        return True
    if len(re.findall(r"[\u0600-\u06FFA-Za-zÀ-ÿ]", text)) < max(12, len(text) * 0.12):
        return True
    return text_quality_score(text) < 16


def choose_better_text(primary: str, secondary: str) -> str:
    primary_score = text_quality_score(primary)
    secondary_score = text_quality_score(secondary)
    if secondary_score > primary_score + 8:
        return normalize_text(secondary)
    if is_low_quality_text(primary) and secondary_score >= primary_score:
        return normalize_text(secondary)
    return normalize_text(primary)


def _ocr_variants(image: Image.Image) -> list[Image.Image]:
    base = ImageOps.autocontrast(image.convert("L"))
    sharp = base.filter(ImageFilter.SHARPEN)
    return [sharp]


def ocr_image_best_text(image: Image.Image, lang: str = "ara+fra+eng") -> str:
    best_text = ""
    best_score = -10_000.0
    for variant in _ocr_variants(image):
        try:
            text = pytesseract.image_to_string(
                variant,
                lang=lang,
                config="--oem 3 --psm 6 -c preserve_interword_spaces=1",
            )
        except Exception:
            continue
        score = text_quality_score(text)
        if score > best_score:
            best_score = score
            best_text = text
    return normalize_text(best_text)


def ocr_pdf_page_text(page, lang: str = "ara+fra+eng", scale: float = 3.0) -> str:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return ocr_image_best_text(image, lang=lang)
