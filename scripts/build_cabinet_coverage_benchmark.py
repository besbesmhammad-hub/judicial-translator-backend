from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "data" / "accounting_benchmark_cabinet_coverage.jsonl"

SECTIONS = ["Reponse", "Application pratique", "Points de vigilance", "Sources utilisees"]
FORBIDDEN = [
    "## Definition",
    "En premiere analyse, le point doit etre rattache principalement au cadre suivant",
    "Les sources disponibles ne permettent pas de produire une reponse suffisamment fiable",
    "article [X]",
    "source implicite",
]


def case(
    id: str,
    question: str,
    workflow: str,
    intent: str,
    contains: list[str],
    *,
    docs: list[str],
    missing: list[str] | None = None,
    forbidden: list[str] | None = None,
    allowed_workflows: list[str] | None = None,
) -> dict:
    return {
        "id": id,
        "question": question,
        "language": "francais",
        "expected_intent": intent,
        "expected_preferred_source": "legal_corpus",
        "expected_response_style": "practical_analysis",
        "expected_workflow": workflow,
        "allowed_workflows": allowed_workflows or [workflow],
        "expected_sections": SECTIONS,
        "expected_answer_contains": contains,
        "expected_selected_doc_ids": docs,
        "expected_direct_or_framework_doc_ids": docs[:2],
        "expected_missing_info_contains": missing or [],
        "forbidden_answer_contains": FORBIDDEN + (forbidden or []),
    }


CASES: list[dict] = []

