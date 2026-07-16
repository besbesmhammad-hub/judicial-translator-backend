from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "data" / "accounting_benchmark_level35.jsonl"

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
    docs: list[str] | None = None,
    direct_docs: list[str] | None = None,
    forbidden: list[str] | None = None,
    missing: list[str] | None = None,
) -> dict:
    return {
        "id": id,
        "question": question,
        "language": "francais",
        "expected_intent": intent,
        "expected_preferred_source": "legal_corpus",
        "expected_response_style": "practical_analysis",
        "expected_workflow": workflow,
        "expected_sections": SECTIONS,
        "expected_answer_contains": contains,
        "expected_selected_doc_ids": docs or [],
        "expected_direct_or_framework_doc_ids": direct_docs or docs or [],
        "expected_missing_info_contains": missing or [],
        "forbidden_answer_contains": FORBIDDEN + (forbidden or []),
    }


CASES: list[dict] = []

# 1. Cross-border service analysis.
cross_contains = ["TVA", "retenue a la source", "convention fiscale", "etablissement stable", "facturation", "justificatifs"]
CASES += [
    case(
        "level35_cross_border_original_france",
        "Une societe tunisienne de services informatiques facture 120 000 EUR a une societe francaise. Une partie du travail est realisee depuis la Tunisie, mais deux consultants tunisiens se deplacent en France pendant 20 jours pour l installation et la formation. Quels risques fiscaux et obligations faut il analyser avant facturation et paiement ?",
        "level3_multi_domain_case_analysis",
        "legal_basis",
        cross_contains + ["20 jours", "120 000 EUR"],
        docs=["tva_droit_consommation", "code_irpp_is_2011"],
        direct_docs=["tva_droit_consommation", "convention_fiscale_france_tunisie"],
    ),
    case(
        "level35_cross_border_italy_missing_treaty",
        "Une entreprise tunisienne de logiciel facture 75 000 EUR a un client italien. Les developpeurs travaillent a Tunis, mais un consultant passe 12 jours en Italie pour parametrage et formation. Que faut-il verifier avant d emettre la facture ?",
        "level3_multi_domain_case_analysis",
        "legal_basis",
        cross_contains + ["Italie", "12 jours"],
        docs=["tva_droit_consommation", "code_irpp_is_2011"],
        missing=["convention fiscale applicable"],
        forbidden=["France-Tunisie"],
    ),
    case(
        "level35_cross_border_germany_license_training",
        "Une societe tunisienne vend a une societe allemande une licence logicielle avec formation sur site pendant 8 jours en Allemagne. Le contrat ne separe pas licence, assistance technique et formation. Quels risques fiscaux faut-il decomposer ?",
        "level3_multi_domain_case_analysis",
        "legal_basis",
        cross_contains + ["licence", "formation", "ventilation"],
        docs=["tva_droit_consommation", "code_irpp_is_2011"],
        missing=["ventilation"],
        forbidden=["France-Tunisie"],
    ),
    case(
        "level35_cross_border_uae_no_invoice",
        "Une societe tunisienne recoit un paiement d un client aux Emirats arabes unis pour assistance informatique. Il existe un contrat, mais aucune facture definitive n est encore etablie. Comment raisonner TVA, retenue, facturation et justificatifs ?",
        "level3_multi_domain_case_analysis",
        "legal_basis",
        cross_contains + ["contrat", "facture"],
        docs=["tva_droit_consommation", "code_irpp_is_2011"],
        missing=["facture"],
    ),
    case(
        "level35_cross_border_algeria_no_contract",
        "Une prestation de support informatique est facturee a une societe algerienne. La facture existe, mais aucun contrat ne precise le lieu d execution, la duree de presence ni la nature exacte des services. Peut-on conclure le regime fiscal ?",
        "level3_multi_domain_case_analysis",
        "legal_basis",
        cross_contains + ["Algerie", "ne peut pas conclure"],
        docs=["tva_droit_consommation", "code_irpp_is_2011"],
        missing=["lieu d execution", "nature exacte"],
    ),
    case(
        "level35_cross_border_france_non_assujetti",
        "Une societe tunisienne fournit une prestation informatique a un client francais non assujetti a la TVA, sans deplacement en France. Quels points changent par rapport a un client B2B assujetti ?",
        "level3_multi_domain_case_analysis",
        "legal_basis",
        cross_contains + ["non assujetti"],
        docs=["tva_droit_consommation"],
        direct_docs=["tva_droit_consommation"],
    ),
]

