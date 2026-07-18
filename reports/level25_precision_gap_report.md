# Level 2/2.5 Precision Gap Report

- Benchmark cases: 61
- OK requests: 61
- Source precision pass: 58/61
- Expert pass: 43/61
- Content quality pass: 43/61
- Cases requiring precision work: 18

## Priority Summary
- Priority A: 11
- Priority B: 7
- Priority C: 0

## Priority A - Must Fix Before Cabinet Use

### tax_dividendes_2026
- Question: Une SARL tunisienne distribue des dividendes en 2026. Quelles retenues a la source faut il verifier avant paiement ?
- Workflow: `company_law_governance_case`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source, unclassified`
- Root cause: `weak retrieval` (weak routing)
- Missing: Dividend answer must explicitly cover withholding, declaration/reversement, certificate/proof, and beneficiary profile.
- Selected sources: `code_irpp_is_2025`/direct_passage/p85, `loi_finances_2026`/framework_source/p1, `procedures_fiscales_2026`/framework_source/p1, `code_societes_commerciales_2022`/unclassified/p1, `code_irpp_is_2011`/unclassified/p1
- Substance failures: dividends_mentions_withholding, dividends_mentions_declaration
- Source precision failures: none
- Recommended fix: Route dividend + withholding questions to shareholder_split_tax_analysis, not company_law_governance_case; require retenue/declaration/certificate phrases.

### acct_goodwill_amortissement
- Question: Une societe peut elle amortir un goodwill et quels textes faut il verifier avant de conclure ?
- Workflow: `llm_provider`
- Current answer status: `fail`
- Support levels: `unclassified`
- Root cause: `missing article / weak retrieval` (weak source-support formatting)
- Missing: Directly tagged support from IFRS 3/NC 38 on goodwill treatment and impairment test.
- Selected sources: `ifrs_3_regroupements_entreprises`/unclassified/p5, `ifrs_3_regroupements_entreprises`/unclassified/p8, `nc_38_regroupements_entreprises`/unclassified/p10, `nc_38_regroupements_entreprises`/unclassified/p9
- Substance failures: none
- Source precision failures: source_precision_visible, amortization_has_direct_passage
- Recommended fix: Add source precision rules for IFRS 3 and NC 38 goodwill terms; do not accept unclassified sources for goodwill conclusions.

### level2_dividendes_associe_resident_prudent
- Question: Une SARL tunisienne distribue 250 000 TND de dividendes en 2026 a un associe resident. Quelles sont les consequences fiscales ? Citez les bases legales.
- Workflow: `shareholder_split_tax_analysis`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Single resident shareholder analysis should apply facts directly instead of a generic beneficiary-by-beneficiary template.
- Selected sources: `code_irpp_is_2025`/direct_passage/p85, `loi_finances_2026`/framework_source/p5, `procedures_fiscales_2026`/framework_source/p1
- Substance failures: none
- Source precision failures: none
- Recommended fix: Use the current IRPP/IS direct passage plus finance-law framework to produce a fact-specific dividend checklist; avoid generic multi-beneficiary wording for one beneficiary.

### level2_tva_services_france_sources_tva
- Question: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?
- Workflow: `tva_operational_case`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Final answer must use retrieved TVA/treaty sources to conclude the checks for the exact B2B/B2C fact pattern.
- Selected sources: `tva_droit_consommation`/direct_passage/p14, `procedures_fiscales_2026`/framework_source/p1, `loi_finances_2026`/direct_passage/p6, `convention_fiscale_france_tunisie_texte_1973`/direct_passage/p8, `boi_france_tunisie_convention_fiscale_2012`/direct_passage/p4
- Substance failures: none
- Source precision failures: none
- Recommended fix: Turn retrieved TVA/treaty passages into a fact-sensitive answer: client status, place of use, invoicing, justificatifs, missing facts.

### level2_fraude_apres_rapport_cac
- Question: Un commissaire aux comptes decouvre une fraude apres l emission de son rapport. Que doit il faire ?
- Workflow: `audit_cac_response_case`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source, unclassified`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: CAC response must state concrete obligations by timing: communication, governance, reassessment of opinion/report, documentation.
- Selected sources: `audit_resume_gaida_normes_missions`/direct_passage/p2, `audit_resume_acceptation_controle_qualite`/direct_passage/p3, `code_societes_commerciales_2022`/framework_source/p139, `textes_profession_comptable_2018`/unclassified/p1
- Substance failures: none
- Source precision failures: none
- Recommended fix: Create no new fastpath yet; strengthen audit_cac_response_case generation so timing changes before/after signature alter obligations.

