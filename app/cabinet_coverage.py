from __future__ import annotations

import unicodedata
from dataclasses import dataclass


def _key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().replace("-", " ").split())


def _contains(haystack: str, term: str) -> bool:
    needle = _key(term)
    if not needle:
        return False
    if len(needle) <= 3 and needle.isalpha():
        return f" {needle} " in f" {haystack} "
    return needle in haystack


@dataclass(frozen=True)
class CabinetWorkflow:
    id: str
    family: str
    title: str
    intent: str
    legal_domain: str
    trigger_any: tuple[str, ...]
    trigger_all_any: tuple[tuple[str, ...], ...]
    source_doc_ids: tuple[str, ...]
    issue_split: tuple[str, ...]
    missing_facts: tuple[str, ...]
    source_terms: tuple[tuple[str, tuple[str, ...], int], ...]


CABINET_WORKFLOWS: tuple[CabinetWorkflow, ...] = (
    CabinetWorkflow(
        id="direct_tax_deductibility_adjustment_case",
        family="fiscalite_directe",
        title="Fiscalite directe: deductibilite, reintegrations et avantages",
        intent="tax_calculation",
        legal_domain="fiscalite",
        trigger_any=("is", "irpp", "retenue a la source", "charge deductible", "charges deductibles", "reintegr", "avantage occulte", "provision", "amortissement fiscal", "benefice imposable"),
        trigger_all_any=(("charge", "provision", "amortissement", "avantage", "reintegr", "retenue", "dividende"), ("deduire", "deductible", "fiscal", "impot", "is", "irpp")),
        source_doc_ids=("code_irpp_is_2011", "loi_finances_2026", "procedures_fiscales_2026", "loi_comptable"),
        issue_split=(
            "qualifier le contribuable, le beneficiaire et l'exercice concerne",
            "distinguer traitement comptable, deductibilite fiscale et reintegration extra-comptable",
            "verifier retenue a la source, dividendes, avantages occultes, benefice imposable ou limitation fiscale selon la nature du flux",
            "identifier les pieces probantes et les declarations ou certificats a produire",
        ),
        missing_facts=("statut du contribuable", "exercice", "montant", "beneficiaire resident ou non-resident", "contrat/facture", "preuve de paiement", "article fiscal direct"),
        source_terms=(
            ("code_irpp_is_2011", ("benefice imposable", "charges", "retenue a la source", "provision", "amortissement"), 2),
            ("loi_finances_2026", ("loi de finances", "2026", "retenue", "impot"), 2),
            ("procedures_fiscales_2026", ("declaration", "controle", "justificatifs", "certificat"), 2),
            ("loi_comptable", ("pieces justificatives", "comptabilite", "enregistrement", "documents"), 2),
        ),
    ),
    CabinetWorkflow(
        id="tva_operational_case",
        family="tva",
        title="TVA: territorialite, deduction, facturation et regularisation",
        intent="legal_basis",
        legal_domain="fiscalite",
        trigger_any=("tva", "taxe sur la valeur ajoutee", "deduction tva", "tva deductible", "tva collectee", "exigibilite", "exoneration", "facturation", "regularisation tva", "exportation de services"),
        trigger_all_any=(("tva", "taxe sur la valeur ajoutee", "facture", "exoneration", "deduction"), ("territorialite", "export", "deductible", "exigible", "regularisation", "justificatif")),
        source_doc_ids=("tva_droit_consommation", "procedures_fiscales_2026", "loi_finances_2026", "code_irpp_is_2011"),
        issue_split=(
            "qualifier l'operation, le lieu d'utilisation et le statut du client",
            "separer champ d'application, territorialite, exonération, exigibilite et droit a deduction",
            "verifier les mentions de facture et les justificatifs du regime TVA applique",
            "traiter les regularisations, exportation de services ou rejets de deduction sans inventer de taux",
        ),
        missing_facts=("statut TVA du client", "lieu d'execution/utilisation", "facture", "contrat", "nature exacte du service ou bien", "preuve d'exportation", "article TVA direct"),
        source_terms=(
            ("tva_droit_consommation", ("tva", "taxe sur la valeur ajoutee", "facture", "deduction", "exoneration"), 2),
            ("procedures_fiscales_2026", ("facture", "controle", "declaration", "justificatifs"), 2),
            ("loi_finances_2026", ("tva", "loi de finances", "2026"), 2),
        ),
    ),
    CabinetWorkflow(
        id="accounting_closing_estimate_case",
        family="comptabilite",
        title="Comptabilite: cut-off, estimations, actifs et cloture",
        intent="accounting_treatment",
        legal_domain="comptabilite",
        trigger_any=("cut off", "cut-off", "cloture", "revenu", "charge", "stock", "immobilisation", "creance douteuse", "evenement posterieur", "continuite d exploitation", "parties liees"),
        trigger_all_any=(("comptabiliser", "ecriture", "cloture", "provision", "revenu", "charge", "stock", "immobilisation"), ("exercice", "estimation", "cut", "evenement", "amortissement", "depreciation")),
        source_doc_ids=("nc_01_norme_generale", "nc_14_eventualites_post_cloture", "nc_39_parties_liees", "nc_03_revenus", "nc_04_stocks", "nc_05_immobilisations_corporelles"),
        issue_split=(
            "identifier l'exercice de rattachement et la nature comptable de l'operation",
            "distinguer comptabilisation, estimation, depreciation/provision, parties liees et information en notes",
            "separer impacts comptables et retraitements fiscaux eventuels",
            "documenter jugement, calcul, documentation et justificatifs, pieces de cloture et evenement posterieur",
        ),
        missing_facts=("date de cloture", "date de facture", "date de service", "montant", "piece justificative", "mode de calcul", "referentiel applique"),
        source_terms=(
            ("nc_01_norme_generale", ("etats financiers", "exercice", "charges", "produits", "continuite"), 2),
            ("nc_14_eventualites_post_cloture", ("evenement", "cloture", "provision"), 2),
            ("nc_39_parties_liees", ("parties liees", "transactions", "information"), 2),
            ("nc_03_revenus", ("revenu", "prestation de services", "exercice"), 2),
            ("nc_04_stocks", ("stocks", "marchandises", "cout", "inventaire"), 2),
            ("nc_05_immobilisations_corporelles", ("immobilisation", "amortissement", "duree d'utilisation"), 2),
        ),
    ),
    CabinetWorkflow(
        id="audit_cac_response_case",
        family="audit_cac",
        title="Audit/CAC: risques, opinion, gouvernance et documentation",
        intent="legal_basis",
        legal_domain="audit",
        trigger_any=("commissaire aux comptes", "cac", "audit", "fraude", "opinion", "refus de correction", "limitation de travaux", "gouvernance", "evenements posterieurs", "rapport"),
        trigger_all_any=(("audit", "cac", "commissaire aux comptes", "auditeur"), ("fraude", "opinion", "rapport", "direction", "gouvernance", "limitation", "correction")),
        source_doc_ids=("audit_resume_gaida_normes_missions", "audit_resume_acceptation_controle_qualite", "code_societes_commerciales_2022", "textes_profession_comptable_2018"),
        issue_split=(
            "qualifier le fait d'audit et sa date par rapport au rapport",
            "identifier les diligences complementaires, elements probants, communications a la gouvernance et documentation",
            "evaluer l'incidence sur les comptes, les evenements posterieurs, les disclosures et l'opinion",
            "distinguer fraude, anomalie, limitation et refus de correction",
        ),
        missing_facts=("date de decouverte", "montant/significativite", "reponse de la direction", "date du rapport", "preuves disponibles", "communication gouvernance"),
        source_terms=(
            ("audit_resume_gaida_normes_missions", ("audit", "opinion", "rapport", "elements probants", "fraude"), 2),
            ("audit_resume_acceptation_controle_qualite", ("documentation", "risque", "planification", "rapport"), 2),
            ("code_societes_commerciales_2022", ("commissaire aux comptes", "rapport", "societe"), 2),
        ),
    ),
    CabinetWorkflow(
        id="company_law_governance_case",
        family="droit_societes",
        title="Droit des societes: associes, dirigeants, comptes et distribution",
        intent="legal_basis",
        legal_domain="droit_affaires",
        trigger_any=("associe", "dirigeant", "gerant", "capital social", "pertes", "approbation des comptes", "distribution de benefices", "convention reglementee", "assemblee", "sarl", "sa"),
        trigger_all_any=(("societe", "sarl", "sa", "associe", "dirigeant", "gerant", "assemblee"), ("distribution", "pertes", "capital", "approbation", "convention", "comptes")),
        source_doc_ids=("code_societes_commerciales_2022", "code_irpp_is_2011", "code_commerce_2014", "code_obligations_contrats_2015", "textes_profession_comptable_2018"),
        issue_split=(
            "identifier la forme sociale, les organes competents et les decisions requises",
            "separer validite societaire, impact comptable et consequences fiscales",
            "verifier conventions reglementees, pertes, capital, approbation des comptes et distribution",
            "documenter PV, rapports, convocations et pieces justificatives",
        ),
        missing_facts=("forme sociale", "statuts", "PV/assemblee", "qualite du dirigeant ou associe", "montant", "comptes approuves", "rapport CAC"),
        source_terms=(
            ("code_societes_commerciales_2022", ("associes", "gerant", "assemblee", "capital", "benefices"), 2),
            ("code_irpp_is_2011", ("benefices", "revenus distribues", "benefice imposable"), 2),
            ("code_commerce_2014", ("societe", "commerce", "registre"), 2),
            ("code_obligations_contrats_2015", ("contrat", "obligation", "responsabilite"), 2),
        ),
    ),
    CabinetWorkflow(
        id="payroll_social_case",
        family="paie_social",
        title="Paie/social: CNSS, retenues salariales et declarations",
        intent="legal_basis",
        legal_domain="general",
        trigger_any=("cnss", "paie", "salaire", "retenue salariale", "charges sociales", "declaration employeur", "avantage en nature", "cotisation sociale"),
        trigger_all_any=(("salaire", "paie", "cnss", "employeur", "avantage en nature"), ("declaration", "retenue", "cotisation", "charge sociale", "social")),
        source_doc_ids=(
            "cnss_f1_demande_affiliation_employeur",
            "cnss_n43_liste_nominative_personnel",
            "code_irpp_is_2011",
            "procedures_fiscales_2026",
            "cnss_p326_prise_en_charge_indemnites_licenciement",
            "cnss_p212_affiliation_travailleurs_non_salaries",
            "cnss_p304_affiliation_travailleurs_tunisiens_etranger",
            "cnss_n66_declaration_accident_non_professionnel",
            "cnss_p57_demande_indemnite_deces",
            "cnss_p58_constat_medical_de_deces",
            "cnss_a144bis_pension_capital_deces_survivants",
            "cnss_i16_declaration_trimestrielle_salaires",
            "cnss_i27_declaration_trimestrielle_salaries_agricoles",
            "cnss_i28_etat_recapitulatif_salaires_agricoles",
            "cnss_i3_etat_recapitulatif_salaires_declares",
            "cnss_c084_majoration_salaire_unique",
            "cnss_n101_declaration_enfant_handicape",
            "cnss_n44_affiliation_independants",
            "cnss_n40_affiliation_employes_maison",
        ),
        issue_split=(
            "identifier le salarie, l'employeur, la periode et la nature de l'avantage ou retenue",
            "separer paie, IRPP salarial, cotisations sociales et declarations",
            "verifier les formulaires et justificatifs CNSS pertinents sans inventer de taux",
            "documenter bulletin, contrat, declaration employeur et justificatifs",
        ),
        missing_facts=("bulletin de paie", "contrat", "periode", "montant brut/net", "statut CNSS", "taux ou regime CNSS exact si non cite"),
        source_terms=(
            ("cnss_f1_demande_affiliation_employeur", ("cnss", "demande d affiliation", "employeur", "representant legal", "entreprise"), 2),
            ("cnss_n43_liste_nominative_personnel", ("liste nominative", "personnel", "salaire mensuel", "date de recrutement", "employeur"), 2),
            ("code_irpp_is_2011", ("traitements", "salaires", "retenue a la source", "avantages"), 2),
            ("procedures_fiscales_2026", ("declaration", "retenue", "controle", "employeur"), 2),
            ("cnss_p326_prise_en_charge_indemnites_licenciement", ("indemnites de licenciement", "droits legaux", "raisons economiques", "technologiques", "fermeture"), 2),
            ("cnss_p212_affiliation_travailleurs_non_salaries", ("travailleurs non salaries", "secteurs agricole", "secteur non agricole", "affiliation"), 2),
            ("cnss_p304_affiliation_travailleurs_tunisiens_etranger", ("travailleurs tunisiens a l etranger", "tunisiens a l etranger", "affiliation"), 2),
            ("cnss_n66_declaration_accident_non_professionnel", ("accident non professionnel", "declaration d accident", "temoins", "circonstances"), 2),
            ("cnss_p57_demande_indemnite_deces", ("indemnite de deces", "acte de deces", "assure social", "conjoint"), 2),
            ("cnss_p58_constat_medical_de_deces", ("constat medical de deces", "cause de deces", "medecin traitant", "accident"), 2),
            ("cnss_a144bis_pension_capital_deces_survivants", ("pension", "capital deces", "survivants", "conjoint survivant", "orphelins"), 2),
            ("cnss_i16_declaration_trimestrielle_salaires", ("declaration trimestrielle", "remuneration mensuelle", "salaires declares", "trimestre"), 2),
            ("cnss_i27_declaration_trimestrielle_salaries_agricoles", ("declaration trimestrielle", "secteur agricole", "salaries", "qualification professionnelle"), 2),
            ("cnss_i28_etat_recapitulatif_salaires_agricoles", ("etat recapitulatif", "salaires declares", "secteur agricole", "cotisations"), 2),
            ("cnss_i3_etat_recapitulatif_salaires_declares", ("etat recapitulatif", "salaires declares", "cotisations", "penalites de retard"), 2),
            ("cnss_c084_majoration_salaire_unique", ("majoration pour salaire unique", "salaire unique", "conjoint", "engagement"), 2),
            ("cnss_n101_declaration_enfant_handicape", ("enfant handicape", "infirmit", "maladie incurable", "declaration sur l honneur"), 2),
            ("cnss_n44_affiliation_independants", ("travailleur pour son propre compte", "secteur agricole", "secteur non agricole", "affiliation"), 2),
            ("cnss_n40_affiliation_employes_maison", ("employes de maison", "aide de menage", "chauffeur", "jardinier", "affiliation"), 2),
        ),
    ),
    CabinetWorkflow(
        id="tax_procedure_compliance_case",
        family="procedure_fiscale",
        title="Procedure fiscale: declarations, controle, penalites et recours",
        intent="legal_basis",
        legal_domain="fiscalite",
        trigger_any=("declaration fiscale", "delai", "controle fiscal", "penalite", "recours", "redressement", "certificat", "justificatifs", "notification", "contentieux fiscal"),
        trigger_all_any=(("declaration", "controle", "redressement", "penalite", "recours", "certificat"), ("delai", "fiscal", "justificatif", "notification", "contentieux", "administration")),
        source_doc_ids=("procedures_fiscales_2026", "code_irpp_is_2011", "tva_droit_consommation", "loi_finances_2026"),
        issue_split=(
            "qualifier l'obligation declarative, le controle ou le recours demande",
            "identifier delais, documents, notifications, penalites et voies de contestation",
            "separer procedure fiscale, assiette de l'impot et preuve documentaire",
            "refuser d'inventer un delai ou une penalite sans article direct",
        ),
        missing_facts=("type de declaration", "date de notification", "periode controlee", "impot concerne", "montant", "pieces justificatives", "article direct"),
        source_terms=(
            ("procedures_fiscales_2026", ("declaration", "controle", "penalite", "recours", "notification"), 2),
            ("code_irpp_is_2011", ("declaration", "impot", "retenue"), 2),
            ("tva_droit_consommation", ("declaration", "facture", "tva"), 2),
        ),
    ),
)


