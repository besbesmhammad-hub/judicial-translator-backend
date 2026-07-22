from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.deterministic_kernel import (  # noqa: E402
    _format_amount,
    _fmt_date,
    _key,
    apply_deterministic_kernel,
)


MONTHS = [
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
]


def norm(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def fr_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def month_count_inclusive(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month) + 1)


def months_earned(start: date, end: date, closing: date) -> int:
    if closing < start:
        return 0
    effective_end = min(end, closing)
    return min(month_count_inclusive(start, end), month_count_inclusive(start, effective_end))


def make_legacy_answer() -> str:
    return (
        "## Reponse de travail\n"
        "Ce dossier releve d'une analyse generale. Identifier le texte exact applicable et verifier les seuils.\n\n"
        "## Application concrete\n"
        "Montant facture x periode rendue / periode totale. Traitement comptable et TVA a verifier.\n\n"
        "## Sources utilisees\n"
        "- NC 01, page 1\n"
        "- NC 03 Revenus, page 2\n"
        "- Code TVA 2026, page 1\n"
        "- IAS 37 Provisions, page 4\n"
        "- Code IRPP/IS 2025, page 3\n"
        "- Code des stocks, page 7"
    )


def run_kernel(prompt: str, workflow_hint: str = "") -> tuple[str, dict[str, Any]]:
    return apply_deterministic_kernel(make_legacy_answer(), prompt, workflow_hint)


def fixed_asset_cases(rng: random.Random, count: int) -> list[dict[str, Any]]:
    cases = []
    for i in range(count):
        year = rng.choice([2025, 2026])
        acquisition = date(year, rng.randint(1, 10), rng.randint(1, 20))
        delivery = acquisition + timedelta(days=rng.randint(1, 8))
        installation = delivery + timedelta(days=rng.randint(2, 20))
        ready = installation + timedelta(days=rng.randint(0, 12))
        wording = rng.choice(
            [
                "Une machine est achetee le {a}, livree le {d}, installee le {i} et prete a fonctionner le {r}. A partir de quelle date commence l'amortissement comptable ?",
                "Pour une immobilisation corporelle: achat {a}, livraison {d}, installation {i}, mise en service {r}. Quelle date retenir pour l'amortissement ?",
                "La facture de la machine date du {a}; elle arrive le {d}, les tests finissent apres installation le {i}, et l'actif est pret a fonctionner le {r}. Quand amortir ?",
            ]
        )
        cases.append(
            {
                "id": f"mut_fixed_asset_{i + 1:02d}",
                "family": "fixed_asset_depreciation",
                "prompt": wording.format(a=fr_date(acquisition), d=fr_date(delivery), i=fr_date(installation), r=fr_date(ready)),
                "expected": {
                    "workflow": "fixed_asset_depreciation_case",
                    "required": [fr_date(ready)],
                    "forbidden_start_dates": [fr_date(acquisition), fr_date(delivery), fr_date(installation)],
                },
            }
        )
    return cases


