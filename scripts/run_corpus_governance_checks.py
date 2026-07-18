from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import (
    CURRENT_ENREGISTREMENT_TIMBRE_DOC_ID,
    CURRENT_FISCALITE_LOCALE_DOC_ID,
    CURRENT_IRPP_IS_DOC_ID,
    CURRENT_TAX_PROCEDURE_DOC_ID,
    CURRENT_TVA_DOC_ID,
    enregistrement_timbre_doc_id_for_query,
    fiscalite_locale_doc_id_for_query,
    irpp_is_doc_id_for_query,
    tax_procedure_doc_id_for_query,
    tva_doc_id_for_query,
)


REPORTS_DIR = ROOT / "reports"


def case(case_id: str, helper, query: str, expected: str, note: str) -> dict:
    actual = helper(query)
    return {
        "id": case_id,
        "query": query,
        "expected_doc_id": expected,
        "actual_doc_id": actual,
        "passed": actual == expected,
        "note": note,
    }


def build_cases() -> list[dict]:
    cases: list[dict] = []

    for year, doc_id in [
        ("2026", "procedures_fiscales_2026"),
        ("2025", "procedures_fiscales_2025"),
        ("2024", "procedures_fiscales_2024"),
        ("2023", "procedures_fiscales_2023"),
    ]:
        cases.append(case(
            f"cdpf_explicit_{year}",
            tax_procedure_doc_id_for_query,
            f"Selon le Code des droits et procedures fiscaux edition {year}, quel est le cadre general du controle fiscal ?",
            doc_id,
            "Explicit code edition must select the requested year.",
        ))
    cases.append(case(
        "cdpf_transaction_date_current_default",
        tax_procedure_doc_id_for_query,
        "Une verification fiscale porte sur une operation de 2023. Quels risques de procedure examiner ?",
        CURRENT_TAX_PROCEDURE_DOC_ID,
        "Transaction year alone must not downgrade the default source.",
    ))

    for year, doc_id in [
        ("2026", "tva_droit_consommation"),
        ("2025", "tva_droit_consommation_2025"),
        ("2023", "tva_droit_consommation_2023"),
        ("2021", "tva_droit_consommation_2021"),
        ("2019", "tva_droit_consommation_2019"),
    ]:
        cases.append(case(
            f"tva_explicit_{year}",
            tva_doc_id_for_query,
            f"Selon le Code TVA edition {year}, presente les obligations de facturation.",
            doc_id,
            "Explicit TVA edition must select the requested year.",
        ))
    cases.append(case(
        "tva_transaction_date_current_default",
        tva_doc_id_for_query,
        "Une facture de prestation date de 2021. Quel traitement TVA examiner ?",
        CURRENT_TVA_DOC_ID,
        "Transaction year alone must not select an old TVA code.",
    ))

    for year, doc_id in [
        ("2026", "enregistrement_timbre"),
        ("2025", "enregistrement_timbre_2025"),
        ("2022", "enregistrement_timbre_2022"),
        ("2020", "enregistrement_timbre_2020"),
        ("2018", "enregistrement_timbre_2018"),
    ]:
        cases.append(case(
            f"enregistrement_timbre_explicit_{year}",
            enregistrement_timbre_doc_id_for_query,
            f"Selon le Code des droits d enregistrement et de timbre edition {year}, quel est le cadre applicable ?",
            doc_id,
            "Explicit enregistrement/timbre edition must select the requested year.",
        ))
    cases.append(case(
        "enregistrement_transaction_date_current_default",
        enregistrement_timbre_doc_id_for_query,
        "Un acte signe en 2020 doit etre analyse. Quels droits d enregistrement verifier ?",
        CURRENT_ENREGISTREMENT_TIMBRE_DOC_ID,
        "Transaction year alone must not select an old registration code.",
    ))

    for year, doc_id in [
        ("2026", "fiscalite_locale_2026"),
        ("2025", "fiscalite_locale_2025"),
        ("2023", "fiscalite_locale_2023"),
        ("2020", "fiscalite_locale_2020"),
        ("2018", "fiscalite_locale_2018"),
    ]:
        cases.append(case(
            f"fiscalite_locale_explicit_{year}",
            fiscalite_locale_doc_id_for_query,
            f"Selon le Code de la fiscalite locale edition {year}, presente les taxes locales.",
            doc_id,
            "Explicit local-tax edition must select the requested year.",
        ))
    cases.append(case(
        "fiscalite_locale_transaction_date_current_default",
        fiscalite_locale_doc_id_for_query,
        "Une taxe locale due au titre de 2020 est contestee. Quel cadre verifier ?",
        CURRENT_FISCALITE_LOCALE_DOC_ID,
        "Transaction year alone must not select an old local-tax code.",
    ))

    for year, doc_id in [
        ("2025", "code_irpp_is_2025"),
        ("2023", "code_irpp_is_2023"),
        ("2022", "code_irpp_is_2022"),
        ("2021", "code_irpp_is_2021"),
        ("2020", "code_irpp_is_2020"),
        ("2019", "code_irpp_is_2019"),
        ("2011", "code_irpp_is_2011"),
    ]:
        cases.append(case(
            f"irpp_is_explicit_{year}",
            irpp_is_doc_id_for_query,
            f"Selon le Code IRPP IS edition {year}, presente le cadre general.",
            doc_id,
            "Explicit IRPP/IS edition must select the requested year.",
        ))
    cases.append(case(
        "irpp_is_dividend_2025_current_default",
        irpp_is_doc_id_for_query,
        "Une SARL distribue des dividendes en 2025. Quelles consequences fiscales examiner ?",
        CURRENT_IRPP_IS_DOC_ID,
        "Current cabinet question must use the latest available IRPP/IS source, not the old 2011 edition.",
    ))

    return cases


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    results = build_cases()
    summary = {
        "passed": sum(1 for item in results if item["passed"]),
        "total": len(results),
        "failures": [item for item in results if not item["passed"]],
        "results": results,
    }
    (REPORTS_DIR / "corpus_governance_checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# Corpus Governance Checks",
        "",
        f"Passed: {summary['passed']}/{summary['total']}",
        "",
        "| Case | Expected | Actual | Status |",
        "|---|---:|---:|---|",
    ]
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        md.append(f"| `{item['id']}` | `{item['expected_doc_id']}` | `{item['actual_doc_id']}` | {status} |")
    (REPORTS_DIR / "corpus_governance_checks.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"passed": summary["passed"], "total": summary["total"], "failures": len(summary["failures"])}, indent=2))
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
