from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "app" / "data" / "accounting_blind_level4_seed.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "level4_reliability_probe_latest.json"
DEFAULT_BASE_URL = "https://judicial-translator-backend.onrender.com"
DEFAULT_FRONTEND_URL = "https://judicial-translator-20260706031117.netlify.app"
DEFAULT_RENDER_SERVICE_ID = "srv-d9cpg4flk1mc73fd7q80"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    started = time.perf_counter()
    started_at = utc_now()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(text) if text else None
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": 200 <= response.status < 400,
                "started_at_utc": started_at,
                "finished_at_utc": utc_now(),
                "method": method,
                "url": url,
                "status_code": response.status,
                "response_headers": dict(response.headers.items()),
                "response_body_preview": text[:2000],
                "json": parsed,
                "latency_ms": latency_ms,
            }
    except urllib.error.HTTPError as error:
        raw = error.read()
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            parsed = None
        return {
            "ok": False,
            "started_at_utc": started_at,
            "finished_at_utc": utc_now(),
            "method": method,
            "url": url,
            "status_code": error.code,
            "response_headers": dict(error.headers.items()) if error.headers else {},
            "response_body_preview": text[:2000],
            "json": parsed,
            "latency_ms": latency_ms,
            "error_type": type(error).__name__,
            "error": str(error),
        }
    except Exception as error:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "ok": False,
            "started_at_utc": started_at,
            "finished_at_utc": utc_now(),
            "method": method,
            "url": url,
            "status_code": None,
            "response_headers": {},
            "response_body_preview": "",
            "json": None,
            "latency_ms": latency_ms,
            "error_type": type(error).__name__,
            "error": repr(error),
        }


def render_get(path: str, timeout: float = 30) -> dict[str, Any] | None:
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        return None
    url = f"https://api.render.com/v1{path}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "url": url,
                "status_code": response.status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "json": json.loads(text) if text else None,
            }
    except urllib.error.HTTPError as error:
        return {
            "ok": False,
            "url": url,
            "status_code": error.code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "body_preview": error.read().decode("utf-8", errors="replace")[:1000],
        }
    except Exception as error:
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": repr(error),
        }


def frontend_config(frontend_url: str, timeout: float) -> dict[str, Any]:
    candidates = [
        f"{frontend_url.rstrip('/')}/config.json",
        f"{frontend_url.rstrip('/')}/runtime-config.json",
        f"{frontend_url.rstrip('/')}/.netlify/functions/config",
    ]
    results = [http_json("GET", url, timeout=timeout) for url in candidates]
    return {"candidates": results}


def health_snapshot(base_url: str, timeout: float) -> dict[str, Any]:
    return {
        "version": http_json("GET", f"{base_url.rstrip()}/version", timeout=timeout),
        "health": http_json("GET", f"{base_url.rstrip()}/health", timeout=timeout),
    }


def evaluate_case(base_url: str, case: dict[str, Any], timeout: float, include_health: bool) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/v1/accounting-chat"
    payload = {
        "message": case["question"],
        "context": case.get("context") or None,
        "language": case.get("language") or "francais",
        "history": [],
        "debug": True,
    }
    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    before = health_snapshot(base_url, timeout=20) if include_health else None
    response = http_json("POST", endpoint, payload=payload, timeout=timeout)
    after = health_snapshot(base_url, timeout=20) if include_health or not response.get("ok") else None
    data = response.get("json") if isinstance(response.get("json"), dict) else {}
    debug = data.get("debug_trace") if isinstance(data, dict) else {}
    return {
        "id": case.get("id"),
        "question": case.get("question"),
        "endpoint_called": endpoint,
        "payload_size_bytes": payload_bytes,
        "request_payload": payload,
        "response": response,
        "commit_hash": debug.get("commit_hash") if isinstance(debug, dict) else None,
        "workflow": debug.get("workflow") if isinstance(debug, dict) else None,
        "generator_path": debug.get("generator_path") if isinstance(debug, dict) else None,
        "fallback_used": debug.get("fallback_used") if isinstance(debug, dict) else None,
        "selected_sources": debug.get("selected_sources") if isinstance(debug, dict) else None,
        "health_before": before,
        "health_after": after,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        code = str(row.get("response", {}).get("status_code"))
        status_counts[code] = status_counts.get(code, 0) + 1
    ok_rows = [row for row in rows if row.get("response", {}).get("ok")]
    failed_rows = [row for row in rows if not row.get("response", {}).get("ok")]
    return {
        "total": len(rows),
        "ok": len(ok_rows),
        "failed": len(failed_rows),
        "status_counts": status_counts,
        "avg_latency_ms_ok": round(sum(row["response"].get("latency_ms", 0) for row in ok_rows) / max(1, len(ok_rows)), 1),
        "avg_latency_ms_failed": round(sum(row["response"].get("latency_ms", 0) for row in failed_rows) / max(1, len(failed_rows)), 1),
        "failed_ids": [row.get("id") for row in failed_rows],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe live Render reliability for Level 4 blind validation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL)
    parser.add_argument("--render-service-id", default=DEFAULT_RENDER_SERVICE_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", choices=["normal", "delayed", "smoke"], default="normal")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    if args.limit:
        cases = cases[: args.limit]
    delay = args.delay
    if args.mode == "delayed" and delay <= 0:
        delay = 8

    report: dict[str, Any] = {
        "created_at_utc": utc_now(),
        "mode": args.mode,
        "base_url": args.base_url,
        "frontend_url": args.frontend_url,
        "dataset": str(args.dataset),
        "frontend_config_probe": frontend_config(args.frontend_url, timeout=20),
        "initial_health": health_snapshot(args.base_url, timeout=30),
        "render_service": render_get(f"/services/{args.render_service_id}"),
        "render_deploys": render_get(f"/services/{args.render_service_id}/deploys?limit=5"),
        "results": [],
    }

    for index, case in enumerate(cases):
        include_health = args.mode == "smoke"
        report["results"].append(evaluate_case(args.base_url, case, args.timeout, include_health))
        if delay and index < len(cases) - 1:
            time.sleep(delay)

    report["final_health"] = health_snapshot(args.base_url, timeout=30)
    report["render_deploys_after"] = render_get(f"/services/{args.render_service_id}/deploys?limit=5")
    report["summary"] = summarize(report["results"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Results written to: {args.output}")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
