from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_deterministic_mutation_suite import (  # noqa: E402
    build_cases,
    make_legacy_answer,
    run_kernel,
    validate_case,
)

from app.deterministic_kernel import apply_deterministic_kernel  # noqa: E402


DEFAULT_SEEDS = [20260722, 20260723, 20260724, 20260725, 20260726]
STATIC_DATASET = ROOT / "app" / "data" / "accounting_benchmark_deterministic_kernel.jsonl"


def key(text: str) -> str:
    normalized = "".join(ch for ch in text or "")
    return normalized.casefold()


def load_static_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with STATIC_DATASET.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_netlify_backend(netlify_url: str, timeout: float) -> str:
    base = netlify_url.rstrip("/")
    data = post_json(
        f"{base}/.netlify/functions/config",
        {},
        timeout,
    )
    # Netlify config is a GET endpoint; urllib POST fallback above will fail on some hosts.
    return str(data.get("backendApiUrl") or data.get("BACKEND_API_URL") or "").rstrip("/")


def get_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_netlify_backend_get(netlify_url: str, timeout: float) -> str:
    base = netlify_url.rstrip("/")
    data = get_json(f"{base}/.netlify/functions/config", timeout)
    return str(data.get("backendApiUrl") or data.get("BACKEND_API_URL") or "").rstrip("/")


def run_static_regressions_direct() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in load_static_cases():
        answer, trace = apply_deterministic_kernel(
            make_legacy_answer(),
            case["question"],
            case.get("expected_workflow") or "",
        )
        answer_key = key(answer)
        missing = [item for item in case.get("must_include", []) if key(item) not in answer_key]
        forbidden = [item for item in case.get("must_not_include", []) if key(item) in answer_key]
        consistency = trace.get("consistency") or {}
        contamination = trace.get("contamination") or {}
        ok = not missing and not forbidden and consistency.get("pass", True) and contamination.get("pass", True)
        if not ok:
            failures.append(case["id"])
        results.append(
            {
                "id": case["id"],
                "workflow": trace.get("workflow"),
                "deterministic_kernel_applied": trace.get("deterministic_kernel_applied"),
                "deterministic_mode": trace.get("mode"),
                "missing_required": missing,
                "forbidden_visible": forbidden,
                "consistency_validator_result": consistency,
                "contamination_validator_result": contamination,
                "pass": ok,
                "final_visible_answer": answer,
            }
        )
    return {"mode": "direct", "total": len(results), "passed": len(results) - len(failures), "failed": failures, "results": results}


def run_mutations_direct(seeds: list[int], cases_per_workflow: int) -> dict[str, Any]:
    all_results: list[dict[str, Any]] = []
    failures: list[str] = []
    totals = {
        "wrong_deterministic_calculations": 0,
        "contradictory_dates": 0,
        "legacy_template_contamination": 0,
        "fake_service_dates_not_in_prompt": 0,
        "irrelevant_final_answer_blocks": 0,
    }
    deterministic_applied = 0
    for seed in seeds:
        for case in build_cases(seed, cases_per_workflow):
            answer, trace = run_kernel(case["prompt"], case["expected"].get("workflow", ""))
            ok, reasons, categories = validate_case(case, answer, trace)
            result_id = f"{seed}:{case['id']}"
            if not ok:
                failures.append(result_id)
            deterministic_applied += int(bool(trace.get("deterministic_kernel_applied")))
            totals["wrong_deterministic_calculations"] += int(categories["wrong_deterministic_calculation"])
            totals["contradictory_dates"] += int(categories["contradictory_dates"])
            totals["legacy_template_contamination"] += int(categories["legacy_template_contamination"])
            totals["fake_service_dates_not_in_prompt"] += int(categories["fake_service_dates"])
            totals["irrelevant_final_answer_blocks"] += int(categories["irrelevant_final_blocks"])
            all_results.append(
                {
                    "seed": seed,
                    "id": case["id"],
                    "workflow_family": case["family"],
                    "prompt": case["prompt"],
                    "extracted_facts_json": trace.get("facts"),
                    "deterministic_decision_object": trace.get("decision"),
                    "final_visible_answer": answer,
                    "consistency_validator_result": trace.get("consistency"),
                    "contamination_validator_result": trace.get("contamination"),
                    "pass": ok,
                    "pass_fail_reason": "pass" if ok else "; ".join(reasons),
                }
            )
    acceptance_pass = not failures and all(value == 0 for value in totals.values())
    return {
        "mode": "direct",
        "seeds": seeds,
        "cases_per_workflow": cases_per_workflow,
        "total": len(all_results),
        "passed": len(all_results) - len(failures),
        "failed": failures,
        "deterministic_kernel_applied_count": deterministic_applied,
        "acceptance_gate": totals,
        "acceptance_pass": acceptance_pass,
        "results": all_results,
    }


