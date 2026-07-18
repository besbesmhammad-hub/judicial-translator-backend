from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_PATH = ROOT / "reports" / "benchmark_v2_governance.json"
BASELINE_PATH = ROOT / "reports" / "live_hf_benchmark_v2_d868bc5.json"
OUT_MD = ROOT / "reports" / "level25_precision_gap_report.md"
OUT_JSON = ROOT / "reports" / "level25_precision_gap_report.json"

SUPPORT_RANK = {
    "missing_source": 0,
    "unclassified": 1,
    "framework_source": 2,
    "direct_passage": 3,
}


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_sources(row: dict) -> list[dict]:
    return [
        {
            "doc_id": source.get("doc_id"),
            "page": source.get("page"),
            "support_level": source.get("support_level") or "unclassified",
            "matched_terms": source.get("matched_terms") or [],
            "heading": source.get("heading") or "",
        }
        for source in row.get("selected_sources", [])[:6]
    ]


def false_keys(values: dict | None) -> list[str]:
    return [key for key, value in (values or {}).items() if not value]


def answer_status(row: dict) -> str:
    if row.get("expert_pass"):
        return "expert_pass"
    if row.get("safe_pass"):
        return "safe_pass only"
    return "fail"


def issue_type(row: dict) -> str:
    workflow = row.get("actual_workflow") or row.get("workflow") or ""
    sources = compact_sources(row)
    supports = {source["support_level"] for source in sources}
    substance_false = false_keys(row.get("substance_checks"))
    source_false = false_keys(row.get("source_precision_checks"))

    if workflow in {"fallback_after_provider_failure"} or row.get("guardrail_blocked"):
        return "weak answer generation / provider fallback"
    if "source_precision_visible" in source_false:
        return "weak source-support formatting"
    if "amortization_has_direct_passage" in source_false or all(level == "unclassified" for level in supports):
        return "weak retrieval/source precision tagging"
    if any(source["support_level"] == "missing_source" for source in sources):
        return "missing document"
    if row.get("actual_workflow") == "company_law_governance_case" and "dividende" in row.get("id", ""):
        return "weak routing"
    if substance_false:
        return "weak answer generation"
    if not row.get("expert_pass"):
        return "weak answer generation"
    return "weak retrieval"


def missing_item(row: dict) -> str:
    case_id = row.get("id", "")
    source_false = false_keys(row.get("source_precision_checks"))
    substance_false = false_keys(row.get("substance_checks"))
    if "tax_dividendes" in case_id:
        return "Dividend answer must explicitly cover withholding, declaration/reversement, certificate/proof, and beneficiary profile."
    if "subvention" in case_id:
        return "Provider-safe fallback replaced the cabinet answer; needs accounting treatment from NC 12 with direct source support."
    if "goodwill" in case_id:
        return "Directly tagged support from IFRS 3/NC 38 on goodwill treatment and impairment test."
    if case_id in {"general_lois_tva_tunisie", "loi_finances_modifie_code_tva"}:
        return "Fastpath answer is good, but source support labels are unclassified and source-precision wording is not visible."
    if "dividendes_associe_resident" in case_id:
        return "Single resident shareholder analysis should apply facts directly instead of a generic beneficiary-by-beneficiary template."
    if "tva_services" in case_id or "prestation_informatique_france" in case_id:
        return "Final answer must use retrieved TVA/treaty sources to conclude the checks for the exact B2B/B2C fact pattern."
    if "fraude" in case_id:
        return "CAC response must state concrete obligations by timing: communication, governance, reassessment of opinion/report, documentation."
    if "amortissement" in case_id:
        return "Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split."
    if "provision_creance" in case_id or "creance_douteuse" in case_id:
        return "Answer must stay focused on accounting provision and fiscal deductibility conditions; avoid irrelevant post-closing recovery unless facts include it."
    if "associe_non_resident" in case_id:
        return "Country/treaty passage is missing; answer should reserve treaty rate and list residence certificate/treaty facts."
    if source_false or substance_false:
        return "; ".join(source_false + substance_false)
    return "Manual review needed."


def priority(row: dict) -> str:
    case_id = row.get("id", "")
    if row.get("source_precision_pass") is False and row.get("expert_pass") is False and answer_status(row) == "fail":
        if case_id in {"general_lois_tva_tunisie", "loi_finances_modifie_code_tva"}:
            return "B"
        return "A"
    if answer_status(row) == "fail":
        if any(term in case_id for term in ("dividendes", "tva_services", "fraude", "amortissement")):
            return "A"
        return "B"
    if answer_status(row) == "safe_pass only":
        return "B"
    return "C"


