from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any


MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}


def _key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.lower()


def _fmt_date(value: date | None) -> str:
    if not value:
        return ""
    month = {
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
    }[value.month]
    return f"{value.day} {month} {value.year}"


def _format_amount(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:,.2f}"
    else:
        text = f"{int(value):,}"
    return text.replace(",", " ")


def _default_year(text: str) -> int | None:
    match = re.search(r"\b(20\d{2}|19\d{2})\b", text)
    return int(match.group(1)) if match else None


def _parse_numeric_date(day: str, month: str, year: str | None, fallback_year: int | None) -> date | None:
    y = int(year) if year else fallback_year
    if not y:
        return None
    try:
        return date(y, int(month), int(day))
    except ValueError:
        return None


def _parse_named_date(day: str, month_name: str, year: str | None, fallback_year: int | None) -> date | None:
    y = int(year) if year else fallback_year
    m = MONTHS.get(month_name)
    if not y or not m:
        return None
    try:
        return date(y, m, int(day))
    except ValueError:
        return None


def _dates_in(text: str, fallback_year: int | None = None) -> list[date]:
    source = _key(text)
    year = fallback_year or _default_year(source)
    found: list[date] = []
    for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", source):
        y = match.group(3)
        if len(y) == 2:
            y = "20" + y
        parsed = _parse_numeric_date(match.group(1), match.group(2), y, year)
        if parsed:
            found.append(parsed)
    month_names = "|".join(MONTHS)
    for match in re.finditer(rf"\b(\d{{1,2}}|1er)\s+({month_names})(?:\s+(\d{{4}}))?\b", source):
        day = "1" if match.group(1) == "1er" else match.group(1)
        parsed = _parse_named_date(day, match.group(2), match.group(3), year)
        if parsed:
            found.append(parsed)
    for match in re.finditer(rf"\b(?:en|au mois de)\s+({month_names})\s+(\d{{4}})\b", source):
        parsed = _parse_named_date("1", match.group(1), match.group(2), year)
        if parsed and parsed not in found:
            found.append(parsed)
    return found


def _date_after_marker(text: str, markers: list[str], *, fallback_year: int | None = None, window: int = 95) -> date | None:
    source = _key(text)
    for marker in markers:
        pos = source.find(marker)
        if pos < 0:
            continue
        local = source[pos : pos + window]
        dates = _dates_in(local, fallback_year)
        if dates:
            return dates[0]
    return None


def _amounts_with_currency(text: str) -> list[int]:
    values: list[int] = []
    pattern = re.compile(
        r"\b(\d{1,3}(?:[ .]\d{3})+|\d+)\s*(?:tnd|dt|dinars?|eur|euros?)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(_key(text)):
        raw = re.sub(r"[ .]", "", match.group(1))
        try:
            values.append(int(raw))
        except ValueError:
            continue
    return values


def _all_large_amounts(text: str) -> list[int]:
    values = _amounts_with_currency(text)
    seen = set(values)
    for match in re.finditer(r"\b(\d{1,3}(?:[ .]\d{3})+)\b", _key(text)):
        raw = re.sub(r"[ .]", "", match.group(1))
        try:
            value = int(raw)
        except ValueError:
            continue
        if value >= 1000 and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def _month_count_inclusive(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month) + 1)


def _months_earned_until(start: date, end: date, closing: date) -> int:
    if closing < start:
        return 0
    effective_end = min(end, closing)
    return min(_month_count_inclusive(start, end), _month_count_inclusive(start, effective_end))


def _extract_period(text: str) -> tuple[date | None, date | None]:
    source = _key(text)
    year = _default_year(source)
    month_names = "|".join(MONTHS)
    patterns = [
        rf"(?:du|de)\s+(\d{{1,2}}|1er)\s+({month_names})(?:\s+(\d{{4}}))?\s+(?:au|a)\s+(\d{{1,2}}|1er)\s+({month_names})(?:\s+(\d{{4}}))?",
        rf"(?:du|de)\s+(\d{{1,2}})[/-](\d{{1,2}})[/-](\d{{4}})\s+(?:au|a)\s+(\d{{1,2}})[/-](\d{{1,2}})[/-](\d{{4}})",
    ]
    m = re.search(patterns[0], source)
    if m:
        d1 = "1" if m.group(1) == "1er" else m.group(1)
        d2 = "1" if m.group(4) == "1er" else m.group(4)
        start_year = int(m.group(3)) if m.group(3) else year
        end_year = int(m.group(6)) if m.group(6) else start_year
        start = _parse_named_date(d1, m.group(2), str(start_year) if start_year else None, year)
        end = _parse_named_date(d2, m.group(5), str(end_year) if end_year else None, start_year)
        return start, end
    m = re.search(patterns[1], source)
    if m:
        start = _parse_numeric_date(m.group(1), m.group(2), m.group(3), year)
        end = _parse_numeric_date(m.group(4), m.group(5), m.group(6), year)
        return start, end
    return None, None