def _validate_endpoint_response(case: dict[str, Any], data: dict[str, Any], latency_ms: int | None = None) -> tuple[bool, dict[str, Any]]:
    answer = data.get("answer") or ""
    trace = data.get("debug_trace") or {}
    mutation_trace = {
        "workflow": trace.get("deterministic_workflow") or trace.get("workflow"),
        "facts": trace.get("deterministic_facts"),
        "decision": trace.get("deterministic_decision"),
        "consistency": trace.get("deterministic_consistency"),
        "contamination": trace.get("deterministic_contamination"),
        "deterministic_kernel_applied": trace.get("deterministic_kernel_applied"),
    }
    ok, reasons, _categories = validate_case(case, answer, mutation_trace)
    row = {
        "id": case["id"],
        "workflow_family": case["family"],
        "prompt": case["prompt"],
        "status": "returned",
        "commit_hash": trace.get("commit_hash") or data.get("commit_hash"),
        "workflow": trace.get("deterministic_workflow") or trace.get("workflow"),
        "deterministic_kernel_applied": trace.get("deterministic_kernel_applied"),
        "extracted_facts_json": trace.get("deterministic_facts"),
        "deterministic_decision_object": trace.get("deterministic_decision"),
        "final_visible_answer": answer,
        "consistency_validator_result": trace.get("deterministic_consistency"),
        "contamination_validator_result": trace.get("deterministic_contamination"),
        "pass": ok,
        "pass_fail_reason": "pass" if ok else "; ".join(reasons),
    }
    if latency_ms is not None:
        row["latency_ms"] = latency_ms
    return ok, row


def run_mutations_testclient(seeds: list[int], cases_per_workflow: int) -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    all_results: list[dict[str, Any]] = []
    failures: list[str] = []
    deterministic_applied = 0
    for seed in seeds:
        for case in build_cases(seed, cases_per_workflow):
            response = client.post(
                "/v1/accounting-chat",
                json={"message": case["prompt"], "language": "francais", "debug": True},
                timeout=120,
            )
            try:
                data = response.json()
            except Exception as exc:
                failures.append(f"{seed}:{case['id']}")
                all_results.append({"seed": seed, "id": case["id"], "status": "error", "error": str(exc), "pass": False})
                continue
            ok, row = _validate_endpoint_response(case, data)
            row["seed"] = seed
            row["status_code"] = response.status_code
            if response.status_code != 200:
                ok = False
                row["pass"] = False
                row["pass_fail_reason"] = f"status_code:{response.status_code}"
            if not ok:
                failures.append(f"{seed}:{case['id']}")
            deterministic_applied += int(bool(row.get("deterministic_kernel_applied")))
            all_results.append(row)
    return {
        "mode": "testclient",
        "seeds": seeds,
        "cases_per_workflow": cases_per_workflow,
        "total": len(all_results),
        "passed": len(all_results) - len(failures),
        "failed": failures,
        "deterministic_kernel_applied_count": deterministic_applied,
        "acceptance_pass": not failures,
        "results": all_results,
    }