### level2_amortissement_immobilisation_cloture
- Question: Comment analyser l amortissement d une immobilisation corporelle avant cloture ?
- Workflow: `accounting_closing_estimate_case`
- Current answer status: `fail`
- Support levels: `direct_passage, unclassified`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split.
- Selected sources: `nc_05_immobilisations_corporelles`/direct_passage/p2, `ias_16_immobilisations_corporelles`/direct_passage/p7, `nc_01_norme_generale`/direct_passage/p7, `nc_14_eventualites_post_cloture`/unclassified/p1, `nc_39_parties_liees`/unclassified/p1
- Substance failures: amortization_mentions_service_date, amortization_mentions_accounting_basis
- Source precision failures: none
- Recommended fix: Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction.

### level2_tva_services_client_francais_non_assujetti
- Question: Une societe tunisienne fournit une prestation informatique a un client francais non assujetti a la TVA. Quel regime TVA faut il verifier ?
- Workflow: `level3_multi_domain_case_analysis`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Final answer must use retrieved TVA/treaty sources to conclude the checks for the exact B2B/B2C fact pattern.
- Selected sources: `tva_droit_consommation`/direct_passage/p14, `procedures_fiscales_2026`/framework_source/p1, `code_irpp_is_2025`/direct_passage/p89, `loi_finances_2026`/direct_passage/p6, `convention_fiscale_france_tunisie`/direct_passage/p4
- Substance failures: none
- Source precision failures: none
- Recommended fix: Turn retrieved TVA/treaty passages into a fact-sensitive answer: client status, place of use, invoicing, justificatifs, missing facts.

### level2_dividendes_associe_non_resident
- Question: Une SARL tunisienne distribue des dividendes en 2026 a un associe non resident. Quels points fiscaux faut il verifier ?
- Workflow: `shareholder_split_tax_analysis`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source, missing_source`
- Root cause: `missing document` (missing document)
- Missing: Country/treaty passage is missing; answer should reserve treaty rate and list residence certificate/treaty facts.
- Selected sources: `code_irpp_is_2025`/direct_passage/p85, `loi_finances_2026`/framework_source/p5, `procedures_fiscales_2026`/framework_source/p1, `convention_fiscale_applicable`/missing_source/pNone
- Substance failures: none
- Source precision failures: none
- Recommended fix: Keep missing_source reservation for treaty until residence country/treaty passage is known; ask for country and certificate of tax residence.

### level2_fraude_avant_signature_rapport_cac
- Question: Un commissaire aux comptes decouvre une fraude avant la signature de son rapport. Que doit il faire ?
- Workflow: `audit_cac_response_case`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source, unclassified`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: CAC response must state concrete obligations by timing: communication, governance, reassessment of opinion/report, documentation.
- Selected sources: `audit_resume_gaida_normes_missions`/direct_passage/p2, `audit_resume_acceptation_controle_qualite`/direct_passage/p3, `code_societes_commerciales_2022`/framework_source/p139, `textes_profession_comptable_2018`/unclassified/p1
- Substance failures: none
- Source precision failures: none
- Recommended fix: Create no new fastpath yet; strengthen audit_cac_response_case generation so timing changes before/after signature alter obligations.

### level2_amortissement_mise_en_service_novembre
- Question: Une immobilisation corporelle a ete achetee en septembre mais mise en service en novembre. Comment raisonner l amortissement ?
- Workflow: `fixed_asset_component_depreciation_case`
- Current answer status: `fail`
- Support levels: `direct_passage`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split.
- Selected sources: `nc_05_immobilisations_corporelles`/direct_passage/p2, `ias_16_immobilisations_corporelles`/direct_passage/p7, `code_irpp_is_2025`/direct_passage/p14, `nc_01_norme_generale`/direct_passage/p7
- Substance failures: none
- Source precision failures: none
- Recommended fix: Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction.