def revenue_cutoff_cases(rng: random.Random, count: int) -> list[dict[str, Any]]:
    cases = []
    for i in range(count):
        amount = rng.choice([90000, 120000, 180000, 240000, 360000])
        year = rng.choice([2025, 2026])
        start_month = rng.randint(1, 12)
        start = date(year, start_month, 1)
        end = add_months(start, 11)
        closing = date(year, 12, 31)
        total = month_count_inclusive(start, end)
        earned = months_earned(start, end, closing)
        deferred = total - earned
        earned_amount = round(amount * earned / total, 2)
        deferred_amount = round(amount - earned_amount, 2)
        wording = rng.choice(
            [
                "Contrat de maintenance de {amount} TND du {start} au {end}, encaisse en decembre {year}, cloture au 31 decembre {year}. Quel cut-off comptable et TVA ?",
                "Une prestation annuelle est payee d'avance pour {amount} TND et couvre la periode du {start} au {end}. A la cloture du 31 decembre {year}, quel produit reconnaitre ?",
                "Facture annuelle {amount} TND: periode du {start} au {end}; exercice clos le 31/12/{year}. Comment separer produit acquis et produit constate d'avance ?",
            ]
        )
        cases.append(
            {
                "id": f"mut_revenue_period_{i + 1:02d}",
                "family": "revenue_cutoff_prepaid_services",
                "prompt": wording.format(amount=_format_amount(amount), start=fr_date(start), end=fr_date(end), year=year),
                "expected": {
                    "workflow": "revenue_cutoff_tva_case",
                    "required": [f"{earned}/{total}", f"{deferred}/{total}", _format_amount(earned_amount), _format_amount(deferred_amount)],
                    "earned_fraction": f"{earned}/{total}",
                    "deferred_fraction": f"{deferred}/{total}",
                },
            }
        )

        future_amount = rng.choice([50000, 90000, 150000])
        service_month = rng.randint(2, 6)
        service_date = date(year + 1, service_month, rng.randint(1, 20))
        cases.append(
            {
                "id": f"mut_revenue_future_{i + 1:02d}",
                "family": "revenue_cutoff_prepaid_services",
                "prompt": f"Une societe tunisienne recoit en decembre {year} un paiement integral de {_format_amount(future_amount)} TND pour une prestation qui sera realisee le {fr_date(service_date)}. Que faire comptablement et en TVA a la cloture du 31/12/{year} ?",
                "expected": {
                    "workflow": "revenue_cutoff_tva_case",
                    "required": ["revenu 2025 est 0" if year == 2025 else f"revenu {year} est 0", _format_amount(future_amount), "encaissement avant realisation"],
                    "forbidden_fake_dates": [month for month in MONTHS if month not in norm(fr_date(service_date)) and month in ["fevrier", "avril"]],
                },
            }
        )
    return cases


def receivable_cases(rng: random.Random, count: int) -> list[dict[str, Any]]:
    cases = []
    for i in range(count):
        gross = rng.choice([75000, 120000, 180000, 260000])
        recovery = rng.choice([10000, 20000, 30000, 50000])
        if recovery >= gross:
            recovery = gross // 3
        months = rng.randint(6, 20)
        residual = gross - recovery
        wording = rng.choice(
            [
                "Une societe a une creance client de {gross} TND impayee depuis {months} mois au 31/12/2025. Apres la cloture, le client regle {recovery} TND. Quel traitement comptable et fiscal ?",
                "Client en retard depuis {months} mois: solde {gross} TND, relances envoyees, encaissement apres cloture de {recovery} TND. Quelle exposition et quelle provision examiner ?",
                "Creance douteuse de {gross} TND; paiement posterieur a la cloture {recovery} TND; retard {months} mois. Comment traiter le solde ?",
            ]
        )
        cases.append(
            {
                "id": f"mut_receivable_{i + 1:02d}",
                "family": "receivable_impairment_recovery_after_closing",
                "prompt": wording.format(gross=_format_amount(gross), months=months, recovery=_format_amount(recovery)),
                "expected": {
                    "workflow": "receivable_impairment_subsequent_event",
                    "required": [_format_amount(residual), f"{_format_amount(gross)} - {_format_amount(recovery)} = {_format_amount(residual)}"],
                    "forbidden": [f"{_format_amount(gross)} - {months}", "montant facture x", "produit constate d'avance"],
                },
            }
        )
    return cases


def tva_service_cases(rng: random.Random, count: int) -> list[dict[str, Any]]:
    cases = []
    for i in range(count):
        year = rng.choice([2025, 2026])
        collection = date(year, rng.randint(1, 10), rng.randint(1, 20))
        realization = collection + timedelta(days=rng.randint(20, 120))
        amount = rng.choice([30000, 80000, 120000])
        cases.append(
            {
                "id": f"mut_tva_service_{i + 1:02d}",
                "family": "tva_service_exigibility",
                "prompt": f"Une prestation de services tunisienne de {_format_amount(amount)} TND est encaissee le {fr_date(collection)} mais realisee le {fr_date(realization)}. Quelle consequence TVA ?",
                "expected": {
                    "workflow": "tva_operational_case",
                    "required": ["TVA", "exigible"],
                    "service_date": fr_date(realization),
                },
            }
        )
    return cases


