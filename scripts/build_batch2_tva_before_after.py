import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "reports" / "benchmark_v2_batch1_dividends_full.json"
AFTER = ROOT / "reports" / "benchmark_v2_batch2_tva_full.json"
OUT_MD = ROOT / "reports" / "batch2_tva_before_after.md"
OUT_JSON = ROOT / "reports" / "batch2_tva_before_after.json"

IDS = [
    "tva_services_client_france",
    "level2_tva_services_france_sources_tva",
    "level2_tva_services_client_francais_non_assujetti",
    "level2_user_tva_prestation_informatique_france_assujetti",
    "batch2_tva_france_b2b_assujetti",
    "batch2_tva_france_b2c_non_assujetti",
    "batch2_tva_service_used_tunisia",
    "batch2_tva_service_used_abroad",
    "batch2_tva_training_physically_france",
    "batch2_tva_partly_tunisia_partly_abroad",
    "batch2_tva_no_foreign_client_proof",
    "batch2_tva_invoice_no_export_justification",
]


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in data["results"]}


def compact_sources(row: dict | None) -> str:
    if not row:
        return "new case"
    return "; ".join(
        f"{source.get('doc_id')} p.{source.get('page')} ({source.get('support_level') or 'unclassified'})"
        for source in (row.get("selected_sources") or [])[:5]
    )


def status(row: dict | None) -> str:
    if not row:
        return "new"
    return f"workflow={row.get('workflow')} safe={row.get('safe_pass')} expert={row.get('expert_pass')} source={row.get('source_precision_pass')}"


def main() -> None:
    before = load(BEFORE)
    after = load(AFTER)
    rows = []
    for case_id in IDS:
        b = before.get(case_id)
        a = after.get(case_id)
        rows.append(
            {
                "id": case_id,
                "question": (a or b or {}).get("question"),
                "before_status": status(b),
                "after_status": status(a),
                "before_sources": compact_sources(b),
                "after_sources": compact_sources(a),
                "before_answer_preview": (b or {}).get("answer_preview", ""),
                "after_answer_preview": (a or {}).get("answer_preview", ""),
            }
        )

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Batch 2 TVA - Before / After",
        "",
        "| Case | Before | After | Sources movement |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {id} | {before} | {after} | {sources} |".format(
                id=row["id"],
                before=row["before_status"].replace("|", "/"),
                after=row["after_status"].replace("|", "/"),
                sources=(row["before_sources"] + " -> " + row["after_sources"]).replace("|", "/"),
            )
        )
    lines.append("")
    lines.append("## Answer Previews")
    for row in rows:
        lines.extend(
            [
                "",
                f"### {row['id']}",
                "",
                f"Question: {row['question']}",
                "",
                "Before:",
                "",
                row["before_answer_preview"] or "New variant added in Batch 2.",
                "",
                "After:",
                "",
                row["after_answer_preview"],
            ]
        )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