### level2_user_amortissement_date_depart_15_septembre
- Question: Une immobilisation est achetee le 15 septembre. A partir de quelle date commence son amortissement ? Quels textes ou normes faut-il consulter ?
- Workflow: `accounting_closing_estimate_case`
- Current answer status: `fail`
- Support levels: `direct_passage, unclassified`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split.
- Selected sources: `nc_05_immobilisations_corporelles`/direct_passage/p2, `ias_16_immobilisations_corporelles`/direct_passage/p7, `nc_01_norme_generale`/direct_passage/p7, `nc_14_eventualites_post_cloture`/unclassified/p1, `nc_39_parties_liees`/unclassified/p1
- Substance failures: amortization_mentions_service_date, amortization_mentions_accounting_basis
- Source precision failures: none
- Recommended fix: Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction.


## Priority B - Useful Improvement, Currently Reserved/Safe Enough

### acct_subvention_investissement
- Question: Comment analyser comptablement une subvention d investissement recue par une entreprise tunisienne ?
- Workflow: `fallback_after_provider_failure`
- Current answer status: `safe_pass only`
- Support levels: `unclassified`
- Root cause: `weak answer generation` (weak answer generation / provider fallback)
- Missing: Provider-safe fallback replaced the cabinet answer; needs accounting treatment from NC 12 with direct source support.
- Selected sources: `nc_12_subventions_publiques`/unclassified/p4, `nc_12_subventions_publiques`/unclassified/p3, `nc_40_structures_sportives`/unclassified/p36, `code_comptabilite_publique`/unclassified/p1
- Substance failures: no_guardrail_block
- Source precision failures: none
- Recommended fix: Add NC 12 precision rules and a grounded fallback using retrieved NC 12 excerpts when provider generation is blocked.

### general_lois_tva_tunisie
- Question: Donnez-moi les lois de TVA en Tunisie généralement.
- Workflow: `fastpath`
- Current answer status: `fail`
- Support levels: `unclassified`
- Root cause: `missing article / weak retrieval` (weak source-support formatting)
- Missing: Fastpath answer is good, but source support labels are unclassified and source-precision wording is not visible.
- Selected sources: `tva_droit_consommation`/unclassified/p2, `procedures_fiscales_2026`/unclassified/p1, `loi_finances_2026`/unclassified/p1
- Substance failures: none
- Source precision failures: source_precision_visible
- Recommended fix: Classify canonical fastpath sources as framework_source/direct_passage and include the existing source-support wording in debug/output checks.

### loi_finances_modifie_code_tva
- Question: Une loi de finances peut-elle modifier le Code TVA ?
- Workflow: `fastpath`
- Current answer status: `fail`
- Support levels: `unclassified`
- Root cause: `missing article / weak retrieval` (weak source-support formatting)
- Missing: Fastpath answer is good, but source support labels are unclassified and source-precision wording is not visible.
- Selected sources: `tva_droit_consommation`/unclassified/p2, `loi_finances_2026`/unclassified/p1, `procedures_fiscales_2026`/unclassified/p1
- Substance failures: none
- Source precision failures: source_precision_visible
- Recommended fix: Classify canonical fastpath sources as framework_source/direct_passage and include the existing source-support wording in debug/output checks.

### level2_provision_creances_douteuses_deductible
- Question: Dans quelles conditions une provision pour creances douteuses est elle deductible ?
- Workflow: `receivable_impairment_subsequent_event`
- Current answer status: `fail`
- Support levels: `direct_passage`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Answer must stay focused on accounting provision and fiscal deductibility conditions; avoid irrelevant post-closing recovery unless facts include it.
- Selected sources: `nc_01_norme_generale`/direct_passage/p35, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage/p1, `ias_10_evenements_post_cloture`/direct_passage/p2, `code_irpp_is_2025`/direct_passage/p10
- Substance failures: none
- Source precision failures: none
- Recommended fix: Split generic receivable definition from subsequent-event workflow; only discuss post-closing recovery when present in facts.

