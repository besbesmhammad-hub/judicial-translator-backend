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

    if "creance" in case_id or "creances" in case_id or "creance douteuse" in question or "creances douteuses" in question:
        checks["receivable_distinguishes_accounting_tax"] = contains_any(normalized, ["distinguer la constatation comptable", "deductibilite fiscale", "traitement comptable"])
        checks["receivable_mentions_individualized"] = contains_any(normalized, ["creance est individualisee", "client par client", "chaque creance"])
        checks["receivable_mentions_evidence"] = contains_any(normalized, ["justificatifs suffisants", "relances", "recouvrement", "balance agee"])
        checks["receivable_uses_accounting_and_tax_sources"] = ("code_irpp_is_2011" in docs and any(doc.startswith(("nc_", "ias_")) for doc in docs))

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
        ["passage cible", "source-cadre", "article precis a verifier", "niveau d'appui", "limite:"],
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
            "content_quality_pass": all_required_phrases_present and no_forbidden_phrases and substance["passed"] and source_precision["passed"],
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