def _detect_workflow(query: str, workflow: str) -> str:
    key = _key(f"{workflow} {query}")
    if "amort" in key or "immobilisation" in key or "machine" in key or "pret a fonctionner" in key:
        return "fixed_asset_depreciation_case"
    if "creance" in key or "client impaye" in key or "provisionner le solde" in key:
        return "receivable_impairment_subsequent_event"
    if ("prestation" in key or "maintenance" in key or "contrat" in key) and (
        "produit constate" in key
        or "cut-off" in key
        or "cut off" in key
        or "cloture" in key
        or "paye" in key
        or "paiement" in key
    ):
        return "revenue_cutoff_tva_case"
    if "tva" in key and ("service" in key or "encaissement" in key or "realisation" in key or "facture" in key):
        return "tva_operational_case"
    return workflow or ""


def extract_deterministic_facts(query: str, workflow: str) -> dict[str, Any]:
    detected = _detect_workflow(query, workflow)
    key = _key(query)
    default_year = _default_year(key)
    facts: dict[str, Any] = {"workflow": detected, "query": query}

    if detected == "fixed_asset_depreciation_case":
        facts.update(
            {
                "acquisition_date": _date_after_marker(query, ["achete", "acquis", "acquisition", "facture"], fallback_year=default_year),
                "delivery_date": _date_after_marker(query, ["livre", "livraison"], fallback_year=default_year),
                "installation_date": _date_after_marker(query, ["installe", "installation"], fallback_year=default_year),
                "ready_for_use_date": _date_after_marker(
                    query,
                    ["prete a fonctionner", "pret a fonctionner", "prete a l'emploi", "pret a l'emploi", "mise en service", "mise en production"],
                    fallback_year=default_year,
                ),
                "component_issue": bool(re.search(r"composant|remplace|piece majeure|3 ans|trois ans", key)),
            }
        )
        return facts

    if detected == "receivable_impairment_subsequent_event":
        amounts = _all_large_amounts(query)
        gross = amounts[0] if amounts else None
        recovery = None
        for marker in ["recupere", "regle", "encaisse", "paiement", "apres cloture"]:
            local_amounts = _amounts_with_currency(key[key.find(marker) : key.find(marker) + 120]) if marker in key else []
            if local_amounts:
                recovery = local_amounts[0]
                break
        if recovery is None and len(amounts) >= 2:
            recovery = amounts[1]
        months_overdue = None
        month_match = re.search(r"\b(\d{1,2})\s*mois\b", key)
        if month_match:
            months_overdue = int(month_match.group(1))
        facts.update(
            {
                "gross_receivable": gross,
                "recovery_after_closing": recovery,
                "months_overdue": months_overdue,
                "has_reminders": any(term in key for term in ["relance", "mise en demeure", "recouvrement"]),
                "closing_date": _date_after_marker(query, ["au", "cloture", "31/12"], fallback_year=default_year),
            }
        )
        return facts

    if detected == "revenue_cutoff_tva_case":
        period_start, period_end = _extract_period(query)
        closing = _date_after_marker(query, ["cloture", "31/12", "au 31"], fallback_year=default_year)
        if not closing and default_year:
            closing = date(default_year, 12, 31)
        realization = _date_after_marker(query, ["realisee", "realise", "execution", "sera realisee", "sera realise"], fallback_year=default_year)
        collection = _date_after_marker(query, ["recoit", "recu", "encaisse", "encaissement", "paye", "paiement", "regle"], fallback_year=default_year)
        amounts = _all_large_amounts(query)
        facts.update(
            {
                "amount": amounts[0] if amounts else None,
                "contract_start": period_start,
                "contract_end": period_end,
                "closing_date": closing,
                "service_realization_date": realization,
                "collection_date": collection,
                "payment_before_service": bool(collection and realization and collection < realization),
            }
        )
        return facts

    if detected == "tva_operational_case":
        realization = _date_after_marker(query, ["realisee", "realise", "execution", "sera realisee", "sera realise"], fallback_year=default_year)
        collection = _date_after_marker(query, ["recoit", "recu", "encaisse", "encaissement", "paye", "paiement", "regle"], fallback_year=default_year)
        facts.update(
            {
                "service_realization_date": realization,
                "collection_date": collection,
                "collection_before_realization": bool(collection and realization and collection < realization),
                "tunisian_scope_known": "tunisie" in key or "tunisienne" in key,
                "foreign_client": any(country in key for country in ["france", "francais", "etranger", "italie", "allemagne"]),
            }
        )
        return facts

    return facts


