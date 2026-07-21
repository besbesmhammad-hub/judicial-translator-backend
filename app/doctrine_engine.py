from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path


DOCTRINE_PATH = Path(__file__).with_name("data") / "tunisian_doctrine_cards.json"


def key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("-", " ").replace("'", " ")
    return " ".join(text.split())


def fmt_amount(value: int) -> str:
    return f"{value:,}".replace(",", " ")


@dataclass(frozen=True)
class DoctrineCard:
    doctrine_id: str
    domain: str
    topic: str
    workflow_tags: tuple[str, ...]
    query_markers: tuple[str, ...]
    primary_source_document: str
    article_page: str
    exact_extracted_passage: str
    legal_accounting_rule: str
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    practical_cabinet_consequence: str
    required_final_answer_elements: tuple[str, ...]
    common_wrong_answers_to_block: tuple[str, ...]
    source_support_level: str


@lru_cache(maxsize=1)
def load_doctrine_cards() -> tuple[DoctrineCard, ...]:
    if not DOCTRINE_PATH.exists():
        return ()
    raw_cards = json.loads(DOCTRINE_PATH.read_text(encoding="utf-8"))
    cards: list[DoctrineCard] = []
    for raw in raw_cards:
        cards.append(
            DoctrineCard(
                doctrine_id=str(raw.get("doctrine_id") or ""),
                domain=str(raw.get("domain") or ""),
                topic=str(raw.get("topic") or ""),
                workflow_tags=tuple(raw.get("workflow_tags") or ()),
                query_markers=tuple(raw.get("query_markers") or ()),
                primary_source_document=str(raw.get("primary_source_document") or ""),
                article_page=str(raw.get("article_page") or ""),
                exact_extracted_passage=str(raw.get("exact_extracted_passage") or ""),
                legal_accounting_rule=str(raw.get("legal_accounting_rule") or ""),
                conditions=tuple(raw.get("conditions") or ()),
                exceptions=tuple(raw.get("exceptions") or ()),
                practical_cabinet_consequence=str(raw.get("practical_cabinet_consequence") or ""),
                required_final_answer_elements=tuple(raw.get("required_final_answer_elements") or ()),
                common_wrong_answers_to_block=tuple(raw.get("common_wrong_answers_to_block") or ()),
                source_support_level=str(raw.get("source_support_level") or "framework_source"),
            )
        )
    return tuple(cards)


def select_doctrine_cards(query: str, workflow: str) -> list[DoctrineCard]:
    normalized = key(query)
    selected: list[tuple[int, DoctrineCard]] = []
    for card in load_doctrine_cards():
        score = 0
        if workflow and workflow in card.workflow_tags:
            score += 6
        for marker in card.query_markers:
            if key(marker) in normalized:
                score += 2
        if score:
            selected.append((score, card))
    selected.sort(key=lambda item: (-item[0], item[1].doctrine_id))
    return [card for _, card in selected[:4]]


FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

FRENCH_MONTH_LABELS = {
    1: "janvier",
    2: "fevrier",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "aout",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "decembre",
}


def repair_date_text(text: str) -> str:
    repaired = text or ""
    replacements = {
        r"f.vrier": "fevrier",
        r"ao.t": "aout",
        r"d.cembre": "decembre",
    }
    for pattern, replacement in replacements.items():
        repaired = re.sub(pattern, replacement, repaired, flags=re.I)
    return repaired


def _normalize_month(month: str) -> int | None:
    return FRENCH_MONTHS.get(month.lower())


def format_french_date(value: date) -> str:
    day = "1er" if value.day == 1 else str(value.day)
    return f"{day} {FRENCH_MONTH_LABELS[value.month]} {value.year}"