def detect_cabinet_workflow(query: str) -> CabinetWorkflow | None:
    normalized = _key(query)
    best: tuple[int, CabinetWorkflow] | None = None
    for workflow in CABINET_WORKFLOWS:
        score = sum(3 for term in workflow.trigger_any if _contains(normalized, term))
        for group in workflow.trigger_all_any:
            if any(_contains(normalized, term) for term in group):
                score += 2
            else:
                score -= 2
        if workflow.family == "tva" and (_contains(normalized, "tva") or _contains(normalized, "taxe sur la valeur ajoutee")):
            score += 12
        if workflow.family == "tva" and any(_contains(normalized, term) for term in ("territorialite", "exoner", "facture conforme", "droit a deduction", "exportee")):
            score += 8
        if workflow.family == "fiscalite_directe" and any(_contains(normalized, term) for term in ("is", "irpp", "retenue a la source", "reintegr", "benefice imposable", "deduire", "deduction fiscal")):
            score += 12
        if workflow.family == "comptabilite" and any(_contains(normalized, term) for term in ("comptabil", "cloture", "stock", "revenu", "note annexe", "evenement posterieur", "partie liee")):
            score += 8
        if workflow.family == "audit_cac" and any(_contains(normalized, term) for term in ("audit", "auditeur", "cac", "commissaire aux comptes", "opinion", "rapport")):
            score += 10
        if workflow.family == "droit_societes" and any(_contains(normalized, term) for term in ("associe", "dirigeant", "gerant", "statuts", "pv", "assemblee", "capital social", "approbation des comptes", "approuve ses comptes", "sarl")):
            score += 10
        if workflow.family == "paie_social" and any(_contains(normalized, term) for term in ("salarie", "cnss", "charges sociales", "retenues salariales", "employeur", "salaire", "cotisation")):
            score += 12
        if workflow.family == "procedure_fiscale" and any(_contains(normalized, term) for term in ("controle fiscal", "notification", "recours", "penalite", "redressement", "declaration fiscale", "certificat", "procedure")):
            score += 10
        if workflow.family == "fiscalite_directe" and _contains(normalized, "tva"):
            score -= 10
        if workflow.family == "fiscalite_directe" and any(_contains(normalized, term) for term in ("statuts", "pv", "associes", "decision d associes", "salarie", "cnss")):
            score -= 6
        if workflow.family == "comptabilite" and any(_contains(normalized, term) for term in ("deduire de l is", "reintegration extra comptable", "retenue a la source")):
            score -= 8
        if workflow.family == "paie_social" and _contains(normalized, "paie") and not any(_contains(normalized, term) for term in ("salarie", "employeur", "cnss", "salaire", "cotisation", "charges sociales", "retenue salariale", "avantage en nature")):
            score -= 20
        if score > 0 and (best is None or score > best[0]):
            best = (score, workflow)
    return best[1] if best and best[0] >= 3 else None


def cabinet_coverage_status() -> dict:
    families: dict[str, list[str]] = {}
    for workflow in CABINET_WORKFLOWS:
        families.setdefault(workflow.family, []).append(workflow.id)
    return {
        "families": families,
        "workflow_count": len(CABINET_WORKFLOWS),
    }