def run_mutations_http(base_url: str, seeds: list[int], cases_per_workflow: int, timeout: float, delay: float) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/v1/accounting-chat"
    version: dict[str, Any] = {}
    try:
        version = get_json(base_url.rstrip("/") + "/version", timeout)
    except Exception as exc:  # pragma: no cover - diagnostic path
        version = {"error": str(exc)}

    all_results: list[dict[str, Any]] = []
    failures: list[str] = []
    deterministic_applied = 0
    for seed in seeds:
        for case in build_cases(seed, cases_per_workflow):
            payload = {"message": case["prompt"], "language": "francais", "debug": True}
            started = time.perf_counter()
            try:
                data = post_json(endpoint, payload, timeout)
                latency_ms = round((time.perf_counter() - started) * 1000)
                ok, row = _validate_endpoint_response(case, data, latency_ms)
                row["seed"] = seed
                if not ok:
                    failures.append(f"{seed}:{case['id']}")
                deterministic_applied += int(bool(row.get("deterministic_kernel_applied")))
                all_results.append(row)
            except Exception as exc:
                failures.append(f"{seed}:{case['id']}")
                all_results.append(
                    {
                        "seed": seed,
                        "id": case["id"],
                        "workflow_family": case["family"],
                        "prompt": case["prompt"],
                        "status": "error",
                        "error": str(exc),
                        "pass": False,
                        "pass_fail_reason": str(exc),
                    }
                )
            if delay:
                time.sleep(delay)
    return {
        "mode": "http",
        "base_url": base_url.rstrip("/"),
        "endpoint": endpoint,
        "version": version,
        "seeds": seeds,
        "cases_per_workflow": cases_per_workflow,
        "total": len(all_results),
        "passed": len(all_results) - len(failures),
        "failed": failures,
        "deterministic_kernel_applied_count": deterministic_applied,
        "acceptance_pass": not failures,
        "results": all_results,
    }


def parse_seeds(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def write_report(report: dict[str, Any], reports_dir: Path, name: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / name
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["direct", "http", "testclient"], default="direct")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--netlify-url", default="")
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in DEFAULT_SEEDS))
    parser.add_argument("--cases-per-workflow", type=int, default=10)
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "reports" / "release_gate")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--delay", type=float, default=0)
    args = parser.parse_args()

    seeds = parse_seeds(args.seeds)
    if len(seeds) < 5 and args.mode == "direct":
        raise SystemExit("direct release gate requires at least 5 seeds")

    if args.mode == "testclient":
        report = run_mutations_testclient(seeds, args.cases_per_workflow)
        output = write_report(report, args.reports_dir, "deterministic_release_gate_testclient.json")
        summary = {k: v for k, v in report.items() if k != "results"} | {"output": str(output)}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if report["acceptance_pass"] else 1

    if args.mode == "http":
        base_url = args.base_url.rstrip("/")
        if args.netlify_url:
            base_url = resolve_netlify_backend_get(args.netlify_url, args.timeout)
        if not base_url:
            raise SystemExit("--base-url or --netlify-url is required in http mode")
        report = run_mutations_http(base_url, seeds, args.cases_per_workflow, args.timeout, args.delay)
        output = write_report(report, args.reports_dir, "deterministic_release_gate_http.json")
        summary = {k: v for k, v in report.items() if k != "results"} | {"output": str(output)}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if report["acceptance_pass"] else 1

    static = run_static_regressions_direct()
    mutations = run_mutations_direct(seeds, args.cases_per_workflow)
    report = {
        "mode": "direct",
        "static_regressions": static,
        "mutations": mutations,
        "acceptance_pass": not static["failed"] and mutations["acceptance_pass"],
    }
    output = write_report(report, args.reports_dir, "deterministic_release_gate_direct.json")
    summary = {
        "mode": "direct",
        "static_regressions": {k: v for k, v in static.items() if k != "results"},
        "mutations": {k: v for k, v in mutations.items() if k != "results"},
        "acceptance_pass": report["acceptance_pass"],
        "output": str(output),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["acceptance_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