def extract_french_dates(text: str) -> list[date]:
    text = repair_date_text(text)
    dates: list[date] = []
    seen: set[tuple[int, int, int]] = set()
    for match in re.finditer(r"\b([0-3]?\d)[/-]([01]?\d)[/-]((?:19|20)\d{2})\b", text or ""):
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        key_tuple = (value.year, value.month, value.day)
        if key_tuple not in seen:
            dates.append(value)
            seen.add(key_tuple)
    month_names = "|".join(sorted(map(re.escape, FRENCH_MONTHS), key=len, reverse=True))
    pattern = re.compile(rf"\b(1er|[0-3]?\d)\s+({month_names})\s+((?:19|20)\d{{2}})\b", re.I)
    for match in pattern.finditer(text or ""):
        raw_day = match.group(1).lower()
        day = 1 if raw_day == "1er" else int(raw_day)
        month = _normalize_month(match.group(2))
        year = int(match.group(3))
        if not month:
            continue
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        key_tuple = (value.year, value.month, value.day)
        if key_tuple not in seen:
            dates.append(value)
            seen.add(key_tuple)
    return dates


def extract_money_values(text: str) -> list[int]:
    values: list[int] = []
    pattern = re.compile(
        r"\b(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)\s*(tnd|dt|dinar(?:s)?|eur|euro(?:s)?)\b"
        r"|\b(\d{1,3}(?:[ \u00a0]\d{3})+)\b",
        re.I,
    )
    for match in pattern.finditer(text or ""):
        raw = re.sub(r"[ \u00a0]", "", match.group(1) or match.group(3) or "")
        try:
            value = int(raw)
        except ValueError:
            continue
        if value >= 1000:
            values.append(value)
    return values


def month_span_inclusive(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month + 1)


def rendered_months_until_closing(start: date, end: date, closing: date) -> int:
    if closing < start:
        return 0
    if closing >= end:
        return month_span_inclusive(start, end)
    return month_span_inclusive(start, closing)


def infer_contract_period(query: str) -> tuple[date, date] | None:
    dates = extract_french_dates(query)
    if len(dates) < 2:
        return None
    first, second = dates[0], dates[1]
    if first <= second:
        return first, second
    return second, first


def infer_closing_date(query: str, period: tuple[date, date] | None = None) -> date | None:
    normalized = key(query)
    query_for_dates = repair_date_text(query)
    month_names = "|".join(sorted(map(re.escape, FRENCH_MONTHS), key=len, reverse=True))
    closing_patterns = [
        rf"(?:cloture|clôture|cl.ture|closing)[^.\n]{{0,80}}?((?:1er|[0-3]?\d)\s+(?:{month_names})\s+(?:19|20)\d{{2}})",
        r"(?:cloture|clôture|cl.ture|closing)[^.\n]{0,80}?([0-3]?\d[/-][01]?\d[/-](?:19|20)\d{2})",
    ]
    for pattern in closing_patterns:
        match = re.search(pattern, query_for_dates or "", re.I)
        if match:
            parsed = extract_french_dates(match.group(1))
            if parsed:
                return parsed[0]
    dates = extract_french_dates(query_for_dates)
    for value in dates:
        before = normalized[: max(0, normalized.find(str(value.year)))]
        if "cloture" in before[-80:] or "31 decembre" in normalized:
            if value.day == 31 and value.month == 12:
                return value
    if "31 decembre" in normalized or "31/12" in normalized:
        years = [int(item) for item in re.findall(r"\b(20\d{2})\b", query or "")]
        if years:
            return date(min(years), 12, 31)
    product_year = re.search(r"\bproduit\s+(20\d{2})\b", normalized)
    if product_year:
        return date(int(product_year.group(1)), 12, 31)
    if period and ("cloture" in normalized or "decembre" in normalized or "paye" in normalized or "payee" in normalized):
        return date(period[0].year, 12, 31)
    return None


def revenue_cutoff_visible_block(query: str) -> str:
    period = infer_contract_period(query)
    if not period:
        return (
            "## Application concrete\n"
            "Les dates exactes de debut, de fin et de cloture ne sont pas toutes exploitables. Il faut appliquer la formule: "
            "montant facture x periode deja rendue avant cloture / periode totale couverte; le solde non gagne est un produit constate d'avance. La TVA reste analysee separement."
        )
    start, end = period
    closing = infer_closing_date(query, period)
    if not closing:
        return (
            "## Application concrete\n"
            f"La periode contractuelle identifiable couvre {format_french_date(start)} au {format_french_date(end)}. "
            "La date de cloture n'est pas exploitable avec certitude: appliquer le prorata entre la periode deja rendue a la cloture et la duree totale du contrat. La TVA reste separee du cut-off comptable."
        )
    total = month_span_inclusive(start, end)
    earned = rendered_months_until_closing(start, end, closing)
    deferred = max(0, total - earned)
    if total <= 0:
        return ""
    conclusion = (
        f"Le contrat couvre {format_french_date(start)} au {format_french_date(end)}. "
        f"A la cloture du {format_french_date(closing)}, la part rendue est {earned}/{total}; la part non gagnee est {deferred}/{total}."
    )
    if total == 12:
        conclusion += f" Il faut donc retenir {earned}/12 en produit de l'exercice et {deferred}/12 en produit constate d'avance."
    conclusion += " La TVA doit etre traitee separement de la reconnaissance du revenu comptable."
    return f"## Application concrete\n{conclusion}"


