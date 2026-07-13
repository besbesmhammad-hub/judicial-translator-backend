import argparse
import json
from collections import Counter
from pathlib import Path


DEFAULT_LOG_PATH = Path("/tmp/accounting_chat_requests.jsonl")


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def top_counter(counter: Counter, limit: int = 10) -> list[dict]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {
            "total_requests": 0,
            "fallback_rate": None,
            "avg_latency_ms": None,
            "provider_success_rate": None,
            "top_intents": [],
            "top_results": [],
            "top_provider_errors": [],
            "top_retrieved_docs": [],
            "top_models": [],
            "ratings": [],
        }

    intents = Counter()
    results = Counter()
    provider_errors = Counter()
    retrieved_docs = Counter()
    models = Counter()
    ratings = Counter()
    latencies: list[float] = []
    fallback_used = 0
    provider_success = 0

    for row in rows:
        intents.update([str(row.get("intent") or "unknown")])
        results.update([str(row.get("result") or "unknown")])
        models.update([str(row.get("model") or "none")])
        if row.get("fallback_used"):
            fallback_used += 1
        if row.get("result") == "provider_success":
            provider_success += 1
        if isinstance(row.get("latency_ms"), (int, float)):
            latencies.append(float(row["latency_ms"]))
        rating = row.get("user_rating")
        if rating is not None:
            ratings.update([str(rating)])
        for attempt in row.get("provider_attempts") or []:
            if attempt.get("status") == "error":
                error_key = f"{attempt.get('provider', 'unknown')}/{attempt.get('error_type', 'error')}"
                provider_errors.update([error_key])
        for ref in row.get("retrieved_legal_refs") or []:
            retrieved_docs.update([str(ref.get("doc_id") or ref.get("title") or "unknown")])

    return {
        "total_requests": len(rows),
        "fallback_rate": round(fallback_used / len(rows), 4),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "provider_success_rate": round(provider_success / len(rows), 4),
        "top_intents": top_counter(intents),
        "top_results": top_counter(results),
        "top_provider_errors": top_counter(provider_errors),
        "top_retrieved_docs": top_counter(retrieved_docs),
        "top_models": top_counter(models),
        "ratings": top_counter(ratings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize accounting-chat JSONL traces.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="Path to accounting chat JSONL log")
    args = parser.parse_args()

    rows = load_rows(Path(args.log_path))
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
