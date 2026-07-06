import json
import re
import asyncio

import httpx

from . import config
from .skills import ACTIVE_SKILLS, ROUTE_PRESETS, choose_route, detect_document_kind, detect_language, retrieve_terms


def clean_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\x00", "").strip()


def split_by_structure(text: str, max_chars: int | None = None) -> list[str]:
    max_chars = max_chars or config.MAX_CHARS_PER_CHUNK
    text = clean_text(text)
    if len(text) <= max_chars:
        return [text]
    units = []
    for part in re.split(r"(?=\n(?:\[PAGE \d+\]|\[HEADING|\[ARTICLE\]|Article\s+\d+|ARTICLE\s+\d+|Clause\s+\d+))", text):
        units.extend(item.strip() for item in re.split(r"\n{2,}", part) if item.strip())

    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(unit[i : i + max_chars] for i in range(0, len(unit), max_chars))
            continue
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) > max_chars and current:
            chunks.append(current.strip())
            current = unit
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def model_candidates() -> list[str]:
    candidates = [config.LLM_MODEL, *config.LLM_FALLBACK_MODELS]
    return list(dict.fromkeys(item for item in candidates if item))


def retry_delay_seconds(error: Exception | None, attempt: int) -> float:
    message = str(error or "")
    retry_match = re.search(r'retry_after_seconds"?\s*:\s*([0-9.]+)', message, re.I)
    if retry_match:
        return min(15.0, float(retry_match.group(1)))
    if "429" in message:
        return 6.0
    if "402" in message:
        return 0.3
    return 0.5 * attempt


def clean_translation_output(value: str) -> str:
    return (
        str(value or "")
        .replace("\n\\ ", "\n")
        .replace("\n\\", "\n")
        .replace("\n\n\n", "\n\n")
        .strip()
    )


def extract_json(content: str) -> dict:
    raw = content.strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.I)
    raw = re.sub(r"^```\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw, flags=re.I)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {
                "translation": raw,
                "summary": [],
                "quality_notes": ["Model returned non-JSON text; translation was recovered automatically."],
                "metadata": {},
            }
        return json.loads(match.group(0))


async def classify_document_with_llm(client: httpx.AsyncClient, headers: dict, text: str, fallback_kind: str) -> dict:
    fallback_route = choose_route(text, fallback_kind)
    sample = clean_text(text)[:6000]
    body = {
        "model": config.LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "You are a silent document classifier for an adaptive translation pipeline.",
                        "Do not translate. Classify the document route only.",
                        "Allowed routes: legal, financial, tunisianFinance, technical, medical, administrative, general.",
                        "Return only valid JSON:",
                        '{"route":"legal|financial|tunisianFinance|technical|medical|administrative|general","document_kind":"","confidence":0.0,"reasons":[]}',
                    ]
                ),
            },
            {"role": "user", "content": f"Heuristic kind: {fallback_kind}\n\nDocument sample:\n{sample}"},
        ],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    try:
        response = await client.post(config.LLM_ENDPOINT, headers=headers, json=body)
        if response.status_code == 400:
            body.pop("response_format", None)
            response = await client.post(config.LLM_ENDPOINT, headers=headers, json=body)
        response.raise_for_status()
        parsed = extract_json(response.json()["choices"][0]["message"]["content"])
        route = parsed.get("route")
        if route not in ROUTE_PRESETS:
            route = fallback_route
        return {
            "route": route,
            "document_kind": parsed.get("document_kind") or fallback_kind,
            "confidence": parsed.get("confidence", 0.5),
            "reasons": parsed.get("reasons") if isinstance(parsed.get("reasons"), list) else [],
            "source": "llm-classifier",
        }
    except Exception:
        return {
            "route": fallback_route,
            "document_kind": fallback_kind,
            "confidence": 0.35,
            "reasons": ["Fallback heuristic classifier used."],
            "source": "heuristic-fallback",
        }