def receivable_visible_block(query: str) -> str:
    values = extract_money_values(query)
    duration = re.search(r"\b(\d+)\s*mois\b", key(query))
    if len(values) >= 2:
        gross = max(values)
        recovered = min(value for value in values if value != gross) if any(value != gross for value in values) else values[1]
        if gross > recovered:
            remaining = gross - recovered
            duration_text = f" Le retard de {duration.group(1)} mois est une anciennete, pas un montant a soustraire." if duration else ""
            return (
                "## Application concrete\n"
                f"Sur les montants fournis, l'exposition residuelle preliminaire est {fmt_amount(gross)} - {fmt_amount(recovered)} = {fmt_amount(remaining)} TND."
                f"{duration_text} La provision/depreciation doit porter sur le risque de non-recouvrement restant, puis etre analysee fiscalement selon les conditions et justificatifs disponibles."
            )
    return (
        "## Application concrete\n"
        "La provision/depreciation doit etre calculee client par client sur l'exposition restant a risque, apres prise en compte des encaissements posterieurs et des preuves de recouvrement. Fiscalement, ne pas confirmer la deduction sans source et justificatifs directs."
    )


def fixed_asset_visible_block(query: str) -> str:
    normalized = key(query)
    dates = extract_french_dates(query)
    if not dates:
        return (
            "## Application concrete\n"
            "L'amortissement comptable commence lorsque l'actif est pret ou disponible pour l'utilisation prevue, pas automatiquement a la facture ou a la livraison. Si la date de mise en service manque, la conclusion doit rester formulee comme une condition."
        )
    ready_patterns = [
        r"(?:pret(?:e)? a fonctionner|prete a fonctionner|disponible|mise en service|mise en production|commence la production|pret pour l'utilisation|prets pour l'utilisation)[^.\n]{0,80}?((?:1er|[0-3]?\d)\s+\w+\s+(?:19|20)\d{2}|[0-3]?\d[/-][01]?\d[/-](?:19|20)\d{2})",
        r"((?:1er|[0-3]?\d)\s+\w+\s+(?:19|20)\d{2}|[0-3]?\d[/-][01]?\d[/-](?:19|20)\d{2})[^.\n]{0,80}?(?:pret(?:e)? a fonctionner|prete a fonctionner|disponible|mise en service|mise en production|commence la production|pret pour l'utilisation)",
    ]
    selected: date | None = None
    for pattern in ready_patterns:
        match = re.search(pattern, query or "", re.I)
        if match:
            parsed = extract_french_dates(match.group(0))
            if parsed:
                selected = parsed[-1]
                break
    if selected is None and any(marker in normalized for marker in ["pret", "pretes", "fonctionner", "disponible", "mise en service", "mise en production"]):
        selected = dates[-1]
    if selected is None:
        return (
            "## Application concrete\n"
            "Les dates fournies doivent etre classees entre acquisition, livraison, installation, tests et mise en service. L'amortissement commence a la date ou l'actif devient pret a fonctionner, pas forcement a la premiere date citee."
        )
    return (
        "## Application concrete\n"
        f"Les faits permettent une conclusion comptable preliminaire: l'amortissement comptable commence le {format_french_date(selected)}, sous reserve du PV de mise en service ou d'un justificatif equivalent. La deduction fiscale de l'amortissement doit ensuite etre verifiee separement."
    )


