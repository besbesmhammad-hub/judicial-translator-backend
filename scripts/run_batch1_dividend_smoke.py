import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "batch1_dividend_smoke_local.json"
BACKEND = "http://127.0.0.1:8101"

QUESTIONS = [
    {
        "id": "tax_dividendes_2026",
        "question": "Une SARL tunisienne distribue des dividendes en 2026. Quelles retenues a la source faut il verifier avant paiement ?",
    },
    {
        "id": "level2_dividendes_associe_resident_prudent",
        "question": "Une SARL tunisienne distribue 250 000 TND de dividendes en 2026 a un associe resident. Quelles sont les consequences fiscales ? Citez les bases legales.",
    },
    {
        "id": "level2_dividendes_associe_non_resident",
        "question": "Une SARL tunisienne distribue des dividendes en 2026 a un associe non resident. Quels points fiscaux faut il verifier ?",
    },
]


def post(question: str) -> dict:
    body = json.dumps({"message": question, "debug": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{BACKEND}/v1/accounting-chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> None:
    rows = []
    for item in QUESTIONS:
        response = post(item["question"])
        rows.append(
            {
                "id": item["id"],
                "question": item["question"],
                "commit_hash": response.get("commit_hash"),
                "workflow": response.get("workflow") or response.get("debug_trace", {}).get("workflow"),
                "fallback_used": response.get("fallback_used") or response.get("debug_trace", {}).get("fallback_used"),
                "generator_path": response.get("generator_path") or response.get("debug_trace", {}).get("generator_path"),
                "selected_sources": response.get("selected_sources") or response.get("debug_trace", {}).get("selected_sources"),
                "answer": response.get("answer"),
            }
        )
        print(f"{item['id']}: {rows[-1]['workflow']} fallback={rows[-1]['fallback_used']} generator={rows[-1]['generator_path']}")
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