def recommended_fix(row: dict) -> str:
    case_id = row.get("id", "")
    issue = issue_type(row)
    if case_id == "tax_dividendes_2026":
        return "Route dividend + withholding questions to shareholder_split_tax_analysis, not company_law_governance_case; require retenue/declaration/certificate phrases."
    if "subvention" in case_id:
        return "Add NC 12 precision rules and a grounded fallback using retrieved NC 12 excerpts when provider generation is blocked."
    if "goodwill" in case_id:
        return "Add source precision rules for IFRS 3 and NC 38 goodwill terms; do not accept unclassified sources for goodwill conclusions."
    if case_id in {"general_lois_tva_tunisie", "loi_finances_modifie_code_tva"}:
        return "Classify canonical fastpath sources as framework_source/direct_passage and include the existing source-support wording in debug/output checks."
    if "tva_services" in case_id or "prestation_informatique_france" in case_id:
        return "Turn retrieved TVA/treaty passages into a fact-sensitive answer: client status, place of use, invoicing, justificatifs, missing facts."
    if "fraude" in case_id:
        return "Create no new fastpath yet; strengthen audit_cac_response_case generation so timing changes before/after signature alter obligations."
    if "amortissement" in case_id:
        return "Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction."
    if "provision_creance" in case_id or "creance_douteuse" in case_id:
        return "Split generic receivable definition from subsequent-event workflow; only discuss post-closing recovery when present in facts."
    if "non_resident" in case_id:
        return "Keep missing_source reservation for treaty until residence country/treaty passage is known; ask for country and certificate of tax residence."
    if "dividendes" in case_id:
        return "Use the current IRPP/IS direct passage plus finance-law framework to produce a fact-specific dividend checklist; avoid generic multi-beneficiary wording for one beneficiary."
    return f"Investigate {issue}; compare final answer against selected source excerpts."


def cause(row: dict) -> str:
    issue = issue_type(row)
    if "missing document" in issue:
        return "missing document"
    if "source precision" in issue or "support formatting" in issue:
        return "missing article / weak retrieval"
    if "routing" in issue:
        return "weak retrieval"
    if "fallback" in issue or "generation" in issue:
        return "weak answer generation"
    return "weak retrieval"


def build_gaps(current: dict) -> list[dict]:
    gaps = []
    for row in current.get("results", []):
        if row.get("source_precision_pass") and row.get("expert_pass") and row.get("content_quality_pass"):
            continue
        gaps.append({
            "id": row.get("id"),
            "question": row.get("question"),
            "workflow": row.get("actual_workflow") or row.get("workflow"),
            "selected_sources": compact_sources(row),
            "support_levels": sorted({source["support_level"] for source in compact_sources(row)}),
            "missing": missing_item(row),
            "issue_type": issue_type(row),
            "root_cause": cause(row),
            "answer_status": answer_status(row),
            "priority": priority(row),
            "source_precision_pass": row.get("source_precision_pass"),
            "expert_pass": row.get("expert_pass"),
            "safe_pass": row.get("safe_pass"),
            "substance_failures": false_keys(row.get("substance_checks")),
            "source_precision_failures": false_keys(row.get("source_precision_checks")),
            "recommended_fix": recommended_fix(row),
        })
    return gaps


def source_map(row: dict) -> dict[str, str]:
    return {
        source.get("doc_id"): source.get("support_level") or "unclassified"
        for source in row.get("selected_sources", [])
        if source.get("doc_id")
    }


def build_improvements(current: dict, baseline: dict | None) -> list[dict]:
    if not baseline:
        return []
    old_by_id = {row.get("id"): row for row in baseline.get("results", [])}
    improvements = []
    for row in current.get("results", []):
        old = old_by_id.get(row.get("id"))
        if not old:
            continue
        current_sources = source_map(row)
        old_sources = source_map(old)
        movement: list[str] = []
        if "code_irpp_is_2011" in old_sources and "code_irpp_is_2025" in current_sources:
            movement.append("old/historical source -> current source")
        for doc_id, new_level in current_sources.items():
            old_level = old_sources.get(doc_id)
            if not old_level:
                continue
            if SUPPORT_RANK.get(old_level, 1) < SUPPORT_RANK.get(new_level, 1):
                movement.append(f"{doc_id}: {old_level} -> {new_level}")
        if any(level == "missing_source" for level in old_sources.values()) and any(level == "framework_source" for level in current_sources.values()):
            movement.append("missing_source -> framework_source")
        if movement:
            improvements.append({
                "id": row.get("id"),
                "question": row.get("question"),
                "movements": sorted(set(movement)),
                "old_sources": [
                    {"doc_id": doc, "support_level": level}
                    for doc, level in old_sources.items()
                ][:6],
                "current_sources": [
                    {"doc_id": doc, "support_level": level}
                    for doc, level in current_sources.items()
                ][:6],
            })
    return improvements


