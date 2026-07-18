# Priority A Gap Table - Before Batch 1

| Case | Workflow | Current sources | Why failed expert_pass | Failure type | Proposed fix | Generalizable? |
|---|---|---|---|---|---|---|
| tax_dividendes_2026 | `company_law_governance_case` | code_irpp_is_2025 p.85 (direct_passage); loi_finances_2026 p.1 (framework_source); procedures_fiscales_2026 p.1 (framework_source); code_societes_commerciales_2022 p.1 (unclassified); code_irpp_is_2011 p.1 (unclassified) | Dividend answer must explicitly cover withholding, declaration/reversement, certificate/proof, and beneficiary profile. | weak routing / weak retrieval | Route dividend + withholding questions to shareholder_split_tax_analysis, not company_law_governance_case; require retenue/declaration/certificate phrases. | generalizable |
| acct_goodwill_amortissement | `llm_provider` | ifrs_3_regroupements_entreprises p.5 (unclassified); ifrs_3_regroupements_entreprises p.8 (unclassified); nc_38_regroupements_entreprises p.10 (unclassified); nc_38_regroupements_entreprises p.9 (unclassified) | Directly tagged support from IFRS 3/NC 38 on goodwill treatment and impairment test. | weak source-support formatting / missing article / weak retrieval | Add source precision rules for IFRS 3 and NC 38 goodwill terms; do not accept unclassified sources for goodwill conclusions. | generalizable |
| level2_dividendes_associe_resident_prudent | `shareholder_split_tax_analysis` | code_irpp_is_2025 p.85 (direct_passage); loi_finances_2026 p.5 (framework_source); procedures_fiscales_2026 p.1 (framework_source) | Single resident shareholder analysis should apply facts directly instead of a generic beneficiary-by-beneficiary template. | weak answer generation / weak answer generation | Use the current IRPP/IS direct passage plus finance-law framework to produce a fact-specific dividend checklist; avoid generic multi-beneficiary wording for one beneficiary. | generalizable |
| level2_tva_services_france_sources_tva | `tva_operational_case` | tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage); convention_fiscale_france_tunisie_texte_1973 p.8 (direct_passage); boi_france_tunisie_convention_fiscale_2012 p.4 (direct_passage) | Final answer must use retrieved TVA/treaty sources to conclude the checks for the exact B2B/B2C fact pattern. | weak answer generation / weak answer generation | Turn retrieved TVA/treaty passages into a fact-sensitive answer: client status, place of use, invoicing, justificatifs, missing facts. | generalizable |
| level2_fraude_apres_rapport_cac | `audit_cac_response_case` | audit_resume_gaida_normes_missions p.2 (direct_passage); audit_resume_acceptation_controle_qualite p.3 (direct_passage); code_societes_commerciales_2022 p.139 (framework_source); textes_profession_comptable_2018 p.1 (unclassified) | CAC response must state concrete obligations by timing: communication, governance, reassessment of opinion/report, documentation. | weak answer generation / weak answer generation | Create no new fastpath yet; strengthen audit_cac_response_case generation so timing changes before/after signature alter obligations. | generalizable |
| level2_amortissement_immobilisation_cloture | `accounting_closing_estimate_case` | nc_05_immobilisations_corporelles p.2 (direct_passage); ias_16_immobilisations_corporelles p.7 (direct_passage); nc_01_norme_generale p.7 (direct_passage); nc_14_eventualites_post_cloture p.1 (unclassified); nc_39_parties_liees p.1 (unclassified) | Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split. | weak answer generation / weak answer generation | Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction. | generalizable |
| level2_tva_services_client_francais_non_assujetti | `level3_multi_domain_case_analysis` | tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); code_irpp_is_2025 p.89 (direct_passage); loi_finances_2026 p.6 (direct_passage); convention_fiscale_france_tunisie p.4 (direct_passage) | Final answer must use retrieved TVA/treaty sources to conclude the checks for the exact B2B/B2C fact pattern. | weak answer generation / weak answer generation | Turn retrieved TVA/treaty passages into a fact-sensitive answer: client status, place of use, invoicing, justificatifs, missing facts. | generalizable |
| level2_dividendes_associe_non_resident | `shareholder_split_tax_analysis` | code_irpp_is_2025 p.85 (direct_passage); loi_finances_2026 p.5 (framework_source); procedures_fiscales_2026 p.1 (framework_source); convention_fiscale_applicable p.None (missing_source) | Country/treaty passage is missing; answer should reserve treaty rate and list residence certificate/treaty facts. | missing document / missing document | Keep missing_source reservation for treaty until residence country/treaty passage is known; ask for country and certificate of tax residence. | corpus-specific |
| level2_fraude_avant_signature_rapport_cac | `audit_cac_response_case` | audit_resume_gaida_normes_missions p.2 (direct_passage); audit_resume_acceptation_controle_qualite p.3 (direct_passage); code_societes_commerciales_2022 p.139 (framework_source); textes_profession_comptable_2018 p.1 (unclassified) | CAC response must state concrete obligations by timing: communication, governance, reassessment of opinion/report, documentation. | weak answer generation / weak answer generation | Create no new fastpath yet; strengthen audit_cac_response_case generation so timing changes before/after signature alter obligations. | generalizable |
| level2_amortissement_mise_en_service_novembre | `fixed_asset_component_depreciation_case` | nc_05_immobilisations_corporelles p.2 (direct_passage); ias_16_immobilisations_corporelles p.7 (direct_passage); code_irpp_is_2025 p.14 (direct_passage); nc_01_norme_generale p.7 (direct_passage) | Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split. | weak answer generation / weak answer generation | Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction. | generalizable |
| level2_user_amortissement_date_depart_15_septembre | `accounting_closing_estimate_case` | nc_05_immobilisations_corporelles p.2 (direct_passage); ias_16_immobilisations_corporelles p.7 (direct_passage); nc_01_norme_generale p.7 (direct_passage); nc_14_eventualites_post_cloture p.1 (unclassified); nc_39_parties_liees p.1 (unclassified) | Answer must mention ready-for-use/mise en service, depreciable base, useful life, method, accounting vs tax split. | weak answer generation / weak answer generation | Strengthen accounting_closing_estimate_case wording to always cover mise en service/ready-for-use, base, useful life and tax distinction. | generalizable |

