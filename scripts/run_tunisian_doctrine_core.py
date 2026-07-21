from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ENABLE_KEYLESS_FALLBACKS", "false")
os.environ.setdefault("LLM_PROVIDER_TIMEOUT", "4")
os.environ.setdefault("LLM_PROVIDER_RETRIES", "1")

from app.main import app

DEFAULT_DATASET = ROOT / "app" / "data" / "tunisian_doctrine_core_100.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "tunisian_doctrine_core_100_local.json"


def norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def load_cases(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def contains_all(answer: str, phrases: list[str]) -> dict[str, bool]:
    normalized = norm(answer)
    return {phrase: norm(phrase) in normalized for phrase in phrases}


def visible_hard_checks(case: dict, answer: str, debug: dict) -> dict[str, bool]:
    case_id = str(case.get("id") or "")
    question = norm(case.get("question") or "")
    answer_norm = norm(answer)
    checks: dict[str, bool] = {}
    if "maintenance" in question or "contrat de service" in question or "contrat du" in question:
        if "1er decembre 2025" in question and "30 novembre 2026" in question:
            checks["maintenance_dec_nov_visible"] = "1/12" in answer and "11/12" in answer
        if "1er juillet 2025" in question and "30 juin 2026" in question:
            checks["maintenance_july_june_visible"] = "6/12" in answer
        if "1er janvier 2026" in question and "31 decembre 2026" in question:
            checks["maintenance_after_closing_visible"] = "0/12" in answer and "12/12" in answer
        checks["maintenance_no_missing_given_dates"] = "date de debut/fin du contrat" not in answer_norm
    if "creance" in question and "180 000" in question and "30 000" in question:
        checks["receivable_180_30_visible"] = "150 000" in answer and "180 000 - 30 000" in answer
        checks["receivable_not_month_subtraction"] = "180 000 - 14" not in answer and "179 986" not in answer
    if "creance" in question and "250 000" in question and "40 000" in question:
        checks["receivable_250_40_visible"] = "210 000" in answer and "250 000 - 40 000" in answer
    if "15 octobre 2025" in question and ("machine" in question or "pret" in question):
        checks["asset_15_oct_visible"] = "15 octobre 2025" in answer_norm and "amortissement comptable commence" in answer_norm
    if "1er novembre 2025" in question and ("actif" in question or "pret" in question):
        checks["asset_1_nov_visible"] = "1er novembre 2025" in answer_norm and "amortissement comptable commence" in answer_norm
    if "tva" in question and ("gener" in question or "cadre" in question or "regles" in question):
        checks["tva_framework_not_names_only"] = all(
            marker in answer_norm
            for marker in ["champ", "territorial", "exigibil", "deduction", "facturation"]
        )
    if "ias" in question or "ifrs" in question:
        checks["standards_hierarchy_visible"] = (
            ("tunisien" in answer_norm or "nc" in answer_norm or "sct" in answer_norm)
            and "ifrs" in answer_norm
        )
    if debug.get("guardrail_blocked"):
        checks["no_guardrail_block"] = False
    return checks


def classify(row: dict, answer: str, debug: dict, required: dict[str, bool], forbidden: dict[str, bool], hard: dict[str, bool]) -> tuple[str, str]:
    required_ok = all(required.values()) if required else True
    forbidden_ok = not any(forbidden.values())
    hard_ok = all(hard.values()) if hard else True
    unsafe = any(
        marker in norm(answer)
        for marker in [
            "we need to",
            "rewrite answer",
            "correcting error",
            "article [x]",
            "source implicite",
            "180 000 - 14",
            "179 986",
        ]
    )
    if unsafe or not forbidden_ok or not hard_ok:
        return "fail", "visible answer failed hard/unsafe checks"
    expected_workflow = row.get("expected_workflow")
    if row.get("_enforce_workflow") and expected_workflow and debug.get("workflow") != expected_workflow:
        return "fail", f"workflow mismatch: expected {expected_workflow}, got {debug.get('workflow')}"
    if debug.get("doctrine_cards") and not debug.get("doctrine_validation_pass"):
        return "safe_pass", "final visible answer did not satisfy its doctrine contract"
    if required_ok and debug.get("workflow"):
        return "expert_pass", "required visible elements and workflow present"
    return "safe_pass", "safe answer but missing one or more expected expert elements"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--enforce-workflow", action="store_true")
    args = parser.parse_args()

    client = TestClient(app)
    results = []
    counts = {"expert_pass": 0, "safe_pass": 0, "fail": 0, "error": 0}
    cases = load_cases(args.dataset)
    if args.enforce_workflow:
        for case in cases:
            case["_enforce_workflow"] = True
    if args.limit:
        cases = cases[: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(cases, start=1):
        started = time.time()
        try:
            response = client.post(
                "/v1/accounting-chat",
                json={
                    "message": case["question"],
                    "language": case.get("language") or "francais",
                    "history": [],
                    "debug": True,
                },
                timeout=120,
            )
            data = response.json()
            answer = data.get("answer", "")
            debug = data.get("debug_trace") or {}
            required = contains_all(answer, case.get("expected_answer_contains") or [])
            forbidden = contains_all(answer, case.get("forbidden_answer_contains") or [])
            hard = visible_hard_checks(case, answer, debug)
            if response.status_code != 200:
                status, reason = "error", f"http {response.status_code}"
            else:
                status, reason = classify(case, answer, debug, required, forbidden, hard)
            counts[status] += 1
            results.append(
                {
                    "id": case.get("id"),
                    "question": case.get("question"),
                    "http_status": response.status_code,
                    "status": status,
                    "reason": reason,
                    "workflow": debug.get("workflow"),
                    "generator_path": debug.get("generator_path"),
                    "fallback_used": debug.get("fallback_used"),
                    "guardrail_blocked": debug.get("guardrail_blocked"),
                    "doctrine_engine_applied": debug.get("doctrine_engine_applied"),
                    "doctrine_cards": debug.get("doctrine_cards") or [],
                    "doctrine_validation_pass": debug.get("doctrine_validation_pass"),
                    "doctrine_missing_elements_before": debug.get("doctrine_missing_elements_before") or [],
                    "doctrine_missing_elements": debug.get("doctrine_missing_elements") or [],
                    "doctrine_regenerated": debug.get("doctrine_regenerated"),
                    "doctrine_quality_status": debug.get("doctrine_quality_status"),
                    "required_checks": required,
                    "forbidden_hits": forbidden,
                    "visible_hard_checks": hard,
                    "latency_ms": round((time.time() - started) * 1000, 1),
                    "answer": answer,
                }
            )
        except Exception as exc:
            counts["error"] += 1
            results.append(
                {
                    "id": case.get("id"),
                    "question": case.get("question"),
                    "status": "error",
                    "reason": repr(exc),
                    "latency_ms": round((time.time() - started) * 1000, 1),
                }
            )
        if index % 5 == 0 or index == len(cases):
            payload = {
                "dataset": str(args.dataset),
                "total": len(results),
                "planned": len(cases),
                "counts": counts,
                "unsafe_answers": counts["fail"],
                "results": results,
            }
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"progress": f"{index}/{len(cases)}", "counts": counts}, ensure_ascii=True), flush=True)

    payload = {
        "dataset": str(args.dataset),
        "total": len(results),
        "planned": len(cases),
        "counts": counts,
        "unsafe_answers": counts["fail"],
        "doctrine_regenerated_count": sum(1 for row in results if row.get("doctrine_regenerated")),
        "doctrine_safe_pass_count": sum(1 for row in results if row.get("doctrine_quality_status") == "safe_pass"),
        "results": results,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": len(results), "counts": counts, "output": str(args.output)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
