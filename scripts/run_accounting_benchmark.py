from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "app" / "data" / "accounting_benchmark_v1.jsonl"
DEFAULT_OUTPUT = ROOT / "benchmark_results_latest.json"


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def post_json(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def has_sections(answer: str, sections: list[str]) -> dict[str, bool]:
    text = answer or ""
    return {section: (f"## {section}" in text or f"**{section}**" in text or f"{section}\n" in text) for section in sections}


def normalize_for_match(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def contains_phrases(answer: str, phrases: list[str]) -> dict[str, bool]:
    normalized = normalize_for_match(answer)
    return {phrase: normalize_for_match(phrase) in normalized for phrase in phrases}


def selected_doc_ids(debug_trace: dict) -> list[str]:
    return [
        str(source.get("doc_id") or "")
        for source in (debug_trace.get("selected_sources") or [])
        if source.get("doc_id")
    ]


def selected_source_support(debug_trace: dict) -> list[str]:
    return [
        str(source.get("support_level") or "")
        for source in (debug_trace.get("selected_sources") or [])
        if source.get("support_level")
    ]


def selected_source_headings(debug_trace: dict) -> list[str]:
    return [
        str(source.get("heading") or "")
        for source in (debug_trace.get("selected_sources") or [])
        if source.get("heading")
    ]


def contains_any(normalized_answer: str, phrases: list[str]) -> bool:
    return any(normalize_for_match(phrase) in normalized_answer for phrase in phrases)


def level2_substance_checks(case: dict, answer: str, debug_trace: dict) -> dict:
    case_id = str(case.get("id") or "")
    question = normalize_for_match(str(case.get("question") or ""))
    normalized = normalize_for_match(answer)
    docs = selected_doc_ids(debug_trace)
    checks: dict[str, bool] = {}

    generic_forbidden = [
        "en premiere analyse, le point doit etre rattache principalement au cadre suivant",
        "identifier le texte exact applicable au cas du client",
        "verifier la date de la version du texte",
        "la notion doit etre rattachee aux textes applicables",
    ]
    checks["not_generic_fallback"] = not contains_any(normalized, generic_forbidden)
    checks["no_guardrail_block"] = not bool(debug_trace.get("guardrail_blocked"))

    if "dividende" in case_id or "dividende" in question:
        checks["dividends_mentions_withholding"] = contains_any(normalized, ["retenue a la source", "retenue operee"])
        checks["dividends_mentions_declaration"] = contains_any(normalized, ["obligations declaratives", "declaration", "reversement"])
        checks["dividends_mentions_beneficiary_status"] = contains_any(normalized, ["associe resident", "personne physique", "non-resident", "non resident"])
        checks["dividends_uses_tax_sources"] = "code_irpp_is_2011" in docs and "loi_finances_2026" in docs
        if "non resident" in question:
            checks["nonresident_mentions_treaty"] = contains_any(normalized, ["convention fiscale", "beneficiaire etranger"])

    if ("tva" in case_id and ("france" in case_id or "client" in case_id)) or ("prestation" in question and "france" in question):
        checks["tva_uses_tva_source"] = "tva_droit_consommation" in docs
        checks["tva_not_irpp_primary"] = not docs or docs[0] != "code_irpp_is_2011"
        checks["tva_mentions_territoriality"] = contains_any(normalized, ["territorialite", "client etranger", "etabli hors de tunisie"])
        checks["tva_no_placeholder"] = not contains_any(normalized, ["article [x]", "article x", "reference implicite", "source implicite"])
        if "non assujetti" in question:
            checks["non_taxable_client_changes_analysis"] = contains_any(normalized, ["non assujetti", "ne pas reprendre mecaniquement", "schema b2b"])

    if "fraude" in case_id or "anomalie_apres_rapport" in case_id or "fraude" in question:
        checks["fraud_not_definition"] = "le cac, ou commissaire aux comptes, est" not in normalized
        checks["fraud_addresses_timing"] = contains_any(normalized, ["apres l'emission", "avant la signature", "date de decouverte"])
        checks["fraud_mentions_impact"] = contains_any(normalized, ["evaluer l'incidence", "reevaluer", "remet en cause"])
        checks["fraud_mentions_governance_or_documentation"] = contains_any(normalized, ["gouvernance", "direction", "documentation", "documenter"])
        checks["fraud_uses_audit_sources"] = any(doc.startswith("audit_") for doc in docs)

    if "amortissement" in case_id or "amortissement" in question:
        checks["amortization_mentions_service_date"] = contains_any(normalized, ["mise en service", "prete a etre utilisee", "pret a etre utilise"])
        checks["amortization_mentions_accounting_basis"] = contains_any(normalized, ["base amortissable", "duree d'utilite", "mode d'amortissement"])
        checks["amortization_uses_accounting_sources"] = "nc_05_immobilisations_corporelles" in docs or "ias_16_immobilisations_corporelles" in docs
        checks["amortization_no_audit_sources"] = not any("audit" in doc for doc in docs)
        if "fixed_asset_component" in case_id:
            checks["machine_mentions_all_dates"] = contains_any(normalized, ["15 september", "15 septembre"]) and contains_any(normalized, ["20 septembre"]) and contains_any(normalized, ["10 octobre"]) and contains_any(normalized, ["25 octobre"]) and contains_any(normalized, ["1er novembre", "1 novembre"])
            checks["machine_mentions_component_approach"] = contains_any(normalized, ["composant", "composants", "piece majeure"])
            checks["machine_mentions_accounting_tax_split"] = contains_any(normalized, ["traitement comptable", "fiscalite", "regles fiscales"])
            checks["machine_blocks_wrong_tax_route"] = "droits_taxes_hors_codes" not in docs and "droits et taxes non incorpores" not in normalized

    if "creance" in case_id or "creances" in case_id or "creance douteuse" in question or "creances douteuses" in question:
        checks["receivable_distinguishes_accounting_tax"] = contains_any(normalized, ["distinguer la constatation comptable", "deductibilite fiscale", "traitement comptable"])
        checks["receivable_mentions_individualized"] = contains_any(normalized, ["creance est individualisee", "client par client", "chaque creance"])
        checks["receivable_mentions_evidence"] = contains_any(normalized, ["justificatifs suffisants", "relances", "recouvrement", "balance agee"])
        checks["receivable_uses_accounting_and_tax_sources"] = ("code_irpp_is_2011" in docs and any(doc.startswith(("nc_", "ias_")) for doc in docs))

    is_cross_border_level3 = "cross_border" in case_id or ("120 000" in question and "france" in question and "consultant" in question)

    if is_cross_border_level3:
        checks["level3_not_generic_fallback_phrase"] = not contains_any(
            normalized,
            ["en premiere analyse, le point doit etre rattache principalement au cadre suivant"],
        )
        checks["level3_mentions_tva"] = contains_any(normalized, ["tva", "taxe sur la valeur ajoutee"])
        checks["level3_mentions_withholding"] = contains_any(normalized, ["retenue a la source"])
        checks["level3_mentions_tax_treaty"] = contains_any(normalized, ["convention fiscale", "france-tunisie", "france tunisie"])
        checks["level3_mentions_permanent_establishment"] = contains_any(normalized, ["etablissement stable"])
        checks["level3_mentions_invoicing"] = contains_any(normalized, ["facturation", "facture"])
        checks["level3_mentions_supporting_docs"] = contains_any(normalized, ["justificatifs", "preuves", "contrat"])
        checks["level3_mentions_missing_facts"] = contains_any(normalized, ["informations manquantes", "statut tva du client", "ventilation du prix"])
        checks["level3_uses_tva_source"] = "tva_droit_consommation" in docs
        checks["level3_uses_irpp_source"] = "code_irpp_is_2011" in docs
        checks["level3_flags_treaty_gap"] = "convention_fiscale_france_tunisie" in docs and contains_any(
            normalized,
            ["convention france-tunisie doit etre ajoutee", "convention france tunisie doit etre ajoutee", "n'est pas encore indexee"],
        )

    if "mixed_dividends" in case_id:
        checks["mixed_dividends_splits_physical_person"] = contains_any(normalized, ["personne physique residente", "300 000 tnd"])
        checks["mixed_dividends_splits_tunisian_company"] = contains_any(normalized, ["societe tunisienne", "200 000 tnd"])
        checks["mixed_dividends_splits_nonresident"] = contains_any(normalized, ["associe francais non-resident", "100 000 tnd", "non-resident"])
        checks["mixed_dividends_mentions_treaty"] = contains_any(normalized, ["convention fiscale"])
        checks["mixed_dividends_mentions_certificate"] = contains_any(normalized, ["certificat", "preuve de retenue"])

    if "annual_maintenance" in case_id:
        checks["maintenance_mentions_period_allocation"] = contains_any(normalized, ["periode de service", "ventiler le revenu", "part rattachee"])
        checks["maintenance_mentions_deferred_income"] = contains_any(normalized, ["produit constate d'avance", "produits constates d'avance"])
        checks["maintenance_mentions_tva"] = contains_any(normalized, ["tva", "code tva", "exigibilite"])
        checks["maintenance_distinguishes_payment_service"] = contains_any(normalized, ["date de paiement", "date d'encaissement", "periode de couverture"])

    if "recouvrement_post_cloture" in case_id:
        checks["receivable_recovery_not_generic_fallback_phrase"] = not contains_any(
            normalized,
            ["en premiere analyse, le point doit etre rattache principalement au cadre suivant"],
        )
        checks["receivable_recovery_mentions_180000_if_case"] = ("180 000" not in question and "180000" not in question) or contains_any(normalized, ["180 000 tnd", "180 000"])
        checks["receivable_recovery_mentions_14_months_if_case"] = ("14 mois" not in question) or contains_any(normalized, ["14 mois"])
        checks["receivable_recovery_mentions_reminders_if_case"] = ("relances" not in question) or contains_any(normalized, ["relances"])
        checks["receivable_recovery_mentions_30000"] = contains_any(normalized, ["30 000 tnd", "30 000"])
        checks["receivable_recovery_mentions_subsequent_event"] = contains_any(normalized, ["evenement posterieur", "apres cloture"])
        checks["receivable_recovery_mentions_adjusting"] = contains_any(normalized, ["ajustant", "non ajustant"])
        checks["receivable_recovery_mentions_remaining_exposure"] = contains_any(normalized, ["exposition restante", "150 000", "provision"])

    if "going_concern" in case_id:
        checks["going_concern_not_cac_definition"] = "commissaire aux comptes, est" not in normalized
        checks["going_concern_mentions_negative_equity"] = contains_any(normalized, ["capitaux propres negatifs"])
        checks["going_concern_mentions_bank_financing"] = contains_any(normalized, ["financement bancaire non confirme", "accord est confirme"])
        checks["going_concern_mentions_disclosures_opinion"] = contains_any(normalized, ["disclosures", "notes", "opinion"])
        checks["going_concern_mentions_audit_procedures"] = contains_any(normalized, ["procedures", "elements probants", "confirmations bancaires"])

    if "related_party_property" in case_id:
        checks["related_party_mentions_fair_value"] = contains_any(normalized, ["valeur de marche", "juste valeur", "expertise independante"])
        checks["related_party_mentions_disclosure"] = contains_any(normalized, ["parties liees", "information"])
        checks["related_party_mentions_tax_risk"] = contains_any(normalized, ["acte anormal", "distribution dissimulee", "redressement"])
        checks["related_party_mentions_approval"] = contains_any(normalized, ["convention reglementee", "autorisation", "approbation"])

    if "consulting_cash" in case_id:
        checks["consulting_not_treasury_route"] = "ias_7_tableau_flux_tresorerie" not in docs and "ias 7" not in normalized
        checks["consulting_mentions_service_reality"] = contains_any(normalized, ["realite du service"])
        checks["consulting_mentions_business_interest"] = contains_any(normalized, ["interet de l'entreprise"])
        checks["consulting_mentions_supporting_docs"] = contains_any(normalized, ["contrat", "livrables", "rapport de mission"])
        checks["consulting_prudent_conclusion"] = contains_any(normalized, ["ne peut pas etre confirmee", "sans preuves"])

    if "accounting_provision_not_tax_deductible" in case_id:
        checks["bridge_separates_accounting_tax"] = contains_any(normalized, ["separer le traitement comptable", "traitement fiscal"])
        checks["bridge_mentions_reintegration"] = contains_any(normalized, ["reintegration extra-comptable"])
        checks["bridge_mentions_deferred_tax"] = contains_any(normalized, ["impot differe"])
        checks["bridge_no_unrelated_collection"] = not contains_any(normalized, ["encaissement posterieur"])

    passed = all(checks.values()) if checks else True
    return {
        "checks": checks,
        "passed": passed,
        "selected_doc_ids": docs,
    }


def level25_source_precision_checks(case: dict, answer: str, debug_trace: dict) -> dict:
    case_id = str(case.get("id") or "")
    question = normalize_for_match(str(case.get("question") or ""))
    normalized = normalize_for_match(answer)
    supports = selected_source_support(debug_trace)
    headings = selected_source_headings(debug_trace)
    docs = selected_doc_ids(debug_trace)
    checks: dict[str, bool] = {}

    is_case_analysis = any(
        token in case_id or token in question
        for token in ["dividende", "tva", "france", "fraude", "anomalie", "amortissement", "creance", "creances"]
    )
    if not is_case_analysis:
        return {"checks": checks, "passed": True, "support_levels": supports, "headings": headings}

    checks["source_support_classified"] = bool(supports)
    checks["source_precision_visible"] = contains_any(
        normalized,
        ["passage cible", "source-cadre", "source manquante", "article precis a verifier", "niveau d'appui", "limite:"],
    )

    if "amortissement" in case_id or "amortissement" in question:
        checks["amortization_has_direct_passage"] = "direct_passage" in supports
        checks["amortization_has_heading_or_excerpt"] = bool(headings) or any(
            source.get("excerpt_preview") for source in (debug_trace.get("selected_sources") or [])
        )

    if "creance" in case_id or "creances" in case_id or "creance douteuse" in question or "creances douteuses" in question:
        checks["receivable_has_direct_passage"] = "direct_passage" in supports
        checks["receivable_has_tax_doc"] = "code_irpp_is_2011" in docs

    if ("tva" in case_id and ("france" in case_id or "client" in case_id)) or ("prestation" in question and "france" in question):
        checks["tva_has_tva_doc"] = "tva_droit_consommation" in docs
        checks["tva_no_irpp_primary"] = not docs or docs[0] != "code_irpp_is_2011"
        checks["tva_support_is_not_unclassified"] = any(level in {"direct_passage", "framework_source"} for level in supports)

    if "dividende" in case_id or "dividende" in question:
        checks["dividends_uses_tax_framework"] = "code_irpp_is_2011" in docs and "loi_finances_2026" in docs
        checks["dividends_no_fake_article_precision"] = not contains_any(
            normalized,
            ["article [x]", "source implicite", "reference implicite"],
        )

    if "fraude" in case_id or "anomalie_apres_rapport" in case_id or "fraude" in question:
        checks["fraud_has_audit_support"] = any(doc.startswith("audit_") for doc in docs)
        checks["fraud_support_classified"] = any(level in {"direct_passage", "framework_source"} for level in supports)
        checks["fraud_no_irrelevant_csc_article_416_direct"] = not any(
            source.get("doc_id") == "code_societes_commerciales_2022"
            and source.get("support_level") == "direct_passage"
            and "article 416" in normalize_for_match(str(source.get("heading") or source.get("excerpt_preview") or ""))
            for source in (debug_trace.get("selected_sources") or [])
        )

    is_cross_border_level3 = "cross_border" in case_id or ("120 000" in question and "france" in question and "consultant" in question)

    if is_cross_border_level3:
        checks["level3_has_tva_direct_or_framework"] = "tva_droit_consommation" in docs and any(
            level in {"direct_passage", "framework_source"} for level in supports
        )
        checks["level3_has_missing_treaty_source"] = "convention_fiscale_france_tunisie" in docs and "missing_source" in supports
        checks["level3_source_support_classified"] = bool(supports)

    if "consulting_cash" in case_id:
        checks["consulting_no_ias7_source"] = "ias_7_tableau_flux_tresorerie" not in docs
        checks["consulting_has_tax_or_accounting_source"] = "code_irpp_is_2011" in docs or "loi_comptable" in docs

    return {
        "checks": checks,
        "passed": all(checks.values()) if checks else True,
        "support_levels": supports,
        "headings": headings,
    }


def evaluate_case(base_url: str, case: dict, timeout: float) -> dict:
    payload = {
        "message": case["question"],
        "context": case.get("context") or None,
        "language": case.get("language") or "francais",
        "history": [],
        "debug": True,
    }
    started = time.time()
    try:
        response = post_json(f"{base_url.rstrip('/')}/v1/accounting-chat", payload, timeout=timeout)
        latency_ms = round((time.time() - started) * 1000, 1)
        answer = response.get("answer", "")
        debug_trace = response.get("debug_trace") or {}
        section_checks = has_sections(answer, case.get("expected_sections", []))
        required_phrase_checks = contains_phrases(answer, case.get("expected_answer_contains", []))
        forbidden_phrase_checks = contains_phrases(answer, case.get("forbidden_answer_contains", []))
        substance = level2_substance_checks(case, answer, debug_trace)
        source_precision = level25_source_precision_checks(case, answer, debug_trace)
        expected_workflow = case.get("expected_workflow")
        workflow_match = True if not expected_workflow else debug_trace.get("workflow") == expected_workflow
        all_required_phrases_present = all(required_phrase_checks.values()) if required_phrase_checks else True
        no_forbidden_phrases = not any(forbidden_phrase_checks.values())
        return {
            "id": case["id"],
            "question": case["question"],
            "ok": True,
            "latency_ms": latency_ms,
            "expected_intent": case.get("expected_intent"),
            "actual_intent": response.get("intent"),
            "intent_match": response.get("intent") == case.get("expected_intent"),
            "expected_preferred_source": case.get("expected_preferred_source"),
            "actual_preferred_source": response.get("preferred_source"),
            "preferred_source_match": response.get("preferred_source") == case.get("expected_preferred_source"),
            "expected_response_style": case.get("expected_response_style"),
            "actual_response_style": response.get("response_style"),
            "response_style_match": response.get("response_style") == case.get("expected_response_style"),
            "expected_workflow": expected_workflow,
            "actual_workflow": debug_trace.get("workflow"),
            "workflow_match": workflow_match,
            "section_checks": section_checks,
            "all_sections_present": all(section_checks.values()) if section_checks else True,
            "required_phrase_checks": required_phrase_checks,
            "all_required_phrases_present": all_required_phrases_present,
            "forbidden_phrase_checks": forbidden_phrase_checks,
            "no_forbidden_phrases": no_forbidden_phrases,
            "substance_checks": substance["checks"],
            "substance_quality_pass": substance["passed"],
            "source_precision_checks": source_precision["checks"],
            "source_precision_pass": source_precision["passed"],
            "source_support_levels": source_precision["support_levels"],
            "source_headings": source_precision["headings"],
            "content_quality_pass": all_required_phrases_present and no_forbidden_phrases and substance["passed"] and source_precision["passed"] and workflow_match,
            "sources_count": len(response.get("sources") or []),
            "golden_kb_hits_count": len(response.get("golden_kb_hits") or []),
            "model": response.get("model"),
            "debug_trace": debug_trace,
            "workflow": debug_trace.get("workflow"),
            "generator_path": debug_trace.get("generator_path"),
            "selected_sources": debug_trace.get("selected_sources") or [],
            "fallback_used": debug_trace.get("fallback_used"),
            "guardrail_blocked": debug_trace.get("guardrail_blocked"),
            "answer_preview": answer[:700],
            "warnings": response.get("warnings") or [],
            "assumptions": response.get("assumptions") or [],
            "next_steps": response.get("next_steps") or [],
        }
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return {
            "id": case["id"],
            "question": case["question"],
            "ok": False,
            "http_status": error.code,
            "error": body[:1200],
        }
    except Exception as error:
        return {
            "id": case["id"],
            "question": case["question"],
            "ok": False,
            "error": repr(error),
        }


def summarize(results: list[dict]) -> dict:
    total = len(results)
    ok = sum(1 for row in results if row.get("ok"))
    intent_match = sum(1 for row in results if row.get("intent_match"))
    source_match = sum(1 for row in results if row.get("preferred_source_match"))
    style_match = sum(1 for row in results if row.get("response_style_match"))
    section_match = sum(1 for row in results if row.get("all_sections_present"))
    content_quality_match = sum(1 for row in results if row.get("content_quality_pass"))
    source_precision_match = sum(1 for row in results if row.get("source_precision_pass"))
    latencies = [row["latency_ms"] for row in results if row.get("ok") and isinstance(row.get("latency_ms"), (int, float))]
    return {
        "total_cases": total,
        "ok_cases": ok,
        "failed_cases": total - ok,
        "intent_match_count": intent_match,
        "preferred_source_match_count": source_match,
        "response_style_match_count": style_match,
        "all_sections_present_count": section_match,
        "source_precision_pass_count": source_precision_match,
        "source_precision_failure_count": total - source_precision_match,
        "content_quality_pass_count": content_quality_match,
        "content_quality_failure_count": total - content_quality_match,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }


def summarize_by_key(results: list[dict], key: str) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = {}
    for row in results:
        bucket = str(row.get(key) or "unknown")
        buckets.setdefault(bucket, []).append(row)
    summary: dict[str, dict] = {}
    for bucket, rows in sorted(buckets.items()):
        ok_rows = [row for row in rows if row.get("ok")]
        summary[bucket] = {
            "count": len(rows),
            "ok_cases": len(ok_rows),
            "failed_cases": len(rows) - len(ok_rows),
            "intent_match_count": sum(1 for row in ok_rows if row.get("intent_match")),
            "preferred_source_match_count": sum(1 for row in ok_rows if row.get("preferred_source_match")),
            "response_style_match_count": sum(1 for row in ok_rows if row.get("response_style_match")),
            "all_sections_present_count": sum(1 for row in ok_rows if row.get("all_sections_present")),
            "avg_latency_ms": round(
                sum(row["latency_ms"] for row in ok_rows if isinstance(row.get("latency_ms"), (int, float)))
                / max(1, len([row for row in ok_rows if isinstance(row.get("latency_ms"), (int, float))])),
                1,
            ) if ok_rows else None,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a first benchmark pass against /v1/accounting-chat.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="Path to benchmark jsonl file")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to write benchmark results JSON")
    parser.add_argument("--timeout", type=float, default=90.0, help="Per-request timeout in seconds")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    cases = load_cases(dataset_path)
    results = [evaluate_case(args.base_url, case, args.timeout) for case in cases]
    summary = summarize(results)
    payload = {
        "base_url": args.base_url,
        "dataset": str(dataset_path),
        "generated_at_unix": int(time.time()),
        "summary": summary,
        "summary_by_expected_intent": summarize_by_key(results, "expected_intent"),
        "summary_by_actual_intent": summarize_by_key(results, "actual_intent"),
        "results": results,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Results written to: {output_path}")
    return 0 if summary["failed_cases"] == 0 and summary["content_quality_failure_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
