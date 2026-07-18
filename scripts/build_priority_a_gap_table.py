import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GAPS = ROOT / "reports" / "level25_precision_gap_report.json"
BENCHMARK = ROOT / "reports" / "benchmark_v2_governance.json"
OUT_MD = ROOT / "reports" / "priority_a_gap_table_before_batch1.md"
OUT_JSON = ROOT / "reports" / "priority_a_gap_table_before_batch1.json"


def source_summary(row: dict) -> str:
    return "; ".join(
        f"{src.get('doc_id')} p.{src.get('page')} ({src.get('support_level') or 'unclassified'})"
        for src in (row.get("selected_sources") or [])[:5]
    )


def main() -> None:
    gaps = json.loads(GAPS.read_text(encoding="utf-8"))["gaps"]
    bench = {
        row["id"]: row
        for row in json.loads(BENCHMARK.read_text(encoding="utf-8"))["results"]
    }
    rows = []
    for gap in gaps:
        if gap.get("priority") != "A":
            continue
        row = bench.get(gap["id"], {})
        rows.append(
            {
                "case_name": gap["id"],
                "exact_question": gap.get("question") or row.get("question"),
                "current_workflow": gap.get("workflow") or row.get("workflow"),
                "current_selected_sources": gap.get("selected_sources") or row.get("selected_sources"),
                "current_final_answer": row.get("answer_preview", ""),
                "why_failed_expert_pass": gap.get("missing"),
                "failure_type": {
                    "issue_type": gap.get("issue_type"),
                    "root_cause": gap.get("root_cause"),
                },
                "exact_proposed_fix": gap.get("recommended_fix"),
                "generalizable_or_case_specific": "generalizable" if gap.get("issue_type") != "missing document" else "corpus-specific",
            }
        )

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Priority A Gap Table - Before Batch 1",
        "",
        "| Case | Workflow | Current sources | Why failed expert_pass | Failure type | Proposed fix | Generalizable? |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {case} | `{workflow}` | {sources} | {why} | {failure_type} | {fix} | {generalizable} |".format(
                case=row["case_name"],
                workflow=row["current_workflow"],
                sources=source_summary({"selected_sources": row["current_selected_sources"]}).replace("|", "/"),
                why=(row["why_failed_expert_pass"] or "").replace("|", "/").replace("\n", " "),
                failure_type=(
                    f"{row['failure_type']['issue_type']} / {row['failure_type']['root_cause']}"
                ).replace("|", "/"),
                fix=(row["exact_proposed_fix"] or "").replace("|", "/").replace("\n", " "),
                generalizable=row["generalizable_or_case_specific"],
            )
        )
    lines.append("")
    lines.append("## Current Answer Previews")
    for row in rows:
        lines.extend(["", f"### {row['case_name']}", "", row["current_final_answer"]])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