### level2_provision_creance_douteuse_sans_justificatifs
- Question: Dans quelles conditions une provision pour creance douteuse peut elle etre deductibile si aucune action de recouvrement ni justificatifs ne sont disponibles ?
- Workflow: `direct_tax_deductibility_adjustment_case`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source, unclassified`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Answer must stay focused on accounting provision and fiscal deductibility conditions; avoid irrelevant post-closing recovery unless facts include it.
- Selected sources: `code_irpp_is_2025`/direct_passage/p10, `nc_01_norme_generale`/direct_passage/p35, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage/p1, `procedures_fiscales_2026`/framework_source/p1, `code_irpp_is_2011`/unclassified/p1
- Substance failures: receivable_mentions_individualized
- Source precision failures: none
- Recommended fix: Split generic receivable definition from subsequent-event workflow; only discuss post-closing recovery when present in facts.

### level2_user_tva_prestation_informatique_france_assujetti
- Question: Une societe tunisienne fournit une prestation informatique a une societe etablie en France. Le client est assujetti a la TVA dans son pays. Quel est le regime TVA applicable en Tunisie ? Quelles dispositions legales doivent etre examinees ?
- Workflow: `level3_multi_domain_case_analysis`
- Current answer status: `fail`
- Support levels: `direct_passage, framework_source`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Final answer must use retrieved TVA/treaty sources to conclude the checks for the exact B2B/B2C fact pattern.
- Selected sources: `tva_droit_consommation`/direct_passage/p14, `procedures_fiscales_2026`/framework_source/p1, `code_irpp_is_2025`/direct_passage/p89, `loi_finances_2026`/direct_passage/p6, `convention_fiscale_france_tunisie`/direct_passage/p4
- Substance failures: none
- Source precision failures: none
- Recommended fix: Turn retrieved TVA/treaty passages into a fact-sensitive answer: client status, place of use, invoicing, justificatifs, missing facts.

### level2_user_creance_douteuse_comptable_fiscal
- Question: Une societe constate une creance douteuse. Dans quelles conditions une provision est-elle comptablement et fiscalement deductible ?
- Workflow: `receivable_impairment_subsequent_event`
- Current answer status: `fail`
- Support levels: `direct_passage`
- Root cause: `weak answer generation` (weak answer generation)
- Missing: Answer must stay focused on accounting provision and fiscal deductibility conditions; avoid irrelevant post-closing recovery unless facts include it.
- Selected sources: `nc_01_norme_generale`/direct_passage/p35, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage/p1, `ias_10_evenements_post_cloture`/direct_passage/p2, `code_irpp_is_2025`/direct_passage/p10
- Substance failures: none
- Source precision failures: none
- Recommended fix: Split generic receivable definition from subsequent-event workflow; only discuss post-closing recovery when present in facts.


## New Corpus Impact

### tax_dividendes_2026
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source
- Current sources: `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source, `code_societes_commerciales_2022`/unclassified, `code_irpp_is_2011`/unclassified

### tva_export_client_etranger
- Movement: tva_droit_consommation: unclassified -> framework_source
- Old sources: `tva_droit_consommation`/unclassified, `code_irpp_is_2011`/unclassified
- Current sources: `tva_droit_consommation`/framework_source, `procedures_fiscales_2026`/framework_source, `loi_finances_2026`/direct_passage, `convention_fiscale_france_tunisie`/direct_passage, `boi_france_tunisie_convention_fiscale_2012`/direct_passage

### tax_non_resident_services
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/unclassified, `code_obligations_contrats_2015`/unclassified
- Current sources: `tva_droit_consommation`/direct_passage, `procedures_fiscales_2026`/framework_source, `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/direct_passage, `convention_fiscale_applicable`/missing_source

### tax_regularisation_dettes
- Movement: code_irpp_is_2011: unclassified -> direct_passage
- Old sources: `note_generale_regularisation_dettes_fiscales_2026`/unclassified, `code_irpp_is_2011`/unclassified, `droits_taxes_hors_codes`/unclassified
- Current sources: `procedures_fiscales_2026`/framework_source, `code_irpp_is_2011`/direct_passage, `tva_droit_consommation`/framework_source, `formulaire_declaration_mensuelle_ar_2026`/direct_passage, `formulaire_declaration_is_2026`/framework_source

### tax_dividendes_associe_resident_2026
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source
- Current sources: `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source

### acct_provision_clients_douteux
- Movement: nc_01_norme_generale: unclassified -> direct_passage
- Old sources: `nc_34_microcredit_revenus`/unclassified, `nc_01_norme_generale`/unclassified, `nc_19_etats_financiers_intermediaires`/unclassified
- Current sources: `nc_01_norme_generale`/direct_passage, `nc_14_eventualites_post_cloture`/direct_passage, `nc_39_parties_liees`/direct_passage, `nc_03_revenus`/direct_passage, `nc_04_stocks`/direct_passage