def render_md(gaps: list[dict], improvements: list[dict], summary: dict) -> str:
    lines = [
        "# Level 2/2.5 Precision Gap Report",
        "",
        f"- Benchmark cases: {summary.get('total_cases')}",
        f"- OK requests: {summary.get('ok_cases')}",
        f"- Source precision pass: {summary.get('source_precision_pass_count')}/{summary.get('total_cases')}",
        f"- Expert pass: {summary.get('expert_pass_count')}/{summary.get('total_cases')}",
        f"- Content quality pass: {summary.get('content_quality_pass_count')}/{summary.get('total_cases')}",
        f"- Cases requiring precision work: {len(gaps)}",
        "",
        "## Priority Summary",
    ]
    for prio in ["A", "B", "C"]:
        items = [gap for gap in gaps if gap["priority"] == prio]
        lines.append(f"- Priority {prio}: {len(items)}")

    for prio, title in [
        ("A", "Priority A - Must Fix Before Cabinet Use"),
        ("B", "Priority B - Useful Improvement, Currently Reserved/Safe Enough"),
        ("C", "Priority C - Optional Corpus Improvement"),
    ]:
        items = [gap for gap in gaps if gap["priority"] == prio]
        if not items:
            continue
        lines.extend(["", f"## {title}", ""])
        for gap in items:
            selected_sources = ", ".join(
                f"`{source['doc_id']}`/{source['support_level']}/p{source['page']}"
                for source in gap["selected_sources"]
            )
            lines.extend([
                f"### {gap['id']}",
                f"- Question: {gap['question']}",
                f"- Workflow: `{gap['workflow']}`",
                f"- Current answer status: `{gap['answer_status']}`",
                f"- Support levels: `{', '.join(gap['support_levels'])}`",
                f"- Root cause: `{gap['root_cause']}` ({gap['issue_type']})",
                f"- Missing: {gap['missing']}",
                f"- Selected sources: {selected_sources}",
                f"- Substance failures: {', '.join(gap['substance_failures']) or 'none'}",
                f"- Source precision failures: {', '.join(gap['source_precision_failures']) or 'none'}",
                f"- Recommended fix: {gap['recommended_fix']}",
                "",
            ])

    lines.extend(["", "## New Corpus Impact", ""])
    if improvements:
        for item in improvements[:40]:
            old_sources = ", ".join(
                f"`{source['doc_id']}`/{source['support_level']}"
                for source in item["old_sources"]
            )
            current_sources = ", ".join(
                f"`{source['doc_id']}`/{source['support_level']}"
                for source in item["current_sources"]
            )
            lines.extend([
                f"### {item['id']}",
                f"- Movement: {', '.join(item['movements'])}",
                f"- Old sources: {old_sources}",
                f"- Current sources: {current_sources}",
                "",
            ])
    else:
        lines.append("- No comparable baseline movements found.")
    return "\n".join(lines)


def main() -> None:
    current = load_report(CURRENT_PATH)
    baseline = load_report(BASELINE_PATH) if BASELINE_PATH.exists() else None
    gaps = build_gaps(current)
    improvements = build_improvements(current, baseline)
    payload = {
        "summary": current.get("summary", {}),
        "gap_count": len(gaps),
        "gaps": gaps,
        "improvements": improvements,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(gaps, improvements, current.get("summary", {})), encoding="utf-8")
    print(json.dumps({
        "gap_count": len(gaps),
        "priority_A": sum(1 for gap in gaps if gap["priority"] == "A"),
        "priority_B": sum(1 for gap in gaps if gap["priority"] == "B"),
        "priority_C": sum(1 for gap in gaps if gap["priority"] == "C"),
        "improvements": len(improvements),
        "report": str(OUT_MD),
    }, indent=2))


if __name__ == "__main__":
    main()