## Current Answer Previews

### tax_dividendes_2026

## Reponse
Ce dossier releve de la famille cabinet suivante: Droit des societes: associes, dirigeants, comptes et distribution. Faits transmis: Une SARL tunisienne distribue des dividendes en 2026. Quelles retenues a la source faut il verifier avant paiement ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- identifier la forme sociale, les organes competents et les decisions requises
- separer validite societaire, impact comptable et consequences fiscales
- verifier conventions reglem

### acct_goodwill_amortissement

## Reponse
Non, en principe le goodwill ne fait pas l’objet d’un amortissement systématique lorsqu’il est comptabilisé selon les normes IFRS 3 : l’écart d’acquisition (goodwill) doit être soumis à un test de dépréciation au moins annuellement et, le cas échéant, réduit de la perte de valeur constatée (voir IFRS 3 Regroupements d’entreprises, page 8, paragraphe concernant la mesure du goodwill comme excédent de la contrepartie transférée sur la juste valeur des actifs nets acquis).

## Application pratique
- Reconstituer les faits, montants et periodes.
- Identifier le texte precis applicable.
- Verifier les seuils, exceptions et pieces justificatives.

## Points de vigilance
- Verifier la da

### level2_dividendes_associe_resident_prudent

## Reponse
Cette distribution doit etre analysee beneficiaire par beneficiaire. Faits transmis: Une SARL tunisienne distribue 250 000 TND de dividendes en 2026 a un associe resident. Quelles sont les consequences fiscales ? Citez les bases legales.. Le dossier ne peut pas recevoir une reponse globale, car les profils de beneficiaires ne portent pas le meme risque fiscal. Pour chacun, il faut verifier la retenue a la source, la declaration et le reversement, le certificat ou la preuve de retenue, et pour un non-resident la convention fiscale applicable au pays du client.

## Application pratique
- Personne physique residente: verifier dans le Code de l'IRPP et de l'IS le regime des revenus di

### level2_tva_services_france_sources_tva