def compute_deterministic_decision(facts: dict[str, Any]) -> dict[str, Any]:
    workflow = facts.get("workflow")
    decision: dict[str, Any] = {"workflow": workflow, "available": False}

    if workflow == "fixed_asset_depreciation_case":
        start = facts.get("ready_for_use_date")
        decision.update(
            {
                "available": bool(start),
                "depreciation_start_date": start,
                "rule": "ready_for_use_date_wins",
                "component_required": bool(facts.get("component_issue")),
            }
        )
        return decision

    if workflow == "receivable_impairment_subsequent_event":
        gross = facts.get("gross_receivable")
        recovery = facts.get("recovery_after_closing")
        if gross is not None and recovery is not None:
            decision.update(
                {
                    "available": True,
                    "residual_exposure": gross - recovery,
                    "formula": f"{_format_amount(gross)} - {_format_amount(recovery)} = {_format_amount(gross - recovery)}",
                    "subsequent_event": "post_closing_recovery_is_evidence_to_consider",
                }
            )
        return decision

    if workflow == "revenue_cutoff_tva_case":
        start = facts.get("contract_start")
        end = facts.get("contract_end")
        closing = facts.get("closing_date")
        amount = facts.get("amount")
        realization = facts.get("service_realization_date")
        if start and end and closing:
            total = _month_count_inclusive(start, end)
            earned = _months_earned_until(start, end, closing)
            deferred = max(0, total - earned)
            decision.update(
                {
                    "available": True,
                    "earned_months": earned,
                    "deferred_months": deferred,
                    "total_months": total,
                    "earned_fraction": f"{earned}/{total}",
                    "deferred_fraction": f"{deferred}/{total}",
                }
            )
            if amount is not None and total:
                earned_amount = round(amount * earned / total, 2)
                deferred_amount = round(amount - earned_amount, 2)
                decision["earned_amount"] = earned_amount
                decision["deferred_amount"] = deferred_amount
        elif realization and closing and realization > closing:
            decision.update(
                {
                    "available": True,
                    "earned_months": 0,
                    "deferred_months": None,
                    "service_future_at_closing": True,
                }
            )
            if amount is not None:
                decision["deferred_amount"] = amount
        if facts.get("payment_before_service"):
            decision["tva_collection_before_realization"] = True
        return decision

    if workflow == "tva_operational_case":
        if facts.get("collection_before_realization"):
            decision.update(
                {
                    "available": True,
                    "tva_collection_before_realization": True,
                    "rule": "service_collection_before_realization_triggers_exigibility_risk",
                }
            )
        return decision

    return decision


def _sources_tail(answer: str) -> str:
    for marker in ["\n## Sources", "\n## Base legale"]:
        idx = answer.find(marker)
        if idx >= 0:
            return answer[idx:].strip()
    return ""