def doctrine_contract_block(query: str, workflow: str) -> tuple[str, list[dict]]:
    cards = select_doctrine_cards(query, workflow)
    if not cards:
        return "", []
    primary = cards[0]
    elements = "; ".join(primary.required_final_answer_elements[:8])
    wrong = "; ".join(primary.common_wrong_answers_to_block[:3])
    block = (
        "## Controle doctrine\n"
        f"Doctrine appliquee: {primary.topic}. Regle decisive: {primary.legal_accounting_rule} "
        f"Elements obligatoires de la reponse: {elements}. "
        f"A bloquer: {wrong}."
    )
    trace = [
        {
            "doctrine_id": card.doctrine_id,
            "topic": card.topic,
            "domain": card.domain,
            "primary_source_document": card.primary_source_document,
            "source_support_level": card.source_support_level,
            "required_final_answer_elements": list(card.required_final_answer_elements),
        }
        for card in cards
    ]
    return block, trace


def repair_missing_facts(answer: str, query: str) -> tuple[str, bool]:
    output = answer
    changed = False
    normalized_query = key(query)
    period = infer_contract_period(query)
    if period and ("date de debut/fin du contrat" in key(output) or "dates de debut" in key(output)):
        output = re.sub(
            r"- Informations (?:manquantes|a completer):[^\n]*(?:date de debut/fin du contrat|dates? de debut[^\n]*)[^\n]*\n?",
            "- Informations a completer: montant HT/TVA, clauses particulieres, conditions de resiliation, facture et preuve d'encaissement. Les dates de debut et de fin deja donnees ne doivent pas etre listees comme manquantes.\n",
            output,
            flags=re.I,
        )
        changed = output != answer
    if "facture" in normalized_query and "facture manquante" in key(output):
        output = re.sub(r"\bfacture manquante\b", "facture a controler", output, flags=re.I)
        changed = True
    return output, changed


def apply_doctrine_engine(answer: str, query: str, workflow: str) -> tuple[str, dict]:
    output = answer or ""
    changed = False
    cards = select_doctrine_cards(query, workflow)
    blocks: list[str] = []

    normalized_output = key(output)
    if workflow == "revenue_cutoff_tva_case":
        block = revenue_cutoff_visible_block(query)
        if block and ("application concrete" not in normalized_output or "produit constate" not in normalized_output):
            blocks.append(block)
    elif workflow == "receivable_impairment_subsequent_event":
        block = receivable_visible_block(query)
        if block and ("exposition residuelle" not in normalized_output or "180 000 - 14" in normalized_output or "179 986" in normalized_output):
            blocks.append(block)
    elif workflow in {"fixed_asset_component_depreciation_case", "fixed_asset_depreciation_case"}:
        block = fixed_asset_visible_block(query)
        visible_date = re.search(r"amortissement comptable commence le ([^.]+)", key(block))
        needs_date = visible_date and visible_date.group(1) not in normalized_output
        if block and ("amortissement comptable commence" not in normalized_output or needs_date):
            blocks.append(block)

    contract_block, trace_cards = doctrine_contract_block(query, workflow)
    if contract_block and "controle doctrine" not in normalized_output:
        broad_tva = cards and cards[0].doctrine_id == "tva_general_framework"
        standards = cards and cards[0].doctrine_id == "standards_hierarchy_tunisia"
        if broad_tva or (standards and workflow not in {"revenue_cutoff_tva_case"}):
            blocks.append(contract_block)

    if blocks:
        marker = "\n## Sources utilisees"
        injection = "\n\n".join(blocks)
        if marker in output:
            output = output.replace(marker, f"\n{injection}\n{marker}", 1)
        else:
            output = f"{output.rstrip()}\n\n{injection}"
        changed = True

    output, missing_changed = repair_missing_facts(output, query)
    changed = changed or missing_changed

    unsafe_patterns = [
        "180 000 - 14",
        "179 986",
        "source implicite",
        "article [x]",
        "we need to",
        "rewrite answer",
        "correcting error",
    ]
    unsafe = [pattern for pattern in unsafe_patterns if pattern in key(output)]

    return output, {
        "doctrine_engine_applied": changed,
        "doctrine_cards": trace_cards,
        "doctrine_unsafe_patterns": unsafe,
        "doctrine_card_count": len(trace_cards),
    }
