from __future__ import annotations

import argparse
import json
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from run_accounting_benchmark import (
    cabinet_answer_quality_scores,
    level25_source_precision_checks,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports" / "blind_cabinet_eval_latest.json"
INFRA_HTTP_STATUS_CODES = {502, 503, 504, 520, 521, 522, 523, 524}

UNSAFE_PATTERNS = [
    "we need to",
    "rewrite answer",
    "correcting error",
    "article [x]",
    "source implicite",
    "reference implicite",
    "en premiere analyse, le point doit etre rattache principalement au cadre suivant",
    "les sources disponibles ne permettent pas de produire une reponse suffisamment fiable",
]

GENERIC_ONLY_PATTERNS = [
    "identifier le texte exact applicable",
    "verifier les seuils",
    "reconstituer les faits",
    "methode de reponse: appliquer les sources prioritaires",
]


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


def get_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def infra_error_details(error: Exception | None) -> tuple[bool, int | None, str]:
    if error is None:
        return False, None, ""
    if isinstance(error, urllib.error.HTTPError):
        body = ""
        try:
            body = error.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            body = ""
        if error.code in INFRA_HTTP_STATUS_CODES:
            return True, error.code, body or str(error)
        return False, error.code, body or str(error)
    if isinstance(error, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return True, None, str(error)
    return False, None, str(error)


def resolve_netlify_backend(netlify_url: str, timeout: float) -> str:
    data = get_json(f"{netlify_url.rstrip('/')}/.netlify/functions/config", timeout)
    return str(data.get("backendApiUrl") or data.get("BACKEND_API_URL") or "").rstrip("/")


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            question = item.get("question") or item.get("message")
            if not question:
                raise ValueError(f"JSONL line {line_no} must contain 'question' or 'message'")
            rows.append(item)
    return rows


def compact_sources(debug_trace: dict[str, Any]) -> list[dict[str, Any]]:
    sources = debug_trace.get("selected_sources") or []
    return [
        {
            "doc_id": source.get("doc_id") or source.get("document_id"),
            "title": source.get("title") or source.get("document"),
            "page": source.get("page"),
            "heading": source.get("heading"),
            "support_level": source.get("support_level"),
            "matched_terms": source.get("matched_terms") or [],
            "excerpt_preview": source.get("excerpt_preview"),
        }
        for source in sources
    ]


def missing_from_scores(scores: dict[str, int], sources: list[dict[str, Any]], answer: str) -> tuple[str | None, str | None]:
    missing_source: str | None = None
    missing_reasoning: str | None = None

    support_levels = [source.get("support_level") for source in sources if source.get("support_level")]
    if not sources:
        missing_source = "no selected source returned"
    elif not any(level in {"direct_passage", "framework_source"} for level in support_levels):
        missing_source = "sources returned but support level is missing or weak"

    weak_steps = []
    if scores.get("fact_application_score") == 0:
        weak_steps.append("fact application")
    if scores.get("quantification_score") == 0:
        weak_steps.append("quantification/calculation")
    if scores.get("domain_split_score") == 0:
        weak_steps.append("domain split")
    if scores.get("practical_conclusion_score") == 0:
        weak_steps.append("practical cabinet conclusion")
    if scores.get("source_support_score") == 0:
        weak_steps.append("source support")
    if any(pattern in normalize(answer) for pattern in GENERIC_ONLY_PATTERNS):
        weak_steps.append("answer is too generic")
    if weak_steps:
        missing_reasoning = ", ".join(dict.fromkeys(weak_steps))

    return missing_source, missing_reasoning


def classify_answer(
    question: str,
    answer: str,
    debug_trace: dict[str, Any],
    quality: dict[str, Any],
    sources: list[dict[str, Any]],
) -> tuple[str, str, str | None, str | None, bool]:
    question_key = normalize(question)
    normalized = normalize(answer)
    scores = quality.get("scores") or {}
    missing_source, missing_reasoning = missing_from_scores(scores, sources, answer)
    workflow = str(debug_trace.get("workflow") or "")

    if any(pattern in normalized for pattern in UNSAFE_PATTERNS):
        return "unsafe", "internal, unsafe, or forbidden fallback language is visible", missing_source, missing_reasoning, False

    if (
        workflow == "tva_operational_case"
        and any(term in question_key for term in ["charge", "honoraires", "consulting", "prestation externe", "facture non conforme", "sans facture"])
        and any(term in question_key for term in ["deduire", "deductible", "deductibilite", "admis fiscalement", "admise fiscalement"])
        and "tva" not in question_key
    ):
        return "fail", "wrong workflow routing: expense deductibility/evidence question was handled as TVA", missing_source, "wrong workflow routing", False

    if debug_trace.get("guardrail_blocked"):
        return "safe_pass", "guardrail blocked a risky answer; safe but not expert quality", missing_source, missing_reasoning, True

    if debug_trace.get("fallback_used"):
        return "safe_pass", "fallback used; acceptable for supervised internal review but not expert-pass", missing_source, missing_reasoning, True

    if debug_trace.get("deterministic_kernel_applied"):
        consistency = debug_trace.get("deterministic_consistency") or {}
        contamination = debug_trace.get("deterministic_contamination") or {}
        has_conclusion = "conclusion cabinet" in normalized or scores.get("practical_conclusion_score") == 1
        if consistency.get("pass", True) and contamination.get("pass", True) and has_conclusion and not missing_source:
            return "expert_pass", "deterministic calculation is consistent and the visible answer is usable", None, None, True
        if consistency.get("pass", True) and contamination.get("pass", True):
            return "safe_pass", "deterministic calculation is correct but answer/source completeness remains limited", missing_source, missing_reasoning, True

    if quality.get("passed") and not missing_source:
        return "expert_pass", "quality checks passed with usable source support", None, None, True

    if missing_source and not missing_reasoning:
        return "safe_pass", "answer is cautious but source support is incomplete", missing_source, missing_reasoning, True

    fact_ok = scores.get("fact_application_score") == 1
    source_ok = scores.get("source_support_score") == 1 and not missing_source
    if fact_ok and source_ok and missing_reasoning:
        return "safe_pass", "answer applies the facts and is safe, but cabinet completeness is partial", missing_source, missing_reasoning, True

    if workflow == "standards_hierarchy_case" and any(term in normalized for term in ["systeme comptable", "normes comptables tunisiennes", "sct"]):
        return "safe_pass", "standards hierarchy answer is directionally safe but source precision/completeness needs review", missing_source, missing_reasoning, True

    return "fail", "answer is not cabinet-grade on the final visible layer", missing_source, missing_reasoning, False


def evaluate_case(base_url: str, case: dict[str, Any], timeout: float, retries: int, delay: float) -> dict[str, Any]:
    question = str(case.get("question") or case.get("message") or "")
    question_id = str(case.get("question_id") or case.get("id") or "")
    payload = {
        "message": question,
        "language": case.get("language") or "francais",
        "context": case.get("context"),
        "debug": True,
    }

    endpoint = f"{base_url.rstrip('/')}/v1/accounting-chat"
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            response = post_json(endpoint, payload, timeout)
            latency_ms = round((time.perf_counter() - started) * 1000)
            break
        except Exception as exc:
            last_error = exc
            if attempt > retries:
                is_infra, status_code, error_body = infra_error_details(last_error)
                return {
                    "question_id": question_id,
                    "question": question,
                    "classification": "infra_error" if is_infra else "fail",
                    "reason_for_classification": (
                        f"infrastructure/runtime error; no model answer produced: {last_error!r}"
                        if is_infra
                        else f"request failed: {last_error!r}"
                    ),
                    "missing_source_or_reasoning_step": "runtime/http failure",
                    "safe_for_supervised_internal_use": False,
                    "infra_status_code": status_code,
                    "infra_error_body": error_body,
                    "attempts": attempt,
                }
            time.sleep(delay or 1.0)

    debug = response.get("debug_trace") or {}
    answer = response.get("answer") or ""
    sources = compact_sources(debug)
    scoring_case = {
        "id": question_id,
        "question": question,
        "expected_response_style": "practical_analysis",
        "expected_workflow": debug.get("workflow") or "blind_cabinet_case",
    }
    source_precision = level25_source_precision_checks(scoring_case, answer, debug)
    quality = cabinet_answer_quality_scores(scoring_case, answer, debug, source_precision)
    classification, reason, missing_source, missing_reasoning, safe_for_internal = classify_answer(question, answer, debug, quality, sources)
    missing_combined = "; ".join(item for item in [missing_source, missing_reasoning] if item) or None

    return {
        "question_id": question_id,
        "question": question,
        "detected_workflow": debug.get("workflow"),
        "deterministic_kernel_applied": bool(debug.get("deterministic_kernel_applied")),
        "extracted_facts": debug.get("deterministic_facts") if debug.get("deterministic_kernel_applied") else debug.get("case_analysis") or debug.get("facts"),
        "final_visible_answer": answer,
        "sources_used": sources,
        "classification": classification,
        "reason_for_classification": reason,
        "missing_source_or_reasoning_step": missing_combined,
        "safe_for_supervised_internal_use": safe_for_internal,
        "commit_hash": debug.get("commit_hash"),
        "environment": debug.get("environment"),
        "endpoint_name": debug.get("endpoint_name"),
        "fallback_used": bool(debug.get("fallback_used")),
        "guardrail_blocked": bool(debug.get("guardrail_blocked")),
        "generator_path": debug.get("generator_path"),
        "quality_scores": quality.get("scores") or {},
        "source_precision": source_precision,
        "latency_ms": latency_ms,
        "attempts": attempt,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    classifications: dict[str, int] = {}
    workflows: dict[str, int] = {}
    deterministic_count = 0
    safe_internal_count = 0
    for row in results:
        classifications[row["classification"]] = classifications.get(row["classification"], 0) + 1
        workflow = str(row.get("detected_workflow") or "missing")
        workflows[workflow] = workflows.get(workflow, 0) + 1
        deterministic_count += int(bool(row.get("deterministic_kernel_applied")))
        safe_internal_count += int(bool(row.get("safe_for_supervised_internal_use")))
    return {
        "total": len(results),
        "classification_counts": classifications,
        "workflow_counts": workflows,
        "deterministic_kernel_applied_count": deterministic_count,
        "safe_for_supervised_internal_use_count": safe_internal_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate unseen cabinet questions without training or patching on them.")
    parser.add_argument("--dataset", type=Path, required=True, help="JSONL containing unseen questions. Each line needs question_id/id and question/message.")
    parser.add_argument("--base-url", default="https://judicial-translator-backend.onrender.com")
    parser.add_argument("--netlify-url", default="", help="Resolve BACKEND_API_URL from the public Netlify app, then evaluate that backend.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fail-on-unsafe", action="store_true")
    args = parser.parse_args()

    base_url = resolve_netlify_backend(args.netlify_url, args.timeout) if args.netlify_url else args.base_url.rstrip("/")
    cases = load_cases(args.dataset)
    if args.limit:
        cases = cases[: args.limit]

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        results.append(evaluate_case(base_url, case, args.timeout, args.retries, args.delay))
        if args.delay and index < len(cases) - 1:
            time.sleep(args.delay)

    report = {
        "mode": "blind_cabinet_evaluation",
        "training_or_patching_performed": False,
        "dataset": str(args.dataset),
        "base_url": base_url,
        "summary": summarize(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"] | {"output": str(args.output), "base_url": base_url}, ensure_ascii=False, indent=2))

    if args.fail_on_unsafe and any(row["classification"] == "unsafe" for row in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