CASES += [
    case(
        "coverage_direct_tax_is_reintegration",
        "Une SARL a comptabilise une charge de 45 000 TND sans contrat et avec facture peu detaillee. Peut-elle la deduire de l IS ou faut-il une reintegration extra-comptable ?",
        "direct_tax_deductibility_adjustment_case",
        "tax_calculation",
        ["Fiscalite directe", "deductibilite fiscale", "reintegration extra-comptable", "justificatifs"],
        docs=["code_irpp_is_2011", "procedures_fiscales_2026"],
        missing=["contrat/facture"],
    ),
    case(
        "coverage_direct_tax_irpp_withholding_service",
        "Une personne physique non residente facture des honoraires a une societe tunisienne. Quels controles IRPP, retenue a la source et certificat faut-il faire avant paiement ?",
        "direct_tax_deductibility_adjustment_case",
        "tax_calculation",
        ["retenue a la source", "non-resident", "certificat", "article fiscal direct"],
        docs=["code_irpp_is_2011", "procedures_fiscales_2026"],
    ),
    case(
        "coverage_direct_tax_hidden_benefit",
        "Le dirigeant utilise un actif de la societe a titre personnel. Comment analyser avantage occulte, IS et reintegration fiscale sans inventer de taux ?",
        "direct_tax_deductibility_adjustment_case",
        "tax_calculation",
        ["avantage occulte", "benefice imposable", "source-cadre", "taux"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "coverage_direct_tax_provision_not_supported",
        "Une provision est passee en comptabilite mais aucun dossier fiscal ne justifie sa deduction. Quelle position prudente doit prendre le cabinet ?",
        "direct_tax_deductibility_adjustment_case",
        "tax_calculation",
        ["provision", "deductibilite fiscale", "ne peut pas", "piece"],
        docs=["code_irpp_is_2011"],
        missing=["article fiscal direct"],
        allowed_workflows=["direct_tax_deductibility_adjustment_case", "accounting_tax_bridge_case"],
    ),
    case(
        "coverage_direct_tax_amortization_limit",
        "Une entreprise applique un amortissement fiscal plus rapide que l amortissement comptable. Quelles verifications IS et retraitements faut-il faire ?",
        "direct_tax_deductibility_adjustment_case",
        "tax_calculation",
        ["amortissement", "traitement comptable", "retraitement", "fiscal"],
        docs=["code_irpp_is_2011", "loi_comptable"],
    ),
]

CASES += [
    case(
        "coverage_tva_deduction_missing_invoice",
        "La societe veut recuperer la TVA sur un achat mais elle n a qu un bon de livraison, pas de facture conforme. Peut-on exercer le droit a deduction ?",
        "tva_operational_case",
        "legal_basis",
        ["TVA", "droit a deduction", "facture", "ne peut pas"],
        docs=["tva_droit_consommation", "procedures_fiscales_2026"],
        missing=["facture"],
    ),
    case(
        "coverage_tva_export_service_contract_only",
        "Une prestation exportee est couverte par un contrat mais pas encore par une facture definitive. Quels justificatifs TVA et facturation faut-il reunir ?",
        "tva_operational_case",
        "legal_basis",
        ["exportation de services", "facturation", "justificatifs", "TVA"],
        docs=["tva_droit_consommation", "procedures_fiscales_2026"],
    ),
    case(
        "coverage_tva_exigibility_advance",
        "Un client paie une avance avant livraison. Comment analyser exigibilite TVA, facture et regularisation eventuelle ?",
        "tva_operational_case",
        "legal_basis",
        ["exigibilite", "facture", "regularisation", "passage direct"],
        docs=["tva_droit_consommation"],
    ),
    case(
        "coverage_tva_exemption_without_basis",
        "Le commercial affirme que l operation est exoneree de TVA mais ne donne aucun texte. Quelle reserve doit formuler le cabinet ?",
        "tva_operational_case",
        "legal_basis",
        ["exoneration", "article TVA direct", "ne pas inventer", "source-cadre"],
        docs=["tva_droit_consommation"],
        missing=["article TVA direct"],
    ),
    case(
        "coverage_tva_conflicting_place_use",
        "Le contrat dit service realise en Tunisie, mais le client indique une utilisation a l etranger. Comment traiter territorialite et justificatifs ?",
        "tva_operational_case",
        "legal_basis",
        ["territorialite", "lieu", "justificatifs", "contradictions"],
        docs=["tva_droit_consommation", "procedures_fiscales_2026"],
    ),
]

CASES += [
    case(
        "coverage_accounting_stock_cutoff",
        "A la cloture, des marchandises sont facturees mais pas encore recues. Comment traiter cut-off, stocks, charges et justificatifs ?",
        "accounting_closing_estimate_case",
        "accounting_treatment",
        ["Comptabilite", "cut-off", "stocks", "pieces"],
        docs=["nc_01_norme_generale", "nc_04_stocks"],
    ),
    case(
        "coverage_accounting_revenue_no_delivery",
        "Un revenu est facture le 29 decembre mais la prestation est realisee en janvier. Peut-on le garder dans l exercice cloture ?",
        "accounting_closing_estimate_case",
        "accounting_treatment",
        ["revenu", "exercice", "ne peut pas", "rattachement"],
        docs=["nc_03_revenus", "nc_01_norme_generale"],
    ),
    case(
        "coverage_accounting_subsequent_event_conflict",
        "Apres cloture, un litige confirme une perte probable existant deja avant la cloture. Quel traitement comptable et quelles notes ?",
        "accounting_closing_estimate_case",
        "accounting_treatment",
        ["evenement posterieur", "provision", "notes", "estimation"],
        docs=["nc_14_eventualites_post_cloture", "nc_01_norme_generale"],
    ),
    case(
        "coverage_accounting_related_party_disclosure",
        "Une transaction significative avec une partie liee est comptabilisee mais aucune note annexe n est preparee. Quels risques ?",
        "accounting_closing_estimate_case",
        "accounting_treatment",
        ["parties liees", "information", "notes", "documentation"],
        docs=["nc_39_parties_liees", "nc_01_norme_generale"],
    ),
    case(
        "coverage_accounting_continuity_no_budget",
        "La direction retient la continuite d exploitation mais ne fournit aucun budget de tresorerie. Peut-on valider l hypothese ?",
        "going_concern_case_analysis",
        "audit",
        ["continuite", "budget de tresorerie", "ne peut pas", "hypothese"],
        docs=["nc_01_norme_generale", "cadre_conceptuel_comptable"],
        missing=["piece justificative"],
    ),
]

CASES += [
    case(
        "coverage_audit_refusal_correction",
        "Le CAC identifie une anomalie significative, mais la direction refuse de corriger les comptes. Que doit-il analyser pour son opinion ?",
        "audit_cac_response_case",
        "legal_basis",
        ["Audit/CAC", "refus de correction", "opinion", "gouvernance"],
        docs=["audit_resume_gaida_normes_missions", "audit_resume_acceptation_controle_qualite"],
    ),
    case(
        "coverage_audit_scope_limitation",
        "L auditeur ne peut pas assister a l inventaire et aucune procedure alternative fiable n est possible. Quelle analyse de limitation de travaux ?",
        "audit_cac_response_case",
        "legal_basis",
        ["limitation de travaux", "elements probants", "opinion", "documentation"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
    case(
        "coverage_audit_fraud_governance",
        "Une fraude est detectee avant la signature du rapport. Quelles communications, diligences et documentation sont attendues ?",
        "audit_cac_response_case",
        "legal_basis",
        ["fraude", "gouvernance", "documentation", "rapport"],
        docs=["audit_resume_gaida_normes_missions", "code_societes_commerciales_2022"],
    ),
    case(
        "coverage_audit_subsequent_event_after_report",
        "Un evenement posterieur significatif est decouvert apres emission du rapport. Comment raisonner sans redefinir le CAC ?",
        "audit_cac_response_case",
        "legal_basis",
        ["evenements posterieurs", "rapport", "opinion", "date"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
    case(
        "coverage_audit_management_no_evidence",
        "La direction affirme qu un financement est obtenu mais refuse de communiquer la lettre bancaire. Quelle position d audit ?",
        "audit_cac_response_case",
        "legal_basis",
        ["preuves", "direction", "ne peut pas", "elements probants"],
        docs=["audit_resume_gaida_normes_missions"],
        missing=["preuves disponibles"],
    ),
]

CASES += [
    case(
        "coverage_company_approval_accounts_late",
        "Une SARL n a pas encore approuve ses comptes et veut distribuer des benefices. Quels controles societaires et fiscaux faire ?",
        "company_law_governance_case",
        "legal_basis",
        ["Droit des societes", "approbation des comptes", "distribution", "PV"],
        docs=["code_societes_commerciales_2022", "code_irpp_is_2011"],
    ),
    case(
        "coverage_company_regulated_agreement",
        "Le gerant conclut une convention avec sa societe sans autorisation prealable. Quels risques et documents faut-il verifier ?",
        "related_party_transaction_case",
        "legal_basis",
        ["convention", "gerant", "autorisation", "approbation"],
        docs=["code_societes_commerciales_2022"],
        allowed_workflows=["company_law_governance_case", "related_party_transaction_case"],
    ),
    case(
        "coverage_company_losses_capital",
        "Les pertes absorbent une partie importante du capital social. Que doit analyser le cabinet avant l assemblee ?",
        "company_law_governance_case",
        "legal_basis",
        ["pertes", "capital social", "assemblee", "forme sociale"],
        docs=["code_societes_commerciales_2022"],
    ),
    case(
        "coverage_company_manager_shareholder_conflict",
        "Un associe dirigeant vote une operation qui lui profite personnellement. Comment separer gouvernance, comptes et fiscalite ?",
        "company_law_governance_case",
        "legal_basis",
        ["associe", "dirigeant", "gouvernance", "fiscal"],
        docs=["code_societes_commerciales_2022", "code_irpp_is_2011"],
    ),
    case(
        "coverage_company_missing_statutes",
        "Le client demande si une decision d associes est valable mais ne fournit ni statuts ni PV. Peut-on conclure ?",
        "company_law_governance_case",
        "legal_basis",
        ["statuts", "PV", "ne peut pas", "forme sociale"],
        docs=["code_societes_commerciales_2022"],
        missing=["statuts"],
    ),
]

CASES += [
    case(
        "coverage_social_benefit_in_kind",
        "Un avantage en nature est accorde a un salarie. Comment analyser paie, IRPP salarial, CNSS et justificatifs ?",
        "payroll_social_case",
        "legal_basis",
        ["Paie/social", "IRPP salarial", "CNSS", "texte CNSS direct"],
        docs=["code_irpp_is_2011", "procedures_fiscales_2026"],
        missing=["texte CNSS direct"],
    ),
    case(
        "coverage_social_missing_payslip",
        "L employeur a paye des salaires mais ne fournit pas les bulletins de paie. Peut-on valider charges sociales et retenues salariales ?",
        "payroll_social_case",
        "legal_basis",
        ["bulletin de paie", "retenues", "ne peut pas", "charges sociales"],
        docs=["code_irpp_is_2011"],
        missing=["bulletin de paie"],
    ),
    case(
        "coverage_social_employer_declaration",
        "Quelles declarations employeur faut-il verifier quand la paie de mars est payee en retard ?",
        "payroll_social_case",
        "legal_basis",
        ["declarations", "employeur", "periode", "delai"],
        docs=["procedures_fiscales_2026", "code_irpp_is_2011"],
    ),
    case(
        "coverage_social_nonresident_employee",
        "Un salarie non resident travaille ponctuellement pour une societe tunisienne. Quels points paie, retenue et convention doivent rester sous reserve ?",
        "payroll_social_case",
        "legal_basis",
        ["non resident", "retenue", "convention", "source-cadre"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "coverage_social_cnss_source_gap",
        "Le client demande le taux CNSS exact applicable. Le corpus contient-il assez de sources pour donner un taux ?",
        "payroll_social_case",
        "legal_basis",
        ["CNSS", "taux", "ne pas inventer", "texte CNSS direct"],
        docs=["code_irpp_is_2011"],
        missing=["texte CNSS direct"],
    ),
]

CASES += [
    case(
        "coverage_procedure_tax_audit_notice",
        "La societe recoit une notification de controle fiscal. Quels delais, pieces et recours faut-il examiner avant de repondre ?",
        "tax_procedure_compliance_case",
        "legal_basis",
        ["Procedure fiscale", "controle", "delais", "recours"],
        docs=["procedures_fiscales_2026"],
    ),
    case(
        "coverage_procedure_late_declaration_penalty",
        "Une declaration fiscale est deposee en retard. Peut-on calculer la penalite sans connaitre l impot, la date et le texte applicable ?",
        "tax_procedure_compliance_case",
        "legal_basis",
        ["penalite", "declaration", "ne peut pas", "article direct"],
        docs=["procedures_fiscales_2026"],
        missing=["date de notification"],
    ),
    case(
        "coverage_procedure_missing_certificate",
        "Le client a opere une retenue mais n a pas remis de certificat. Quels risques procedure et justificatifs ?",
        "tax_procedure_compliance_case",
        "legal_basis",
        ["certificat", "retenue", "justificatifs", "declaration"],
        docs=["procedures_fiscales_2026", "code_irpp_is_2011"],
    ),
    case(
        "coverage_procedure_vat_invoice_control",
        "Lors d un controle TVA, l administration rejette des factures incompletes. Comment preparer la defense documentaire ?",
        "tax_procedure_compliance_case",
        "legal_basis",
        ["controle", "TVA", "factures", "justificatifs"],
        docs=["procedures_fiscales_2026", "tva_droit_consommation"],
    ),
    case(
        "coverage_procedure_recours_missing_notification",
        "Le client veut introduire un recours mais ne transmet pas la notification de redressement. Peut-on conseiller le delai ?",
        "tax_procedure_compliance_case",
        "legal_basis",
        ["recours", "notification", "ne peut pas", "delai"],
        docs=["procedures_fiscales_2026"],
        missing=["date de notification"],
    ),
]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for item in CASES:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"wrote {len(CASES)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