def build_messages(
    text: str,
    source_lang: str,
    target_lang: str,
    notes: str | None,
    document_kind: str,
    skill_profile: str,
    route: str,
    route_rules: list[str],
    retrieved_terms: list[dict],
    chunk_index: int,
    total_chunks: int,
    structure_notes: str | None,
) -> list[dict]:
    knowledge = "\n".join(
        f"- {term['source']} -> {term['target']}. Regle: {term['guidance']}" for term in retrieved_terms
    )
    rules_block = "\n".join(f"- {rule}" for rule in route_rules)
    chunk_line = (
        f"Ce passage est le morceau {chunk_index + 1}/{total_chunks}. Garde la coherence terminologique avec l'ensemble."
        if total_chunks > 1
        else "Le document est fourni en une seule partie."
    )
    system = "\n".join(
        [
            "Tu es un traducteur professionnel senior specialise en traduction juridique, judiciaire, financiere, administrative, medicale et technique.",
            "Tu traduis entre le francais et l'arabe avec le niveau d'un expert judiciaire et d'un reviseur linguistique professionnel.",
            "",
            "SKILLS BACKEND ACTIVES:",
            "1. Server document parsing: le backend extrait PDF, DOCX, HTML et TXT.",
            "2. Layout-aware parsing: respecter pages, titres, articles, clauses, listes et tableaux markdown.",
            "3. RAG terminologique: appliquer les termes recuperes ci-dessous lorsqu'ils sont pertinents.",
            "4. Judicial translation prompt: precision, exhaustivite, style juridique quand le domaine l'exige.",
            "5. Long-document chunking: traduire ce morceau sans perdre la coherence globale.",
            "",
            f"Mode automatique detecte: {skill_profile}.",
            f"Route interne detectee: {route}.",
            f"Type de document detecte: {document_kind}.",
            structure_notes or "",
            chunk_line,
            "",
            "RAG TERMINOLOGIQUE:",
            knowledge or "- Aucun terme specialise detecte.",
            "",
            "REGLES ADAPTATIVES DE LA ROUTE:",
            rules_block,
            "",
            "REGLES ABSOLUES:",
            "- Traduire integralement. Ne pas resumer a la place de traduire.",
            "- Conserver les titres, articles, clauses, paragraphes, listes, tableaux, dates, montants, noms propres, numeros et references.",
            "- Pour les tableaux markdown, garder lignes et colonnes dans le meme ordre.",
            "- Ne pas inventer, corriger ou completer une information absente.",
            "- Pour l'arabe: arabe moderne formel, naturel et professionnel; style judiciaire si le document est juridique.",
            "- Pour le francais: style professionnel, sobre et precis.",
            "- Repondre uniquement en JSON valide.",
            "",
            "Format JSON:",
            '{"translation":"","summary":[],"quality_notes":[],"metadata":{"source_lang":"","target_lang":"","document_type":"","terms":[],"entities":[]}}',
        ]
    )
    user = "\n".join(
        item
        for item in [
            f"Langue source: {source_lang}",
            f"Langue cible: {target_lang}",
            notes and f"Consignes client: {notes}",
            "",
            "Texte a traduire integralement:",
            text,
        ]
        if item is not None
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def translate_text(
    text: str,
    source_lang: str = "auto",
    target_lang: str | None = None,
    notes: str | None = None,
    document_kind: str | None = None,
    structure_notes: str | None = None,
) -> dict:
    if not config.LLM_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    text = clean_text(text)
    source = source_lang if source_lang != "auto" else detect_language(text)
    target = target_lang or ("francais" if source == "arabe" else "arabe")

    headers = {"authorization": f"Bearer {config.LLM_API_KEY}", "content-type": "application/json"}
    if "openrouter.ai" in config.LLM_ENDPOINT:
        headers["http-referer"] = config.SITE_URL
        headers["x-title"] = "Judicial Translator Backend"

    translations: list[str] = []
    summaries: list[str] = []
    notes_out: list[str] = []
    metadata: dict = {}
    async with httpx.AsyncClient(timeout=120) as client:
        heuristic_kind = document_kind or detect_document_kind(text)
        classification = await classify_document_with_llm(client, headers, text, heuristic_kind)
        route = classification["route"]
        preset = ROUTE_PRESETS[route]
        kind = classification["document_kind"]
        profile = preset["profile"]
        terms = retrieve_terms(text, kind, route)
        chunks = split_by_structure(text)

        for index, chunk in enumerate(chunks):
            parsed = None
            messages = build_messages(
                chunk,
                source,
                target,
                notes,
                kind,
                profile,
                route,
                preset["rules"],
                terms,
                index,
                len(chunks),
                structure_notes,
            )
            last_error: Exception | None = None
            used_model = config.LLM_MODEL
            for candidate_model in model_candidates():
                for attempt in range(2):
                    body = {
                        "model": candidate_model,
                        "messages": messages,
                        "temperature": 0.03,
                        "max_tokens": config.LLM_MAX_TOKENS,
                        "response_format": {"type": "json_object"},
                    }
                    try:
                        response = await client.post(config.LLM_ENDPOINT, headers=headers, json=body)
                        if response.status_code == 400:
                            body.pop("response_format", None)
                            response = await client.post(config.LLM_ENDPOINT, headers=headers, json=body)
                        response.raise_for_status()
                        parsed = extract_json(response.json()["choices"][0]["message"]["content"])
                        if str(parsed.get("translation") or "").strip():
                            used_model = candidate_model
                            break
                        last_error = RuntimeError("Model returned an empty translation.")
                    except Exception as error:
                        last_error = error
                    if attempt < 1:
                        await asyncio.sleep(retry_delay_seconds(last_error, attempt + 1))
                if parsed is not None and str(parsed.get("translation") or "").strip():
                    break
            if parsed is None or not str(parsed.get("translation") or "").strip():
                plain_body = {
                    "model": model_candidates()[0],
                    "messages": [
                        messages[0],
                        {
                            "role": "user",
                            "content": f"{messages[1]['content']}\n\nIf JSON is difficult, return only the complete translation text.",
                        },
                    ],
                    "temperature": 0.03,
                    "max_tokens": config.LLM_MAX_TOKENS,
                }
                response = await client.post(config.LLM_ENDPOINT, headers=headers, json=plain_body)
                response.raise_for_status()
                parsed = extract_json(response.json()["choices"][0]["message"]["content"])
                if not str(parsed.get("translation") or "").strip() and last_error:
                    raise last_error
            translations.append(clean_translation_output(parsed.get("translation") or ""))
            summaries.extend(parsed.get("summary") or [])
            notes_out.extend(parsed.get("quality_notes") or [])
            if isinstance(parsed.get("metadata"), dict):
                metadata.update(parsed["metadata"])

    metadata.update({
        "source_lang": source,
        "target_lang": target,
        "document_type": preset["label"],
    })

    return {
        "success": True,
        "translation": "\n\n".join(item for item in translations if item),
        "summary": summaries[:20],
        "quality_notes": notes_out[:20],
        "metadata": metadata,
        "source_lang": source,
        "target_lang": target,
        "document_kind": kind,
        "skill_profile": profile,
        "route": route,
        "classification": classification,
        "active_skills": ACTIVE_SKILLS,
        "retrieved_terms": terms,
        "chunks": len(chunks),
        "model": used_model if "used_model" in locals() else config.LLM_MODEL,
    }