def withholding_cases(rng: random.Random, count: int) -> list[dict[str, Any]]:
    cases = []
    natures = [
        ("honoraires de conseil", "prestation de services ou honoraires"),
        ("dividendes", "distribution de dividendes"),
        ("redevance de logiciel", "redevance/licence"),
        ("loyer", "loyer"),
    ]
    countries = [None, "France", "Italie", "Allemagne", "Algerie"]
    for i in range(count):
        nature, label = rng.choice(natures)
        country = rng.choice(countries)
        amount = rng.choice([15000, 45000, 120000])
        beneficiary = f"un beneficiaire non-resident etabli en {country}" if country else "un beneficiaire resident"
        cases.append(
            {
                "id": f"mut_withholding_{i + 1:02d}",
                "family": "withholding_tax_classification",
                "prompt": f"Une societe tunisienne paie {amount} TND de {nature} a {beneficiary}. Comment qualifier la retenue a la source ?",
                "expected": {
                    "workflow": "withholding_tax_classification_case",
                    "required": ["retenue a la source", "qualification"],
                    "treaty_required": bool(country),
                    "forbidden_rate": True,
                    "label": label,
                },
            }
        )
    return cases


def hierarchy_cases(rng: random.Random, count: int) -> list[dict[str, Any]]:
    cases = []
    for i in range(count):
        explicit_ifrs = rng.choice([False, False, True])
        if explicit_ifrs:
            prompt = "Une societe tunisienne prepare un reporting consolide IFRS pour son groupe. Quelle hierarchie entre SCT, normes comptables tunisiennes et IFRS ?"
            required = ["IFRS", "obligations tunisiennes"]
        else:
            prompt = rng.choice(
                [
                    "Pour une SARL tunisienne ordinaire, quelle norme appliquer si IAS/IFRS semble differer des normes comptables tunisiennes SCT ?",
                    "Quelle est la hierarchie des normes comptables pour une entreprise tunisienne: SCT, NC tunisiennes, IAS ou IFRS ?",
                    "Une societe tunisienne hesite entre IAS 16 et NC 05. Quel referentiel prime en comptabilite locale ?",
                ]
            )
            required = ["Normes Comptables Tunisiennes", "IAS/IFRS", "ne doivent pas remplacer"]
        cases.append(
            {
                "id": f"mut_hierarchy_{i + 1:02d}",
                "family": "accounting_standards_hierarchy",
                "prompt": prompt,
                "expected": {
                    "workflow": "accounting_standards_hierarchy_case",
                    "required": required,
                    "explicit_ifrs": explicit_ifrs,
                },
            }
        )
    return cases


