import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "reports" / "benchmark_v2_governance.json"
AFTER = ROOT / "reports" / "benchmark_v2_batch1_dividends_full.json"
SMOKE = ROOT / "reports" / "batch1_dividend_smoke_local.json"
OUT_MD = ROOT / "reports" / "batch1_dividends_before_after.md"
OUT_JSON = ROOT / "reports" / "batch1_dividends_before_after.json"

IDS = [
    "tax_dividendes_2026",
    "level2_dividendes_associe_resident_prudent",
    "level2_dividendes_associe_non_resident",
]


def index(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in data["results"]}


def compact_sources(row: dict) -> str:
    sources = row.get("selected_sources") or []
    return "; ".join(
        f"{source.get('doc_id')} p.{source.get('page')} ({source.get('support_level') or 'unclassified'})"
        for source in sources[:5]
    )


def main() -> None:
    before = index(BEFORE)
    after = index(AFTER)
    smoke = {row["id"]: row for row in json.loads(SMOKE.read_text(encoding="utf-8"))}
    rows = []
    for case_id in IDS:
        b = before[case_id]
        a = after[case_id]
        s = smoke.get(case_id, {})
        rows.append(
            {
                "id": case_id,
                "question": a["question"],
                "before_workflow": b.get("workflow"),
                "after_workflow": a.get("workflow"),
                "before_status": {
                    "safe_pass": b.get("safe_pass"),
                    "expert_pass": b.get("expert_pass"),
                    "source_precision_pass": b.get("source_precision_pass"),
                },
                "after_status": {
                    "safe_pass": a.get("safe_pass"),
                    "expert_pass": a.get("expert_pass"),
                    "source_precision_pass": a.get("source_precision_pass"),
                },
                "before_sources": compact_sources(b),
                "after_sources": compact_sources(a),
                "before_answer_preview": b.get("answer_preview", ""),
                "after_answer": s.get("answer") or a.get("answer_preview", ""),
            }
        )
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Batch 1 Dividends - Before / After",
        "",
        "| Case | Before | After | Source movement |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {id} | `{bw}` safe={bs} expert={be} | `{aw}` safe={as_} expert={ae} | {src} |".format(
                id=row["id"],
                bw=row["before_workflow"],
                bs=row["before_status"]["safe_pass"],
                be=row["before_status"]["expert_pass"],
                aw=row["after_workflow"],
                as_=row["after_status"]["safe_pass"],
                ae=row["after_status"]["expert_pass"],
                src=(row["before_sources"] + " -> " + row["after_sources"]).replace("|", "/"),
            )
        )
    lines.append("")
    for row in rows:
        lines.extend(
            [
                f"## {row['id']}",
                "",
                f"Question: {row['question']}",
                "",
                "Before answer preview:",
                "",
                row["before_answer_preview"],
                "",
                "After answer:",
                "",
                row["after_answer"],
                "",
            ]
        )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
