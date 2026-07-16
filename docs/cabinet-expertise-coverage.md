# Cabinet Expertise Coverage Map

This map defines the reusable cabinet workflows used by the accounting assistant. The goal is professional reasoning over cabinet cases, not memorized benchmark answers.

## Quality Levels

- `expert_pass`: useful cabinet-level answer applying the facts, splitting issues, using relevant sources, naming missing facts, and avoiding invented rates/articles.
- `safe_pass`: refuses or reserves correctly when facts or sources are insufficient.
- `fail`: wrong workflow, generic fallback, irrelevant source, hallucinated article/rate/deadline, or no fact application.

## Families

### 1. Fiscalite directe

Workflow: `direct_tax_deductibility_adjustment_case`

Coverage:
- IS, IRPP, retenues a la source, dividendes, charges deductibles, provisions, amortissements, avantages occultes, reintegrations extra-comptables.

Priority sources:
- `code_irpp_is_2011`
- `loi_finances_2026`
- `procedures_fiscales_2026`
- `loi_comptable`

Required reasoning:
- Distinguish accounting recognition, tax deductibility and extra-accounting reintegration.
- Identify taxpayer profile, beneficiary, residence, amount, period and supporting documents.
- Refuse to state rates or articles without direct passage support.

### 2. TVA

Workflow: `tva_operational_case`

Coverage:
- Territorialite, exportation de services, droit a deduction, exonerations, facturation, exigibilite, regularisations, justificatifs.

Priority sources:
- `tva_droit_consommation`
- `procedures_fiscales_2026`
- `loi_finances_2026`

Required reasoning:
- Separate field of application, territoriality, exemption, deduction and invoicing.
- Do not use IRPP/IS as primary support for VAT conclusions.
- If the invoice, client status or place of use is missing, reserve the conclusion.

### 3. Comptabilite

Workflow: `accounting_closing_estimate_case`

Coverage:
- Cut-off, revenus, charges, immobilisations, stocks, provisions, creances douteuses, evenements posterieurs, continuite d'exploitation, parties liees.

Priority sources:
- `nc_01_norme_generale`
- `nc_03_revenus`
- `nc_04_stocks`
- `nc_05_immobilisations_corporelles`
- `nc_14_eventualites_post_cloture`
- `nc_39_parties_liees`

Required reasoning:
- Identify the reporting period and recognition basis.
- Distinguish accounting estimate from tax treatment.
- Document management judgment, calculation, closing evidence and post-closing events.

### 4. Audit / CAC

Workflow: `audit_cac_response_case`

Coverage:
- Fraude, continuite, evenements posterieurs, opinion, gouvernance, documentation, refus de correction par la direction, limitations de travaux.

Priority sources:
- `audit_resume_gaida_normes_missions`
- `audit_resume_acceptation_controle_qualite`
- `code_societes_commerciales_2022`
- `textes_profession_comptable_2018`

Required reasoning:
- Identify timing relative to report date.
- Separate facts, audit evidence, governance communication, reporting impact and documentation.
- Do not merely define the CAC when the question asks what the CAC must do.

### 5. Droit des societes

Workflow: `company_law_governance_case`

Coverage:
- Distribution de benefices, conventions reglementees, associes/dirigeants, capital social, pertes, approbation des comptes.

Priority sources:
- `code_societes_commerciales_2022`
- `code_commerce_2014`
- `code_obligations_contrats_2015`

Required reasoning:
- Identify company form, decision-making body, statutory documents and approvals.
- Separate corporate validity, accounting impact and tax consequences.

### 6. Paie / Social

Workflow: `payroll_social_case`

Coverage:
- CNSS, retenues salariales, charges sociales, declarations employeur, avantages en nature.

Priority sources:
- CNSS F1, N40, N41, N42, N43, N44, N54, P212, P304, N66, P57, P58, A144 bis and P326 administrative forms.
- IRPP/IS and procedures fiscales for salary withholding, declarations and control issues.

Current limitation:
- The corpus now includes direct CNSS forms and attestations, but exact CNSS rates, deadlines or regime tables must still be treated as source-cadre unless a direct rate/deadline passage is retrieved.

Required reasoning:
- Mark CNSS rates/deadlines as source-cadre or source manquante unless a direct CNSS rate/deadline text is retrieved.
- Separate payroll, IRPP salary withholding, social contributions and employer declarations.

### 7. Procedure fiscale

Workflow: `tax_procedure_compliance_case`

Coverage:
- Declarations, delais, controle fiscal, penalites, recours, justificatifs, certificats.

Priority sources:
- `procedures_fiscales_2026`
- `code_irpp_is_2011`
- `tva_droit_consommation`
- `loi_finances_2026`

Required reasoning:
- Separate tax base from procedure.
- Identify notification date, tax concerned, period, amount and evidence.
- Refuse to invent deadlines or penalties without direct article support.

## Benchmark

Dataset:
- `app/data/accounting_benchmark_cabinet_coverage.jsonl`

Generator:
- `scripts/build_cabinet_coverage_benchmark.py`

It includes 35 cases: 7 families x 5 variants with changed wording, amounts, dates, taxpayer profiles, missing documents, conflicting facts and missing legal sources.
