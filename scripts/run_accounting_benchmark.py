from __future__ import annotations

import argparse
import json
import sys
import time
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


def evaluate_case(base_url: str, case: dict, timeout: float) -> dict:
    payload = {
        "message": case["question"],
        "context": case.get("context") or None,
        "language": case.get("language") or "francais",
        "history": [],
    }
    started = time.time()
    try:
        response = post_json(f"{base_url.rstrip('/')}/v1/accounting-chat", payload, timeout=timeout)
        latency_ms = round((time.time() - started) * 1000, 1)
        answer = response.get("answer", "")
        section_checks = has_sections(answer, case.get("expected_sections", []))
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
            "sources_count": len(response.get("sources") or []),
            "golden_kb_hits_count": len(response.get("golden_kb_hits") or []),
            "model": response.get("model"),
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
    latencies = [row["latency_ms"] for row in results if row.get("ok") and isinstance(row.get("latency_ms"), (int, float))]
    return {
        "total_cases": total,
        "ok_cases": ok,
        "failed_cases": total - ok,
        "intent_match_count": intent_match,
        "preferred_source_match_count": source_match,
        "response_style_match_count": style_match,
        "all_sections_present_count": section_match,
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
    return 0 if summary["failed_cases"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