# 2. Dividends/shareholder split.
div_contains = ["retenue a la source", "declaration", "certificat"]
CASES += [
    case(
        "level35_dividends_original_three_profiles",
        "Une SARL tunisienne distribue 300 000 TND de dividendes a une personne physique residente, 200 000 TND a une societe tunisienne et 100 000 TND a un associe francais non resident. Quelle analyse fiscale faut il faire avant paiement ?",
        "shareholder_split_tax_analysis",
        "tax_calculation",
        div_contains + ["300 000 TND", "200 000 TND", "100 000 TND", "convention fiscale"],
        docs=["code_irpp_is_2011", "loi_finances_2026"],
        direct_docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_distributed_profits_two_physical",
        "La societe decide de verser des benefices distribues a deux personnes physiques: l une residente en Tunisie, l autre non residente. Quels controles fiscaux faut-il faire avant paiement ?",
        "shareholder_split_tax_analysis",
        "tax_calculation",
        div_contains + ["personne physique", "non-resident", "convention fiscale"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_revenus_distribues_company_shareholder",
        "Une SA verse des revenus distribues uniquement a une societe tunisienne actionnaire. Faut-il raisonner de la meme maniere que pour une personne physique ?",
        "shareholder_split_tax_analysis",
        "tax_calculation",
        div_contains + ["societe tunisienne", "personne physique"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_dividends_nonresident_country_missing",
        "Une SARL doit payer des dividendes a un associe non resident, mais le dossier ne precise pas son pays de residence fiscale. Peut-on appliquer un taux conventionnel ?",
        "shareholder_split_tax_analysis",
        "tax_calculation",
        div_contains + ["non resident", "ne peut pas", "pays de residence"],
        docs=["code_irpp_is_2011"],
        missing=["pays de residence"],
    ),
    case(
        "level35_dividends_no_certificate_process",
        "Le gerant veut distribuer les dividendes rapidement sans certificat de retenue ni preuve de reversement. Quels risques doit signaler le cabinet ?",
        "shareholder_split_tax_analysis",
        "tax_calculation",
        div_contains + ["preuve", "reversement"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_benefices_distribues_old_reserves",
        "La distribution porte en partie sur des reserves anciennes et en partie sur le resultat 2025. Quelles informations faut-il obtenir avant de qualifier les benefices distribues ?",
        "shareholder_split_tax_analysis",
        "tax_calculation",
        div_contains + ["reserves", "informations"],
        docs=["code_irpp_is_2011"],
        missing=["origine des reserves"],
    ),
]

# 3. Revenue cutoff / maintenance.
maintenance_contains = ["periode de service", "produit constate d'avance", "TVA", "facturation"]
CASES += [
    case(
        "level35_maintenance_original",
        "Une societe facture et encaisse en decembre 2025 un contrat annuel de maintenance couvrant janvier a decembre 2026. Comment traiter le revenu, la fiscalite et la TVA avant cloture ?",
        "revenue_cutoff_tva_case",
        "accounting_treatment",
        maintenance_contains + ["2025", "2026"],
        docs=["nc_03_revenus", "tva_droit_consommation"],
    ),
    case(
        "level35_subscription_bank_transfer",
        "Un abonnement annuel est paye par virement bancaire le 20 decembre 2025 pour une assistance couvrant toute l annee 2026. Quelle analyse de cut-off faut-il faire ?",
        "revenue_cutoff_tva_case",
        "accounting_treatment",
        maintenance_contains + ["virement", "2026"],
        docs=["nc_03_revenus"],
    ),
    case(
        "level35_maintenance_invoice_no_payment",
        "Une facture de maintenance est emise le 31 decembre 2025 pour un service a rendre en 2026, mais elle n est pas encore payee. Est-ce un produit de 2025 ?",
        "revenue_cutoff_tva_case",
        "accounting_treatment",
        maintenance_contains + ["non payee", "2025"],
        docs=["nc_03_revenus"],
    ),
    case(
        "level35_maintenance_contract_missing_period",
        "Le client a une facture de maintenance payee d avance, mais la periode couverte par le contrat n est pas indiquee. Peut-on comptabiliser tout le produit ?",
        "revenue_cutoff_tva_case",
        "accounting_treatment",
        maintenance_contains + ["ne peut pas", "periode"],
        docs=["nc_03_revenus"],
        missing=["periode couverte"],
    ),
    case(
        "level35_service_partly_done_before_closing",
        "Une prestation annuelle commence en octobre 2025 et se termine en septembre 2026. Le prix est encaisse d avance. Comment ventiler le revenu et la TVA ?",
        "revenue_cutoff_tva_case",
        "accounting_treatment",
        maintenance_contains + ["ventiler", "2025", "2026"],
        docs=["nc_03_revenus", "tva_droit_consommation"],
    ),
    case(
        "level35_maintenance_no_invoice_contract_only",
        "Le contrat annuel existe et le client a paye, mais aucune facture n a encore ete emise. Quels risques de cut-off, TVA et facturation faut-il signaler ?",
        "revenue_cutoff_tva_case",
        "accounting_treatment",
        maintenance_contains + ["contrat", "facture"],
        docs=["nc_03_revenus", "tva_droit_consommation"],
    ),
]

# 4. Receivable impairment/subsequent event.
rec_contains = ["provision", "deductibilite", "justificatifs"]
CASES += [
    case(
        "level35_receivable_original",
        "Une societe a une creance douteuse de 180 000 TND en retard depuis 14 mois, avec plusieurs relances documentees. Apres la cloture, elle recupere 30 000 TND. Comment analyser la provision comptable, l evenement posterieur et la deductibilite fiscale ?",
        "receivable_impairment_subsequent_event",
        "tax_calculation",
        rec_contains + ["180 000 TND", "30 000 TND", "exposition restante"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_unpaid_client_no_recovery",
        "Un client doit 90 000 TND depuis 11 mois. Plusieurs relances existent, mais aucun encaissement n est intervenu apres la cloture. Quelle provision peut etre envisagee ?",
        "receivable_impairment_subsequent_event",
        "tax_calculation",
        rec_contains + ["90 000 TND", "aucun encaissement"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_receivable_without_reminders",
        "Une facture client de 60 000 TND est impayee depuis 8 mois, mais aucune relance ni action de recouvrement n est documentee. Peut-on deduire une provision ?",
        "receivable_impairment_subsequent_event",
        "tax_calculation",
        rec_contains + ["ne peut pas", "relance", "recouvrement"],
        docs=["code_irpp_is_2011"],
        missing=["relance", "action de recouvrement"],
    ),
    case(
        "level35_receivable_recovered_full_after_closing",
        "Une creance client de 40 000 TND etait en retard a la cloture, puis elle est totalement encaissee en janvier. Faut-il garder une depreciation ?",
        "receivable_impairment_subsequent_event",
        "tax_calculation",
        rec_contains + ["encaissee", "reprise", "evenement posterieur"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_receivable_client_litigation",
        "Un client conteste une facture de 130 000 TND et refuse de payer. Un avocat a ete saisi apres cloture. Comment traiter la depreciation et les pieces fiscales ?",
        "receivable_impairment_subsequent_event",
        "tax_calculation",
        rec_contains + ["litige", "avocat", "pieces"],
        docs=["code_irpp_is_2011"],
    ),
    case(
        "level35_receivable_missing_amount",
        "Le comptable dit qu un client est en retard depuis longtemps mais ne fournit ni solde exact ni balance agee. Peut-on conclure sur la provision deductible ?",
        "receivable_impairment_subsequent_event",
        "tax_calculation",
        rec_contains + ["ne peut pas", "solde", "balance agee"],
        docs=["code_irpp_is_2011"],
        missing=["solde exact", "balance agee"],
    ),
]

# 5. Going concern.
gc_contains = ["continuite d'exploitation", "audit", "opinion"]
CASES += [
    case(
        "level35_going_concern_original",
        "Une societe presente des capitaux propres negatifs, des retards importants de paiement fournisseurs et un financement bancaire non confirme. Comment analyser la continuite d exploitation et l impact sur le rapport d audit ?",
        "going_concern_case_analysis",
        "audit",
        gc_contains + ["capitaux propres negatifs", "financement bancaire"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
    case(
        "level35_going_concern_risque_cessation",
        "Le client risque une cessation d activite: tresorerie insuffisante, fournisseurs impayes et pertes repetees. Que doit faire le cabinet avant de signer ?",
        "going_concern_case_analysis",
        "audit",
        gc_contains + ["cessation d activite", "signer"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
    case(
        "level35_going_concern_management_refuses_disclosure",
        "La direction refuse d inserer une note sur la continuite d exploitation alors que le financement bancaire n est pas obtenu. Quel impact sur le rapport ?",
        "going_concern_case_analysis",
        "audit",
        gc_contains + ["refuse", "note", "rapport"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
    case(
        "level35_going_concern_government_support_unconfirmed",
        "Une entreprise depend d une subvention ou d un soutien bancaire non confirme pour continuer son exploitation. Quelles preuves demander ?",
        "going_concern_case_analysis",
        "audit",
        gc_contains + ["preuves", "non confirme"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
    case(
        "level35_going_concern_no_cashflow_forecast",
        "Le dossier contient des pertes et des retards de paiement mais aucun budget de tresorerie previsionnel. Peut-on conclure sur le going concern ?",
        "going_concern_case_analysis",
        "audit",
        gc_contains + ["ne peut pas", "budget de tresorerie"],
        docs=["audit_resume_gaida_normes_missions"],
        missing=["budget de tresorerie"],
    ),
    case(
        "level35_going_concern_positive_equity_cash_crisis",
        "Les capitaux propres restent positifs, mais la societe ne peut plus payer ses dettes courantes. Faut-il quand meme analyser la continuite d exploitation ?",
        "going_concern_case_analysis",
        "audit",
        gc_contains + ["dettes courantes", "tresorerie"],
        docs=["audit_resume_gaida_normes_missions"],
    ),
]

# 6. Related-party property.
rp_contains = ["valeur de marche", "partie liee", "convention reglementee", "redressement"]
CASES += [
    case(
        "level35_related_party_original",
        "Une societe vend un immeuble a son gerant a un prix inferieur a la valeur de marche. Quels risques comptables, fiscaux, juridiques et d audit faut il analyser ?",
        "related_party_transaction_case",
        "legal_basis",
        rp_contains + ["gerant"],
        docs=["nc_39_parties_liees", "code_societes_commerciales_2022"],
    ),
    case(
        "level35_related_party_shareholder_vehicle",
        "Une societe cede un vehicule a un actionnaire a un prix tres bas. Quels controles faut-il faire avant validation comptable et fiscale ?",
        "related_party_transaction_case",
        "legal_basis",
        rp_contains + ["actionnaire", "prix"],
        docs=["nc_39_parties_liees", "code_societes_commerciales_2022"],
    ),
    case(
        "level35_related_party_no_valuation",
        "La societe vend un terrain a une partie liee, mais aucune expertise independante de valeur n existe. Peut-on conclure que le prix est normal ?",
        "related_party_transaction_case",
        "legal_basis",
        rp_contains + ["ne peut pas", "expertise"],
        docs=["nc_39_parties_liees", "code_societes_commerciales_2022"],
        missing=["expertise independante"],
    ),
    case(
        "level35_related_party_manager_rent",
        "Le gerant loue un local personnel a la societe a un loyer superieur au marche. Quels risques de partie liee et fiscaux analyser ?",
        "related_party_transaction_case",
        "legal_basis",
        rp_contains + ["loyer", "marche"],
        docs=["nc_39_parties_liees", "code_societes_commerciales_2022"],
    ),
    case(
        "level35_related_party_sale_without_approval",
        "Une convention avec un associe a deja ete executee sans autorisation ni approbation. Quelles consequences signaler ?",
        "related_party_transaction_case",
        "legal_basis",
        rp_contains + ["autorisation", "approbation"],
        docs=["code_societes_commerciales_2022"],
    ),
    case(
        "level35_related_party_market_price_ok",
        "La vente a une partie liee semble realisee au prix du marche avec expertise. Quels controles restent necessaires ?",
        "related_party_transaction_case",
        "legal_basis",
        rp_contains + ["expertise", "documentation"],
        docs=["nc_39_parties_liees", "code_societes_commerciales_2022"],
    ),
]

# 7. Expense evidence / consulting.
exp_contains = ["realite du service", "interet de l'entreprise", "justificatifs"]
CASES += [
    case(
        "level35_consulting_original_cash",
        "Une societe comptabilise une charge de consulting avec seulement une facture et un paiement en especes. Peut on confirmer la deductibilite fiscale ?",
        "expense_deductibility_evidence_case",
        "tax_calculation",
        exp_contains + ["paiement en especes", "ne peut pas etre confirmee"],
        docs=["code_irpp_is_2011", "loi_comptable"],
        forbidden=["IAS 7"],
    ),
    case(
        "level35_honoraires_invoice_no_contract",
        "Une facture d honoraires de conseil de 80 000 TND existe, mais aucun contrat ni rapport de mission n est fourni. Peut-on deduire la charge ?",
        "expense_deductibility_evidence_case",
        "tax_calculation",
        exp_contains + ["contrat", "rapport de mission", "ne peut pas"],
        docs=["code_irpp_is_2011", "loi_comptable"],
    ),
    case(
        "level35_external_service_contract_no_invoice",
        "Le contrat de prestation externe existe et le paiement bancaire est trace, mais la facture manque. Quelle position prendre ?",
        "expense_deductibility_evidence_case",
        "tax_calculation",
        exp_contains + ["facture", "paiement bancaire"],
        docs=["code_irpp_is_2011", "loi_comptable"],
        missing=["facture"],
    ),
    case(
        "level35_consulting_bank_transfer_full_docs",
        "Une prestation de conseil est appuyee par contrat, livrables, facture reguliere et virement bancaire. Quels controles restent a effectuer avant deduction ?",
        "expense_deductibility_evidence_case",
        "tax_calculation",
        exp_contains + ["contrat", "livrables", "virement bancaire"],
        docs=["code_irpp_is_2011", "loi_comptable"],
    ),
    case(
        "level35_cash_payment_no_service_evidence",
        "Une charge de prestation externe est payee en liquide et aucun livrable ne prouve le service. Comment repondre au client ?",
        "expense_deductibility_evidence_case",
        "tax_calculation",
        exp_contains + ["liquide", "livrable", "ne peut pas"],
        docs=["code_irpp_is_2011", "loi_comptable"],
    ),
    case(
        "level35_related_consultant_fee",
        "La facture de conseil provient d une societe liee au dirigeant. Elle est payee par virement mais le prix semble eleve. Quels risques analyser ?",
        "expense_deductibility_evidence_case",
        "tax_calculation",
        exp_contains + ["partie liee", "prix", "justificatifs"],
        docs=["code_irpp_is_2011", "loi_comptable"],
    ),
]

# 8. Accounting vs tax provision bridge.
bridge_contains = ["traitement comptable", "traitement fiscal", "reintegration extra-comptable", "impot differe"]
CASES += [
    case(
        "level35_bridge_original",
        "Une provision est comptabilisee selon les normes comptables mais elle n est pas fiscalement deductible. Comment traiter l ecart entre comptabilite et fiscalite ?",
        "accounting_tax_bridge_case",
        "tax_calculation",
        bridge_contains,
        docs=["code_irpp_is_2011", "ias_37_provisions_passifs_actifs_eventuels"],
    ),
    case(
        "level35_bridge_litigation_provision",
        "Une provision pour litige est justifiee comptablement mais les conditions fiscales de deduction ne sont pas reunies. Quelles ecritures et retraitements fiscaux ?",
        "accounting_tax_bridge_case",
        "tax_calculation",
        bridge_contains + ["litige"],
        docs=["code_irpp_is_2011", "ias_37_provisions_passifs_actifs_eventuels"],
    ),
    case(
        "level35_bridge_warranty_estimate",
        "Une garantie client donne lieu a une provision estimee fiable en comptabilite, mais le fiscaliste doute de sa deductibilite. Comment documenter l ecart ?",
        "accounting_tax_bridge_case",
        "tax_calculation",
        bridge_contains + ["garantie"],
        docs=["code_irpp_is_2011", "ias_37_provisions_passifs_actifs_eventuels"],
    ),
    case(
        "level35_bridge_missing_tax_basis",
        "La direction affirme qu une provision est deductible mais ne fournit aucune base fiscale. Peut-on accepter le traitement ?",
        "accounting_tax_bridge_case",
        "tax_calculation",
        bridge_contains + ["ne peut pas", "base fiscale"],
        docs=["code_irpp_is_2011", "ias_37_provisions_passifs_actifs_eventuels"],
        missing=["base fiscale"],
    ),
    case(
        "level35_bridge_temporary_difference",
        "Une charge est comptabilisee cette annee mais deductible fiscalement seulement plus tard. Comment presenter la difference temporaire ?",
        "accounting_tax_bridge_case",
        "tax_calculation",
        bridge_contains + ["difference temporaire"],
        docs=["code_irpp_is_2011", "ias_12_impots_resultat"],
    ),
    case(
        "level35_bridge_definitive_reintegration",
        "Une provision comptable ne sera jamais admise fiscalement. Faut-il parler d impot differe ou de reintegration definitive ?",
        "accounting_tax_bridge_case",
        "tax_calculation",
        bridge_contains + ["definitive"],
        docs=["code_irpp_is_2011", "ias_12_impots_resultat"],
    ),
]

# 9. Fixed asset component depreciation.
asset_contains = ["mise en service", "pret", "composant", "traitement comptable", "fiscalite"]
CASES += [
    case(
        "level35_asset_original",
        "Une societe achete une machine le 15 septembre, la recoit le 20 septembre, l installe le 10 octobre, effectue des tests jusqu au 25 octobre et commence la production le 1er novembre. Une piece majeure doit etre remplacee tous les 3 ans. Comment analyser la date de debut d amortissement, les composants, le traitement comptable et le traitement fiscal ?",
        "fixed_asset_component_depreciation_case",
        "accounting_treatment",
        asset_contains + ["1er novembre", "3 ans"],
        docs=["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles"],
        forbidden=["Droits et taxes non incorpores", "IAS 7"],
    ),
    case(
        "level35_asset_ready_before_production",
        "Un equipement est pret a fonctionner le 25 octobre mais la production commerciale ne demarre que le 1er novembre. A quelle date commencer l amortissement ?",
        "fixed_asset_component_depreciation_case",
        "accounting_treatment",
        asset_contains + ["25 octobre", "1er novembre"],
        docs=["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles"],
    ),
    case(
        "level35_asset_component_engine",
        "Une ligne de production contient un moteur significatif remplace tous les 4 ans alors que le reste dure 10 ans. Comment appliquer l approche par composants ?",
        "fixed_asset_component_depreciation_case",
        "accounting_treatment",
        asset_contains + ["4 ans", "10 ans"],
        docs=["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles"],
    ),
    case(
        "level35_asset_no_commissioning_report",
        "La machine est livree et installee, mais aucun PV de mise en service ni rapport de tests n est disponible. Peut-on fixer le debut d amortissement ?",
        "fixed_asset_component_depreciation_case",
        "accounting_treatment",
        asset_contains + ["ne peut pas", "PV"],
        docs=["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles"],
        missing=["PV de mise en service"],
    ),
    case(
        "level35_asset_delivery_not_installed",
        "Une immobilisation est livree le 20 decembre mais l installation aura lieu en janvier. Faut-il amortir des decembre ?",
        "fixed_asset_component_depreciation_case",
        "accounting_treatment",
        asset_contains + ["decembre", "janvier"],
        docs=["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles"],
    ),
    case(
        "level35_asset_tax_rate_vs_useful_life",
        "Le fiscaliste propose d utiliser directement le taux fiscal comme duree comptable pour une machine complexe. Est-ce suffisant ?",
        "fixed_asset_component_depreciation_case",
        "accounting_treatment",
        asset_contains + ["taux fiscal", "duree comptable"],
        docs=["nc_05_immobilisations_corporelles", "ias_16_immobilisations_corporelles"],
    ),
]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for item in CASES:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {len(CASES)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
