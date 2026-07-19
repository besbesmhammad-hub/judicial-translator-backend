from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from run_accounting_benchmark import (
    cabinet_answer_quality_scores,
    level25_source_precision_checks,
    normalize_for_match,
    post_json,
    selected_doc_ids,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "app" / "data" / "accounting_blind_level4_seed.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "level4_blind_eval_latest.json"


ISSUE_RULES = [
    ("TVA", ["tva", "export", "facture", "facturation", "assujetti", "service", "etranger"]),
    ("retenue a la source", ["retenue", "dividende", "non resident", "redevance", "honoraires"]),
    ("convention fiscale", ["france", "italie", "algerie", "non resident", "etranger", "convention"]),
    ("etablissement stable", ["etablissement stable", "consultant", "chantier", "installation", "formation", "jours"]),
    ("comptabilite", ["comptable", "comptabiliser", "ecriture", "cloture", "provision", "stock", "subvention"]),
    ("amortissement", ["amortissement", "amortir", "mise en service", "machine", "immobilisation", "vehicule"]),
    ("audit/CAC", ["cac", "audit", "opinion", "rapport", "fraude", "confirmation", "direction"]),
    ("droit des societes", ["associe", "assemblee", "capital", "sarl", "sa", "distribution", "dirigeant"]),
    ("paie/social", ["salarie", "paie", "cnss", "avantage en nature", "bulletin", "employeur"]),
    ("procedure fiscale", ["declaration", "penalite", "regularisation", "controle", "delai"]),
]


MISSING_FACT_RULES = [
    ("montant HT/TVA et devise", ["montant", "tnd", "eur", "facture"]),
    ("contrat ou bon de commande", ["contrat", "commande"]),
    ("periode exacte / date de cloture", ["periode", "cloture", "date"]),
    ("statut resident/non-resident et pays", ["resident", "non resident", "pays", "france", "italie", "algerie"]),
    ("statut TVA/B2B/B2C du client", ["assujetti", "particulier", "b2b", "b2c", "tva"]),
    ("preuves de paiement et justificatifs", ["paiement", "virement", "justificatif", "preuve"]),
    ("PV, rapport, livrables ou documentation technique", ["pv", "rapport", "livrable", "documentation"]),
]


def load_cases(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def facts_from_question(question: str) -> dict:
    normalized = normalize_for_match(question)
    amounts = re.findall(r"\b\d{1,3}(?:[ \u00a0]\d{3})+|\b\d+\b", question)
    dates = re.findall(
        r"\b(?:\d{1,2}\s+)?(?:janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre)\s+\d{4}\b|\b20\d{2}\b|\b\d{1,2}\s+jours?\b",
        question,
        flags=re.I,
    )
    countries = [
        country
        for country in ["france", "italie", "algerie", "tunisie", "allemagne", "emirats", "uae"]
        if country in normalized
    ]
    parties = [
        token
        for token in [
            "societe tunisienne",
            "societe francaise",
            "client",
            "associe",
            "actionnaire",
            "personne physique",
            "personne morale",
            "salarie",
            "direction",
            "cac",
        ]
        if token in normalized
    ]
    documents = [
        token
        for token in ["facture", "contrat", "rapport", "pv", "bulletin", "declaration", "certificat", "virement"]
        if token in normalized
    ]
    return {
        "amounts": amounts,
        "dates": dates,
        "countries": countries,
        "parties": parties,
        "documents_mentioned": documents,
    }


def missing_facts_from_question(question: str) -> list[str]:
    normalized = normalize_for_match(question)
    missing = []
    for label, markers in MISSING_FACT_RULES:
        if not any(marker in normalized for marker in markers):
            missing.append(label)
    return missing[:6]


def issue_decomposition(question: str) -> list[str]:
    normalized = normalize_for_match(question)
    issues = [label for label, markers in ISSUE_RULES if any(marker in normalized for marker in markers)]
    return issues or ["qualification professionnelle generale"]


def failure_patterns(row: dict) -> list[str]:
    if not row.get("ok"):
        return ["runtime_or_http_failure"]
    answer = normalize_for_match(row.get("final_answer") or "")
    docs = selected_doc_ids({"selected_sources": row.get("selected_sources") or []})
    scores = row.get("cabinet_answer_quality_scores") or {}
    patterns: list[str] = []
    if row.get("fallback_used") or row.get("guardrail_blocked"):
        patterns.append("safe fallback acceptable" if row.get("safe_pass") else "unsafe answer")
    if not row.get("selected_workflow"):
        patterns.append("routing failure")
    if not docs:
        patterns.append("missing source")
    if row.get("source_support_score") == 0:
        patterns.append("wrong source" if docs else "missing source")
    if scores.get("fact_application_score") == 0:
        patterns.append("weak fact application")
    if scores.get("quantification_score") == 0:
        patterns.append("missing calculation")
    if scores.get("domain_split_score") == 0:
        patterns.append("weak domain split")
    if scores.get("practical_conclusion_score") == 0:
        patterns.append("weak accounting entries" if any(term in answer for term in ["comptable", "ecriture", "provision", "amortissement"]) else "weak practical conclusion")
    risky_claims = ["taux de", "article ", "%"]
    if any(term in answer for term in risky_claims) and row.get("source_support_score") == 0:
        patterns.append("hallucinated or unsupported legal conclusion")
    return patterns or ["passed"]


def classify_status(quality: dict, fallback_used: bool, guardrail_blocked: bool, answer: str) -> tuple[str, str]:
    unsafe_markers = [
        "we need to",
        "rewrite answer",
        "correcting error",
        "article [x]",
        "source implicite",
        "en premiere analyse, le point doit etre rattache principalement au cadre suivant",
    ]
    normalized = normalize_for_match(answer)
    if any(marker in normalized for marker in unsafe_markers):
        return "fail", "unsafe/internal or generic marker reached the user"
    if quality.get("passed") and not fallback_used and not guardrail_blocked:
        return "expert_pass", "all cabinet-answer quality scores passed without fallback"
    if guardrail_blocked or fallback_used:
        return "safe_pass", "fallback or guardrail avoided an unsafe answer, but this is not cabinet expert quality"
    return "fail", "one or more cabinet-answer quality scores failed"


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
    except Exception as error:
        return {
            "id": case.get("id"),
            "question": case.get("question"),
            "ok": False,
            "status": "fail",
            "expert_pass": False,
            "safe_pass": False,
            "fail": True,
            "pass_fail_reason": repr(error),
            "failure_patterns": ["runtime_or_http_failure"],
        }
    latency_ms = round((time.time() - started) * 1000, 1)
    answer = response.get("answer") or ""
    debug = response.get("debug_trace") or {}
    scoring_case = {
        "id": case.get("id"),
        "question": case.get("question"),
        "expected_response_style": "practical_analysis",
        "expected_workflow": debug.get("workflow") or "blind_case",
    }
    source_precision = level25_source_precision_checks(scoring_case, answer, debug)
    quality = cabinet_answer_quality_scores(scoring_case, answer, debug, source_precision)
    fallback_used = bool(debug.get("fallback_used"))
    guardrail_blocked = bool(debug.get("guardrail_blocked"))
    status, reason = classify_status(quality, fallback_used, guardrail_blocked, answer)
    selected_sources = debug.get("selected_sources") or []
    row = {
        "id": case.get("id"),
        "question": case.get("question"),
        "ok": True,
        "latency_ms": latency_ms,
        "commit_hash": debug.get("commit_hash"),
        "environment": debug.get("environment"),
        "selected_workflow": debug.get("workflow"),
        "facts_extracted": facts_from_question(case.get("question") or ""),
        "missing_facts": missing_facts_from_question(case.get("question") or ""),
        "issue_decomposition": issue_decomposition(case.get("question") or ""),
        "selected_sources": [
            {
                "doc_id": source.get("doc_id"),
                "title": source.get("title"),
                "page": source.get("page"),
                "heading": source.get("heading"),
                "support_level": source.get("support_level"),
                "matched_terms": source.get("matched_terms") or [],
                "excerpt_preview": source.get("excerpt_preview"),
            }
            for source in selected_sources
        ],
        "source_support_levels": [source.get("support_level") for source in selected_sources if source.get("support_level")],
        "final_answer": answer,
        "fact_application_score": quality["scores"]["fact_application_score"],
        "quantification_score": quality["scores"]["quantification_score"],
        "domain_split_score": quality["scores"]["domain_split_score"],
        "practical_conclusion_score": quality["scores"]["practical_conclusion_score"],
        "source_support_score": quality["scores"]["source_support_score"],
        "cabinet_answer_quality_scores": quality["scores"],
        "cabinet_answer_quality_checks": quality["checks"],
        "fallback_used": fallback_used,
        "guardrail_blocked": guardrail_blocked,
        "generator_path": debug.get("generator_path"),
        "status": status,
        "expert_pass": status == "expert_pass",
        "safe_pass": status in {"expert_pass", "safe_pass"},
        "fail": status == "fail",
        "pass_fail_reason": reason,
    }
    row["failure_patterns"] = failure_patterns(row)
    return row


def summarize(rows: list[dict]) -> dict:
    patterns: dict[str, int] = {}
    workflows: dict[str, int] = {}
    for row in rows:
        workflows[str(row.get("selected_workflow") or "missing")] = workflows.get(str(row.get("selected_workflow") or "missing"), 0) + 1
        for pattern in row.get("failure_patterns") or []:
            if pattern != "passed":
                patterns[pattern] = patterns.get(pattern, 0) + 1
    return {
        "total_cases": len(rows),
        "ok_cases": sum(1 for row in rows if row.get("ok")),
        "expert_pass_count": sum(1 for row in rows if row.get("expert_pass")),
        "safe_pass_count": sum(1 for row in rows if row.get("status") == "safe_pass"),
        "fail_count": sum(1 for row in rows if row.get("fail")),
        "avg_latency_ms": round(sum(row.get("latency_ms", 0) for row in rows if row.get("ok")) / max(1, sum(1 for row in rows if row.get("ok"))), 1),
        "workflow_counts": workflows,
        "failure_pattern_counts": patterns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Level 4 blind cabinet validation without changing backend code.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default="https://judicial-translator-backend.onrender.com")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between live requests.")
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    if args.limit:
        cases = cases[: args.limit]
    rows = []
    for index, case in enumerate(cases):
        rows.append(evaluate_case(args.base_url, case, args.timeout))
        if args.delay and index < len(cases) - 1:
            time.sleep(args.delay)
    report = {
        "baseline_commit_expected": "ed948e4ded0b",
        "base_url": args.base_url,
        "dataset": str(args.dataset),
        "summary": summarize(rows),
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Results written to: {args.output}")
    return 0 if report["summary"]["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
