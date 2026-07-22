from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "app" / "data" / "accounting_benchmark_deterministic_kernel.jsonl"

sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def load_cases() -> list[dict]:
    cases: list[dict] = []
    with DATASET.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def main() -> int:
    client = TestClient(app)
    results: list[dict] = []
    failures: list[str] = []
    for case in load_cases():
        response = client.post(
            "/v1/accounting-chat",
            json={
                "message": case["question"],
                "language": "francais",
                "debug": True,
            },
            timeout=90,
        )
        data = response.json()
        answer = data.get("answer") or ""
        answer_key = key(answer)
        missing = [item for item in case.get("must_include", []) if key(item) not in answer_key]
        forbidden = [item for item in case.get("must_not_include", []) if key(item) in answer_key]
        trace = data.get("debug_trace") or {}
        deterministic = trace.get("deterministic_consistency") or {}
        ok = response.status_code == 200 and not missing and not forbidden and deterministic.get("pass", True)
        result = {
            "id": case["id"],
            "status_code": response.status_code,
            "workflow": trace.get("workflow"),
            "deterministic_workflow": trace.get("deterministic_workflow"),
            "deterministic_applied": trace.get("deterministic_kernel_applied"),
            "deterministic_mode": trace.get("deterministic_mode"),
            "deterministic_consistency": deterministic,
            "missing_required": missing,
            "forbidden_visible": forbidden,
            "pass": ok,
            "answer_preview": answer[:700],
        }
        results.append(result)
        if not ok:
            failures.append(case["id"])
    print(json.dumps({"total": len(results), "passed": len(results) - len(failures), "failed": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