## Reponse
Ce dossier releve de la famille cabinet suivante: TVA: territorialite, deduction, facturation et regularisation. Faits transmis: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- qualifier l'operation, le lieu d'utilisation et le statut du client
- separer champ d'application, territorialite, exonération, exigibilite et droit a deduction
- verifier les mentions de fa

### level2_fraude_apres_rapport_cac

## Reponse
Ce dossier releve de la famille cabinet suivante: Audit/CAC: risques, opinion, gouvernance et documentation. Faits transmis: Un commissaire aux comptes decouvre une fraude apres l emission de son rapport. Que doit il faire ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- qualifier le fait d'audit et sa date par rapport au rapport
- identifier les diligences complementaires, elements probants, communications a la gouvernance et documentation
- evaluer l'incidence sur les co

### level2_amortissement_immobilisation_cloture

## Reponse
Ce dossier releve de la famille cabinet suivante: Comptabilite: cut-off, estimations, actifs et cloture. Faits transmis: Comment analyser l amortissement d une immobilisation corporelle avant cloture ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- identifier l'exercice de rattachement et la nature comptable de l'operation
- distinguer comptabilisation, estimation, depreciation/provision, parties liees et information en notes
- separer impacts comptables et retraitements f

### level2_tva_services_client_francais_non_assujetti

## Reponse
Ce dossier doit etre traite comme une analyse fiscale transfrontaliere multi-issues, et non comme une simple question IRPP/IS. Les faits transmis doivent etre qualifies sans les remplacer par un cas standard: Une societe tunisienne fournit une prestation informatique a un client francais non assujetti a la TVA. Quel regime TVA faut il verifier ?. L'analyse doit separer au minimum la TVA tunisienne, la retenue a la source ou le risque d'imposition sur le paiement transfrontalier, la convention fiscale France-Tunisie, le risque d'etablissement stable, la facturation et les justificatifs.

## Application pratique
- TVA: verifier dans le Code de la taxe sur la valeur ajoutee si la pre

### level2_dividendes_associe_non_resident

## Reponse
Cette distribution doit etre analysee beneficiaire par beneficiaire. Faits transmis: Une SARL tunisienne distribue des dividendes en 2026 a un associe non resident. Quels points fiscaux faut il verifier ?. Le dossier ne peut pas recevoir une reponse globale, car les profils de beneficiaires ne portent pas le meme risque fiscal. Pour chacun, il faut verifier la retenue a la source, la declaration et le reversement, le certificat ou la preuve de retenue, et pour un non-resident la convention fiscale applicable au pays du client.

## Application pratique
- Personne physique residente: verifier dans le Code de l'IRPP et de l'IS le regime des revenus distribues, la retenue a la source 

### level2_fraude_avant_signature_rapport_cac

## Reponse
Ce dossier releve de la famille cabinet suivante: Audit/CAC: risques, opinion, gouvernance et documentation. Faits transmis: Un commissaire aux comptes decouvre une fraude avant la signature de son rapport. Que doit il faire ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- qualifier le fait d'audit et sa date par rapport au rapport
- identifier les diligences complementaires, elements probants, communications a la gouvernance et documentation
- evaluer l'incidence sur les 

### level2_amortissement_mise_en_service_novembre

## Reponse
Ce dossier doit etre traite comme une immobilisation corporelle avec mise en service progressive et composant significatif. Faits transmis: Une immobilisation corporelle a ete achetee en septembre mais mise en service en novembre. Comment raisonner l amortissement ?. La date d'achat ou de facture ne suffit pas a declencher l'amortissement si la machine n'est pas encore prete a etre utilisee. Il faut rapprocher acquisition, livraison, installation, tests et mise en production. Si la date de production ou de disponibilite correspond a l'utilisation prevue, c'est cette date qui doit etre retenue pour le depart d'amortissement.

## Application pratique
- Cout d'entree: rattacher au co

### level2_user_amortissement_date_depart_15_septembre

## Reponse
Ce dossier releve de la famille cabinet suivante: Comptabilite: cut-off, estimations, actifs et cloture. Faits transmis: Une immobilisation est achetee le 15 septembre. A partir de quelle date commence son amortissement ? Quels textes ou normes faut-il consulter ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- identifier l'exercice de rattachement et la nature comptable de l'operation
- distinguer comptabilisation, estimation, depreciation/provision, parties liees et infor