def build_cases(seed: int, cases_per_workflow: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    cases.extend(fixed_asset_cases(rng, cases_per_workflow))
    cases.extend(revenue_cutoff_cases(rng, max(1, cases_per_workflow // 2)))
    cases.extend(receivable_cases(rng, cases_per_workflow))
    cases.extend(tva_service_cases(rng, cases_per_workflow))
    cases.extend(withholding_cases(rng, cases_per_workflow))
    cases.extend(hierarchy_cases(rng, cases_per_workflow))
    return cases


def validate_case(case: dict[str, Any], answer: str, trace: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    answer_key = norm(answer)
    expected = case["expected"]
    reasons: list[str] = []
    categories = {
        "wrong_deterministic_calculation": False,
        "contradictory_dates": False,
        "legacy_template_contamination": False,
        "fake_service_dates": False,
        "irrelevant_final_blocks": False,
    }

    if trace.get("workflow") != expected.get("workflow"):
        reasons.append(f"wrong_workflow:{trace.get('workflow')}!= {expected.get('workflow')}")

    for item in expected.get("required", []):
        if norm(str(item)) not in answer_key:
            reasons.append(f"missing_required:{item}")

    for item in expected.get("forbidden", []):
        if norm(str(item)) in answer_key:
            reasons.append(f"forbidden_visible:{item}")
            categories["wrong_deterministic_calculation"] = "-" in str(item)
            categories["legacy_template_contamination"] = categories["legacy_template_contamination"] or "montant facture" in norm(str(item))
            categories["irrelevant_final_blocks"] = categories["irrelevant_final_blocks"] or "produit constate" in norm(str(item))

    for wrong_date in expected.get("forbidden_start_dates", []):
        pattern = rf"amortissement[^.\n]{{0,120}}commence[^.\n]{{0,120}}{re.escape(norm(wrong_date))}"
        if re.search(pattern, answer_key):
            reasons.append(f"wrong_depreciation_start:{wrong_date}")
            categories["contradictory_dates"] = True

    if expected.get("treaty_required") and "convention" not in answer_key:
        reasons.append("missing_treaty_for_nonresident")

    if expected.get("forbidden_rate") and re.search(r"\b(5|10|15|20)\s*%", answer_key):
        reasons.append("invented_withholding_rate")
        categories["wrong_deterministic_calculation"] = True

    if case["family"] == "tva_service_exigibility":
        if not ("encaisse" in answer_key and "avant" in answer_key and "exigib" in answer_key):
            reasons.append("missing_tva_collection_before_realization_rule")

    consistency = trace.get("consistency") or {}
    contamination = trace.get("contamination") or {}
    if not consistency.get("pass", True):
        reasons.extend([f"consistency:{err}" for err in consistency.get("errors", [])])
    if not contamination.get("pass", True):
        reasons.extend([f"contamination:{err}" for err in contamination.get("errors", [])])
        for err in contamination.get("errors", []):
            if "service_date" in err or "february" in err or "decembre" in err:
                categories["fake_service_dates"] = True
            else:
                categories["legacy_template_contamination"] = True

    legacy_terms = ["ce dossier releve", "identifier le texte exact", "montant facture x", "traitement comptable et tva"]
    for term in legacy_terms:
        if term in answer_key:
            reasons.append(f"legacy_term:{term}")
            categories["legacy_template_contamination"] = True

    return not reasons, reasons, categories


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--cases-per-workflow", type=int, default=10)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    cases = build_cases(args.seed, args.cases_per_workflow)
    results = []
    totals = {
        "wrong_deterministic_calculations": 0,
        "contradictory_dates": 0,
        "legacy_template_contamination": 0,
        "fake_service_dates_not_in_prompt": 0,
        "irrelevant_final_answer_blocks": 0,
    }
    failures = []

    for case in cases:
        answer, trace = run_kernel(case["prompt"], case["expected"].get("workflow", ""))
        ok, reasons, categories = validate_case(case, answer, trace)
        if not ok:
            failures.append(case["id"])
        totals["wrong_deterministic_calculations"] += int(categories["wrong_deterministic_calculation"])
        totals["contradictory_dates"] += int(categories["contradictory_dates"])
        totals["legacy_template_contamination"] += int(categories["legacy_template_contamination"])
        totals["fake_service_dates_not_in_prompt"] += int(categories["fake_service_dates"])
        totals["irrelevant_final_answer_blocks"] += int(categories["irrelevant_final_blocks"])
        results.append(
            {
                "id": case["id"],
                "workflow_family": case["family"],
                "prompt": case["prompt"],
                "expected": case["expected"],
                "extracted_facts_json": trace.get("facts"),
                "deterministic_decision_object": trace.get("decision"),
                "final_visible_answer": answer,
                "consistency_validator_result": trace.get("consistency"),
                "contamination_validator_result": trace.get("contamination"),
                "pass": ok,
                "pass_fail_reason": "pass" if ok else "; ".join(reasons),
            }
        )

    report = {
        "seed": args.seed,
        "cases_per_workflow": args.cases_per_workflow,
        "total": len(results),
        "passed": len(results) - len(failures),
        "failed": failures,
        "acceptance_gate": totals,
        "acceptance_pass": not failures and all(value == 0 for value in totals.values()),
        "results": results,
    }

    output = args.output or ROOT / "reports" / f"deterministic_mutation_suite_seed_{args.seed}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"} | {"output": str(output)}, ensure_ascii=False, indent=2))
    return 1 if not report["acceptance_pass"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