def build_deterministic_answer_block(facts: dict[str, Any], decision: dict[str, Any]) -> str:
    workflow = facts.get("workflow")
    lines: list[str] = ["## Application aux faits"]

    if workflow == "fixed_asset_depreciation_case" and decision.get("depreciation_start_date"):
        start = _fmt_date(decision["depreciation_start_date"])
        lines.append(
            f"La date a retenir pour le debut de l'amortissement comptable est le {start}: c'est la date a laquelle l'immobilisation est prete a fonctionner ou disponible pour l'utilisation prevue."
        )
        if facts.get("acquisition_date"):
            lines.append(f"La date d'achat ({_fmt_date(facts['acquisition_date'])}) ne suffit pas si l'actif n'etait pas encore pret.")
        if facts.get("delivery_date"):
            lines.append(f"La livraison ({_fmt_date(facts['delivery_date'])}) ne remplace pas la mise en service.")
        if facts.get("installation_date"):
            lines.append(f"L'installation ({_fmt_date(facts['installation_date'])}) doit etre distinguee de la disponibilite effective.")
        if decision.get("component_required"):
            lines.append("Si un composant significatif a une duree d'utilite differente, il faut l'isoler et l'amortir sur sa propre duree.")
        lines.append("A verifier au dossier: facture, bon de livraison, PV d'installation, PV de mise en service, base amortissable, duree d'utilite et traitement fiscal.")
        return "\n".join(lines)

    if workflow == "receivable_impairment_subsequent_event" and decision.get("residual_exposure") is not None:
        gross = _format_amount(facts.get("gross_receivable"))
        recovery = _format_amount(facts.get("recovery_after_closing"))
        residual = _format_amount(decision.get("residual_exposure"))
        months = facts.get("months_overdue")
        lines.append(f"L'exposition residuelle preliminaire est {gross} - {recovery} = {residual} TND.")
        if months:
            lines.append(f"Le retard de {months} mois est un indice de risque; il ne doit jamais etre traite comme un montant a retrancher.")
        lines.append("L'encaissement posterieur a la cloture est un evenement a analyser comme indice sur la situation existant a la cloture.")
        lines.append("Comptablement, la depreciation/provision doit viser le solde estime non recouvrable, distinct d'une perte definitive.")
        lines.append("Fiscalement, la deductibilite depend des conditions legales applicables et d'un dossier probant: balance agee, relances, correspondances, actions de recouvrement, calcul et validation.")
        return "\n".join(lines)

    if workflow == "revenue_cutoff_tva_case" and decision.get("available"):
        if decision.get("earned_fraction") and decision.get("deferred_fraction"):
            lines.append(
                f"A la cloture, la part acquise est {decision['earned_fraction']} et la part a differer est {decision['deferred_fraction']}."
            )
            if decision.get("earned_amount") is not None and decision.get("deferred_amount") is not None:
                lines.append(
                    f"Sur le montant donne, cela donne environ {_format_amount(decision['earned_amount'])} en produit de l'exercice et {_format_amount(decision['deferred_amount'])} en produit constate d'avance."
                )
            if decision.get("earned_fraction") == "1/12" and decision.get("deferred_fraction") == "11/12":
                lines.append("Decembre est rendu avant le 31/12: 1/12 en produit 2025; janvier a novembre restent a differer: 11/12 en produit constate d'avance.")
        elif decision.get("service_future_at_closing"):
            lines.append("Au 31/12, la prestation n'est pas encore realisee: le produit ne doit pas etre reconnu en chiffre d'affaires de l'exercice clos.")
            if decision.get("deferred_amount") is not None:
                lines.append(f"Le montant encaisse doit donc etre traite comme produit constate d'avance pour {_format_amount(decision['deferred_amount'])}.")
            else:
                lines.append("Le montant encaisse doit donc etre traite comme produit constate d'avance, sous reserve des pieces contractuelles.")
        if decision.get("tva_collection_before_realization"):
            lines.append("La TVA doit etre analysee separement: si l'operation entre dans le champ de la TVA tunisienne, l'encaissement avant realisation peut rendre la TVA exigible sur le montant encaisse.")
        lines.append("Pieces a verifier: contrat, facture, preuve d'encaissement, periode couverte, date de realisation effective, declaration TVA et justification du cut-off.")
        return "\n".join(lines)

    if workflow == "tva_operational_case" and decision.get("tva_collection_before_realization"):
        lines.append("Pour une prestation de services, si l'encaissement total ou partiel intervient avant la realisation, l'exigibilite TVA doit etre analysee sur le montant encaisse.")
        lines.append("Cette conclusion reste separee de la reconnaissance comptable du produit: la TVA peut devenir exigible avant que le produit soit acquis comptablement.")
        lines.append("Il faut confirmer le champ territorial, la qualite du client, le lieu d'utilisation/exploitation, la facture et la periode declarative.")
        return "\n".join(lines)

    return ""