### audit_anomalie_apres_rapport
- Movement: audit_resume_acceptation_controle_qualite: unclassified -> direct_passage, audit_resume_gaida_normes_missions: unclassified -> direct_passage
- Old sources: `audit_resume_acceptation_controle_qualite`/unclassified, `audit_resume_gaida_normes_missions`/unclassified, `rapport_cac_innorpi_2021`/unclassified
- Current sources: `audit_resume_gaida_normes_missions`/direct_passage, `audit_resume_acceptation_controle_qualite`/direct_passage, `code_societes_commerciales_2022`/direct_passage, `convention_fiscale_tunisie_mali`/unclassified, `textes_profession_comptable_2018`/unclassified

### def_retenue_source
- Movement: code_irpp_is_2011: unclassified -> direct_passage
- Old sources: `code_irpp_is_2011`/unclassified, `droits_taxes_hors_codes`/unclassified
- Current sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/direct_passage, `procedures_fiscales_2026`/framework_source, `loi_comptable`/direct_passage, `convention_fiscale_france_tunisie`/direct_passage

### cmp_tva_collectee_deductible
- Movement: tva_droit_consommation: unclassified -> framework_source
- Old sources: `tva_droit_consommation`/unclassified
- Current sources: `tva_droit_consommation`/framework_source, `procedures_fiscales_2026`/framework_source, `loi_finances_2026`/direct_passage, `convention_fiscale_france_tunisie`/direct_passage, `boi_france_tunisie_convention_fiscale_2012`/direct_passage

### general_lois_fiscales_tunisie
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `enregistrement_timbre`/unclassified, `fiscalite_locale`/unclassified
- Current sources: `code_irpp_is_2025`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `enregistrement_timbre`/unclassified, `fiscalite_locale_2026`/unclassified

### general_lois_fiscales_tunisie_donnez_moi
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `enregistrement_timbre`/unclassified, `fiscalite_locale`/unclassified
- Current sources: `code_irpp_is_2025`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `enregistrement_timbre`/unclassified, `fiscalite_locale_2026`/unclassified

### cmp_procedures_fiscales_vs_irpp_is
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/unclassified, `procedures_fiscales_2026`/unclassified
- Current sources: `code_irpp_is_2025`/unclassified, `procedures_fiscales_2026`/unclassified

### sources_droit_fiscal_tunisien
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `enregistrement_timbre`/unclassified, `fiscalite_locale`/unclassified
- Current sources: `code_irpp_is_2025`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `enregistrement_timbre`/unclassified, `fiscalite_locale_2026`/unclassified

### hierarchie_normes_fiscales_tunisie
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `loi_finances_2026`/unclassified
- Current sources: `code_irpp_is_2025`/unclassified, `tva_droit_consommation`/unclassified, `procedures_fiscales_2026`/unclassified, `loi_finances_2026`/unclassified

### level2_dividendes_associe_resident_prudent
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source
- Current sources: `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source

### level2_provision_creances_douteuses_deductible
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `procedures_fiscales_2026`/framework_source
- Current sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2025`/direct_passage

### level2_dividendes_associe_non_resident
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source
- Current sources: `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source, `convention_fiscale_applicable`/missing_source

### level2_amortissement_mise_en_service_novembre
- Movement: old/historical source -> current source
- Old sources: `nc_05_immobilisations_corporelles`/direct_passage, `ias_16_immobilisations_corporelles`/direct_passage, `code_irpp_is_2011`/direct_passage, `nc_01_norme_generale`/direct_passage
- Current sources: `nc_05_immobilisations_corporelles`/direct_passage, `ias_16_immobilisations_corporelles`/direct_passage, `code_irpp_is_2025`/direct_passage, `nc_01_norme_generale`/direct_passage

### level2_provision_creance_douteuse_sans_justificatifs
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `procedures_fiscales_2026`/framework_source
- Current sources: `code_irpp_is_2025`/direct_passage, `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `procedures_fiscales_2026`/framework_source, `code_irpp_is_2011`/unclassified