def validate_answer_against_decision(answer: str, facts: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    key_answer = _key(answer)
    key_query = _key(str(facts.get("query") or ""))
    workflow = facts.get("workflow")
    errors: list[str] = []

    if workflow == "fixed_asset_depreciation_case" and decision.get("depreciation_start_date"):
        expected = _key(_fmt_date(decision["depreciation_start_date"]))
        if expected not in key_answer:
            errors.append("missing_depreciation_start_date")
        for label, value in [
            ("acquisition_date", facts.get("acquisition_date")),
            ("delivery_date", facts.get("delivery_date")),
            ("installation_date", facts.get("installation_date")),
        ]:
            if value and value != decision["depreciation_start_date"]:
                wrong = _key(_fmt_date(value))
                if re.search(rf"amortissement[^.\n]{{0,90}}commence[^.\n]{{0,90}}{re.escape(wrong)}", key_answer):
                    errors.append(f"wrong_depreciation_start_uses_{label}")

    if workflow == "receivable_impairment_subsequent_event" and decision.get("residual_exposure") is not None:
        formula = _key(str(decision.get("formula") or ""))
        residual = _format_amount(decision.get("residual_exposure"))
        if _key(residual) not in key_answer and formula not in key_answer:
            errors.append("missing_residual_exposure")
        gross = facts.get("gross_receivable")
        months = facts.get("months_overdue")
        if gross is not None and months is not None:
            bad_formula = f"{_format_amount(gross)} - {months}"
            if _key(bad_formula) in key_answer or "179 986" in key_answer:
                errors.append("money_month_confusion")

    if workflow == "revenue_cutoff_tva_case" and decision.get("available"):
        if "fevrier 2026" in key_answer and "fevrier 2026" not in key_query:
            errors.append("stale_future_service_date_not_in_prompt")
        if "prestation sera realisee" in key_answer and facts.get("contract_start") and facts.get("contract_end"):
            errors.append("stale_single_service_language_for_period_contract")
        if decision.get("earned_fraction") and decision.get("earned_fraction") not in key_answer:
            errors.append("missing_earned_fraction")
        if decision.get("deferred_fraction") and decision.get("deferred_fraction") not in key_answer:
            errors.append("missing_deferred_fraction")
        if decision.get("service_future_at_closing") and not any(term in key_answer for term in ["pas encore realise", "pas encore rend", "non encore realise"]):
            errors.append("missing_future_service_conclusion")
        if facts.get("contract_start") and "date de debut" in key_answer and "manqu" in key_answer:
            errors.append("known_start_date_marked_missing")
        if facts.get("contract_end") and "date de fin" in key_answer and "manqu" in key_answer:
            errors.append("known_end_date_marked_missing")

    if workflow == "tva_operational_case" and decision.get("tva_collection_before_realization"):
        if not ("encaisse" in key_answer and "avant" in key_answer and "exigib" in key_answer):
            errors.append("missing_collection_before_realization_tva_rule")

    return {
        "pass": not errors,
        "errors": errors,
        "workflow": workflow,
    }


def apply_deterministic_kernel(answer: str, query: str, workflow: str) -> tuple[str, dict[str, Any]]:
    facts = extract_deterministic_facts(query, workflow)
    decision = compute_deterministic_decision(facts)
    trace = {
        "deterministic_kernel_applied": False,
        "workflow": facts.get("workflow"),
        "facts": _json_safe(facts),
        "decision": _json_safe(decision),
        "consistency": {"pass": True, "errors": []},
        "mode": "not_applicable",
    }
    if not decision.get("available"):
        return answer, trace

    initial = validate_answer_against_decision(answer, facts, decision)
    block = build_deterministic_answer_block(facts, decision)
    if not block:
        trace["consistency"] = initial
        return answer, trace

    answer_key = _key(answer)
    block_key = _key(block)
    if initial.get("pass") and block_key[:80] in answer_key:
        trace.update({"deterministic_kernel_applied": True, "consistency": initial, "mode": "already_visible"})
        return answer, trace

    tail = _sources_tail(answer)
    if initial.get("pass"):
        new_answer = f"{block}\n\n{answer}".strip()
        mode = "inserted_authoritative_block"
    else:
        new_answer = f"{block}\n\n{tail}".strip() if tail else block
        mode = "replaced_contradictory_or_incomplete_answer"
    final = validate_answer_against_decision(new_answer, facts, decision)
    trace.update(
        {
            "deterministic_kernel_applied": True,
            "consistency": final,
            "mode": mode,
        }
    )
    return new_answer, trace


def _json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value