### level2_user_dividendes_cloture_2025_avril_2026
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source
- Current sources: `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source

### level2_user_creance_douteuse_comptable_fiscal
- Movement: old/historical source -> current source
- Old sources: `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `nc_14_eventualites_post_cloture`/direct_passage, `code_irpp_is_2011`/direct_passage, `ias_12_impots_resultat`/direct_passage
- Current sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2025`/direct_passage

### level3_cross_border_it_services_france_120k
- Movement: old/historical source -> current source
- Old sources: `tva_droit_consommation`/direct_passage, `procedures_fiscales_2026`/framework_source, `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/direct_passage, `convention_fiscale_france_tunisie`/direct_passage
- Current sources: `tva_droit_consommation`/direct_passage, `procedures_fiscales_2026`/framework_source, `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/direct_passage, `convention_fiscale_france_tunisie`/direct_passage

### level3_mixed_dividends_three_shareholders
- Movement: old/historical source -> current source
- Old sources: `code_irpp_is_2011`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source, `convention_fiscale_france_tunisie`/direct_passage
- Current sources: `code_irpp_is_2025`/direct_passage, `loi_finances_2026`/framework_source, `procedures_fiscales_2026`/framework_source, `convention_fiscale_france_tunisie`/direct_passage, `convention_fiscale_france_tunisie_texte_1973`/direct_passage

### level3_annual_maintenance_upfront_cutoff_tva
- Movement: old/historical source -> current source
- Old sources: `nc_03_revenus`/direct_passage, `nc_01_norme_generale`/direct_passage, `tva_droit_consommation`/direct_passage, `code_irpp_is_2011`/direct_passage
- Current sources: `nc_03_revenus`/direct_passage, `nc_01_norme_generale`/direct_passage, `tva_droit_consommation`/direct_passage, `code_irpp_is_2025`/direct_passage

### level3_creance_douteuse_recouvrement_post_cloture
- Movement: old/historical source -> current source
- Old sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2011`/direct_passage
- Current sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2025`/direct_passage

### level3_creance_douteuse_recouvrement_post_cloture_accents
- Movement: old/historical source -> current source
- Old sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2011`/direct_passage
- Current sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2025`/direct_passage

### level3_creance_client_ecritures_deductibilite_post_cloture
- Movement: old/historical source -> current source
- Old sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2011`/direct_passage
- Current sources: `nc_01_norme_generale`/direct_passage, `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `ias_10_evenements_post_cloture`/direct_passage, `code_irpp_is_2025`/direct_passage

### level3_related_party_property_below_market
- Movement: old/historical source -> current source
- Old sources: `nc_39_parties_liees`/direct_passage, `code_societes_commerciales_2022`/direct_passage, `code_irpp_is_2011`/direct_passage, `audit_resume_gaida_normes_missions`/direct_passage
- Current sources: `nc_39_parties_liees`/direct_passage, `code_societes_commerciales_2022`/direct_passage, `code_irpp_is_2025`/direct_passage, `audit_resume_gaida_normes_missions`/direct_passage

### level3_consulting_cash_weak_evidence
- Movement: old/historical source -> current source
- Old sources: `loi_comptable`/direct_passage, `code_irpp_is_2011`/direct_passage, `procedures_fiscales_2026`/framework_source, `nc_01_norme_generale`/direct_passage
- Current sources: `loi_comptable`/direct_passage, `code_irpp_is_2025`/direct_passage, `procedures_fiscales_2026`/framework_source, `nc_01_norme_generale`/direct_passage

### level3_accounting_provision_not_tax_deductible
- Movement: old/historical source -> current source
- Old sources: `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `nc_14_eventualites_post_cloture`/direct_passage, `code_irpp_is_2011`/direct_passage, `ias_12_impots_resultat`/direct_passage
- Current sources: `ias_37_provisions_passifs_actifs_eventuels`/direct_passage, `nc_14_eventualites_post_cloture`/direct_passage, `code_irpp_is_2025`/direct_passage, `ias_12_impots_resultat`/direct_passage

### level3_fixed_asset_component_depreciation_machine
- Movement: old/historical source -> current source
- Old sources: `nc_05_immobilisations_corporelles`/direct_passage, `ias_16_immobilisations_corporelles`/direct_passage, `code_irpp_is_2011`/direct_passage, `nc_01_norme_generale`/direct_passage
- Current sources: `nc_05_immobilisations_corporelles`/direct_passage, `ias_16_immobilisations_corporelles`/direct_passage, `code_irpp_is_2025`/direct_passage, `nc_01_norme_generale`/direct_passage
