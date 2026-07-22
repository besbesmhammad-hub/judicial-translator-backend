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
        id="withholding_tax_general_case",
        family="fiscalite_directe",
        title="Fiscalite directe: retenues a la source",
        intent="legal_basis",
        legal_domain="fiscalite",
        trigger_any=("retenue a la source", "retenues a la source", "withholding tax", "certificat de retenue", "reversement retenue"),
        trigger_all_any=(("retenue", "retenues", "withholding"), ("source", "certificat", "reversement", "declaration", "beneficiaire")),
        source_doc_ids=("code_irpp_is_2025", "procedures_fiscales_2026", "loi_finances_2026"),
        issue_split=(
            "classer le flux par nature de revenu ou paiement",
            "identifier le payeur, le beneficiaire, la residence et le statut fiscal",
            "verifier obligation de retenue, declaration, reversement et certificat",
            "controler la convention fiscale seulement pour les non-residents",
        ),
        missing_facts=("nature du revenu", "payeur", "beneficiaire", "resident ou non-resident", "date de paiement", "article/taux direct"),
        source_terms=(
            ("code_irpp_is_2025", ("retenue a la source", "article 52", "revenus", "paiement", "beneficiaire"), 2),
            ("procedures_fiscales_2026", ("declaration", "retenue", "certificat", "reversement", "controle"), 2),
            ("loi_finances_2026", ("retenue", "loi de finances", "2026", "impot"), 2),
        ),
    ),
    CabinetWorkflow(
        id="direct_tax_deductibility_adjustment_case",
        family="fiscalite_directe",
        title="Fiscalite directe: deductibilite, reintegrations et avantages",
        intent="tax_calculation",
        legal_domain="fiscalite",
        trigger_any=("is", "irpp", "retenue a la source", "charge deductible", "charges deductibles", "reintegr", "avantage occulte", "provision", "amortissement fiscal", "benefice imposable", "convention fiscale", "double imposition", "etablissement stable", "bofip", "revenus non commerciaux", "redevances"),
        trigger_all_any=(("charge", "provision", "amortissement", "avantage", "reintegr", "retenue", "dividende", "convention", "bofip", "etablissement stable", "redevance"), ("deduire", "deductible", "fiscal", "impot", "is", "irpp", "double imposition", "france", "tunisie", "vietnam", "yemen")),
        source_doc_ids=("code_irpp_is_2011", "loi_finances_2026", "procedures_fiscales_2026", "loi_comptable", "convention_fiscale_france_tunisie", "convention_fiscale_france_tunisie_texte_1973", "boi_france_tunisie_convention_fiscale_2012", "convention_fiscale_tunisie_vietnam", "convention_fiscale_tunisie_yemen"),
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
            ("convention_fiscale_france_tunisie", ("france", "tunisie", "etablissement stable", "dividendes", "redevances"), 2),
            ("convention_fiscale_france_tunisie_texte_1973", ("france", "tunisie", "benefices des entreprises", "revenus non commerciaux", "redevances"), 2),
            ("boi_france_tunisie_convention_fiscale_2012", ("bofip", "france", "tunisie", "etablissement stable", "revenus non commerciaux"), 2),
            ("convention_fiscale_tunisie_vietnam", ("vietnam", "tunisie", "etablissement stable", "dividendes", "redevances"), 2),
            ("convention_fiscale_tunisie_yemen", ("yemen", "tunisie", "etablissement stable", "dividendes", "redevances"), 2),
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
        source_doc_ids=("tva_droit_consommation", "procedures_fiscales_2026", "loi_finances_2026"),
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
        trigger_any=("cnss", "paie", "salaire", "retenue salariale", "charges sociales", "declaration employeur", "avantage en nature", "cotisation sociale", "prets sociaux", "fonds de garantie", "pension alimentaire", "rente de divorce", "assures sociaux", "pensionnes", "bilan cnss", "appel d offres cnss", "appels d offres cnss", "marches publics cnss", "services cnss", "engagements envers le citoyen", "convention bilaterale de securite sociale", "smig", "smag", "service sms cnss", "maisons de service", "الصندوق الوطني للضمان الاجتماعي", "طلب العروض"),
        trigger_all_any=(("salaire", "paie", "cnss", "employeur", "avantage en nature", "prets sociaux", "fonds de garantie", "assures sociaux", "pensionnes", "appel d offres", "appels d offres", "marches publics", "services", "engagements", "convention bilaterale", "smig", "smag", "sms", "maisons de service", "طلب العروض"), ("declaration", "retenue", "cotisation", "charge sociale", "social", "pension alimentaire", "rente de divorce", "effectif", "montants", "bilan", "tuneps", "delais", "citoyen", "soumissionnaire", "صفقة", "securite sociale", "salaire minimum", "85785")),
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
            "cnss_a144_demande_pension",
            "cnss_n104_declaration_fille_orpheline",
            "cnss_n102_declaration_orphelin_infirme",
            "cnss_p314_fonds_garantie_pension_alimentaire",
            "cnss_p314bis_engagement_fonds_garantie_pension_alimentaire",
            "cnss_f56bis_demande_pret_logement",
            "cnss_i16_declaration_trimestrielle_salaires",
            "cnss_i27_declaration_trimestrielle_salaries_agricoles",
            "cnss_i28_etat_recapitulatif_salaires_agricoles",
            "cnss_i3_etat_recapitulatif_salaires_declares",
            "cnss_c084_majoration_salaire_unique",
            "cnss_n101_declaration_enfant_handicape",
            "cnss_f52_demande_pret_universitaire",
            "cnss_n45_inscription_travailleur_salarie",
            "cnss_p100_inscription_ayants_droit",
            "cnss_p112_immatriculation_etudiant_stagiaire_diplome",
            "cnss_n74_attestation_contentieuse",
            "cnss_n124_attestation_non_assujettissement",
            "cnss_n75_attestation_de_solde",
            "cnss_presentation_institutionnelle",
            "cnss_liste_comptes_bancaires_bureaux_regionaux",
            "cnss_accidents_travail_maladies_professionnelles",
            "cnss_guide_employeur_secteur_non_agricole",
            "cnss_flyer_sms",
            "cnss_autorisation_debit_bancaire_postal",
            "cnss_affiliation_regime_complementaire_pensions",
            "cnss_prets_sociaux_effectifs_montants_2000",
            "cnss_prets_sociaux_effectifs_montants_2020",
            "cnss_fonds_garantie_pension_divorce_2015_2020",
            "cnss_fonds_garantie_effectif_2017",
            "cnss_fonds_garantie_montants_2017",
            "cnss_sommaire_statistique_2020",
            "cnss_publication_financiere_2018",
            "cnss_evolution_cotisations_2000_2020",
            "cnss_evolution_depenses_prestations_2000_2020",
            "cnss_prestations_familiales_2020",
            "cnss_prestations_assurances_sociales_especes_2020",
            "cnss_depenses_pensions_regime_nature_2020",
            "cnss_prets_sociaux_nombre_montants_2010_2020",
            "cnss_prets_sociaux_effectifs_nature_2000_2020",
            "cnss_prets_sociaux_montants_nature_2000_2020",
            "cnss_evolution_effectif_assures_sociaux_2000_2020",
            "cnss_repartition_assures_actifs_regime_2000_2020",
            "cnss_repartition_titulaires_pensions_regime_2000_2020",
            "cnss_repartition_titulaires_pensions_nature_2000_2020",
            "cnss_rapport_demographique_2000_2020",
            "cnss_evolution_effectif_employeurs_2000_2020",
            "cnss_repartition_employeurs_regime_2000_2020",
            "cnss_notes_etats_financiers_2018",
            "cnss_budget_2022",
            "cnss_appels_offres_resultats_ar_2016_2017",
            "cnss_appels_offres_informatique_2015_2017",
            "cnss_appels_offres_travaux_2015_2017",
            "cnss_avis_appel_offres_climatiseurs_01ca2020",
            "cnss_fiches_services_octobre_2020",
            "cnss_engagements_citoyen_reseau",
            "cnss_conventions_bilaterales_securite_sociale_2017",
            "cnss_maisons_service_administration_proche",
            "cnss_smig_smag_2020",
            "cnss_service_sms",
            "cnss_communique_prets_universitaires_2017",
            "cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017",
            "cnss_avis_03ca2018_linux_tuneps",
            "cnss_avis_01ca2017_extension_bureau_mahdia",
            "cnss_report_ao20_2017_licences_oracle",
            "cnss_avis_09ca2017_iso22301_continuite_activites",
            "cnss_ao02_2020_materiel_roulant_tuneps",
            "cnss_consultation_01si2020_videosurveillance_tuneps",
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
            ("cnss_a144_demande_pension", ("demande de pension", "vieillesse", "invalidite", "retraite anticipee"), 2),
            ("cnss_n104_declaration_fille_orpheline", ("fille orpheline", "non mariee", "sans revenu", "defunt"), 2),
            ("cnss_n102_declaration_orphelin_infirme", ("orphelin", "infirmit", "maladie incurable", "sans revenu"), 2),
            ("cnss_p314_fonds_garantie_pension_alimentaire", ("fonds de garantie", "pension alimentaire", "rente de divorce", "abandon de famille"), 2),
            ("cnss_p314bis_engagement_fonds_garantie_pension_alimentaire", ("fonds de garantie", "pension alimentaire", "rente de divorce", "engagement"), 2),
            ("cnss_f56bis_demande_pret_logement", ("pret logement", "construction", "acquisition", "terrain viabilise"), 2),
            ("cnss_i16_declaration_trimestrielle_salaires", ("declaration trimestrielle", "remuneration mensuelle", "salaires declares", "trimestre"), 2),
            ("cnss_i27_declaration_trimestrielle_salaries_agricoles", ("declaration trimestrielle", "secteur agricole", "salaries", "qualification professionnelle"), 2),
            ("cnss_i28_etat_recapitulatif_salaires_agricoles", ("etat recapitulatif", "salaires declares", "secteur agricole", "cotisations"), 2),
            ("cnss_i3_etat_recapitulatif_salaires_declares", ("etat recapitulatif", "salaires declares", "cotisations", "penalites de retard"), 2),
            ("cnss_c084_majoration_salaire_unique", ("majoration pour salaire unique", "salaire unique", "conjoint", "engagement"), 2),
            ("cnss_n101_declaration_enfant_handicape", ("enfant handicape", "infirmit", "maladie incurable", "declaration sur l honneur"), 2),
            ("cnss_f52_demande_pret_universitaire", ("pret universitaire", "etudiant", "inscription", "delai de 30 jours"), 2),
            ("cnss_n45_inscription_travailleur_salarie", ("inscription", "travailleur salarie", "employeur", "secteur agricole"), 2),
            ("cnss_p100_inscription_ayants_droit", ("ayants droit", "conjoint", "enfants a charge", "parents a charge"), 2),
            ("cnss_p112_immatriculation_etudiant_stagiaire_diplome", ("immatriculation", "etudiant", "stagiaire", "diplome"), 2),
            ("cnss_n74_attestation_contentieuse", ("attestation contentieuse", "contentieux", "litige", "numero d affiliation"), 2),
            ("cnss_n124_attestation_non_assujettissement", ("attestation de non assujettissement", "non assujettissement", "identifiant fiscal", "registre de commerce"), 2),
            ("cnss_n75_attestation_de_solde", ("attestation de solde", "numero d affiliation", "raison sociale", "exemplaires"), 2),
            ("cnss_presentation_institutionnelle", ("caisse nationale de securite sociale", "loi n 60-30", "prestations familiales", "pensions"), 2),
            ("cnss_liste_comptes_bancaires_bureaux_regionaux", ("comptes bancaires", "rib", "bureau regional", "stb"), 2),
            ("cnss_accidents_travail_maladies_professionnelles", ("accidents du travail", "maladies professionnelles", "incapacite permanente", "cotisations"), 2),
            ("cnss_guide_employeur_secteur_non_agricole", ("guide de l employeur", "secteur non agricole", "declaration des salaires", "penalite de retard"), 2),
            ("cnss_flyer_sms", ("sms", "telephone portable", "service sms", "notification"), 2),
            ("cnss_autorisation_debit_bancaire_postal", ("autorisation de debit", "compte bancaire", "compte postal", "prelevement"), 2),
            ("cnss_affiliation_regime_complementaire_pensions", ("regime complementaire des pensions", "rcp", "retraite complementaire", "smig"), 2),
            ("cnss_prets_sociaux_effectifs_montants_2000", ("prets sociaux", "pret logement", "pret personnel", "pret universitaire", "annee 2000"), 2),
            ("cnss_prets_sociaux_effectifs_montants_2020", ("prets sociaux", "pret logement", "pret personnel", "pret universitaire", "annee 2020"), 2),
            ("cnss_fonds_garantie_pension_divorce_2015_2020", ("fonds de garantie", "pension alimentaire", "rente de divorce", "2015", "2020"), 2),
            ("cnss_fonds_garantie_effectif_2017", ("fonds de garantie", "effectif", "beneficiaires", "pension alimentaire", "2017"), 2),
            ("cnss_fonds_garantie_montants_2017", ("fonds de garantie", "montants", "depenses", "pension alimentaire", "2017"), 2),
            ("cnss_sommaire_statistique_2020", ("sommaire", "assures sociaux", "employeurs", "recettes", "depenses"), 2),
            ("cnss_publication_financiere_2018", ("bilan", "etat de resultat", "flux de tresorerie", "capitaux propres", "2018"), 2),
            ("cnss_evolution_cotisations_2000_2020", ("evolution des cotisations", "cotisations cnss", "ensemble des regimes", "2000", "2020"), 2),
            ("cnss_evolution_depenses_prestations_2000_2020", ("evolution des depenses", "prestations servies", "pensions", "prestations familiales", "2000"), 2),
            ("cnss_prestations_familiales_2020", ("prestations familiales", "allocations familiales", "majoration pour salaire unique", "2020"), 2),
            ("cnss_prestations_assurances_sociales_especes_2020", ("prestations en especes", "assurances sociales", "indemnite de deces", "capital deces"), 2),
            ("cnss_depenses_pensions_regime_nature_2020", ("depenses de pension", "regime complementaire", "retraite", "survie conjoints"), 2),
            ("cnss_prets_sociaux_nombre_montants_2010_2020", ("prets sociaux", "nombre et montants", "2010", "2020"), 2),
            ("cnss_prets_sociaux_effectifs_nature_2000_2020", ("prets sociaux", "effectifs par nature", "pret personnel", "pret universitaire"), 2),
            ("cnss_prets_sociaux_montants_nature_2000_2020", ("prets sociaux", "montants par nature", "pret voiture", "pret logement"), 2),
            ("cnss_evolution_effectif_assures_sociaux_2000_2020", ("effectif des assures sociaux", "actifs", "pensionnes", "ensemble des regimes"), 2),
            ("cnss_repartition_assures_actifs_regime_2000_2020", ("assures sociaux actifs", "par regime", "travailleurs non salaries", "2000"), 2),
            ("cnss_repartition_titulaires_pensions_regime_2000_2020", ("titulaires de pensions", "par regime", "salaries non agricoles", "2020"), 2),
            ("cnss_repartition_titulaires_pensions_nature_2000_2020", ("titulaires de pensions", "nature de pension", "retraites", "orphelins"), 2),
            ("cnss_rapport_demographique_2000_2020", ("rapport demographique", "nombre des actifs", "beneficiaire de pension", "2020"), 2),
            ("cnss_evolution_effectif_employeurs_2000_2020", ("effectif des employeurs", "secteur non agricole", "secteur agricole", "2000"), 2),
            ("cnss_repartition_employeurs_regime_2000_2020", ("employeurs par regime", "salaries non agricoles", "travailleurs a faible revenu", "2020"), 2),
            ("cnss_notes_etats_financiers_2018", ("notes aux etats financiers", "normes comptables tunisiennes", "cotisants", "produits techniques"), 2),
            ("cnss_budget_2022", ("budget 2022", "produits techniques", "charges techniques", "resultat technique"), 2),
            ("cnss_appels_offres_resultats_ar_2016_2017", ("طلب العروض", "اسناد الصفقة", "غير مثمر", "اقتناء"), 2),
            ("cnss_appels_offres_informatique_2015_2017", ("appel d offres", "systeme d information", "oracle", "pmsi"), 2),
            ("cnss_appels_offres_travaux_2015_2017", ("appel d offres", "construction", "amenagement", "bureau regional"), 2),
            ("cnss_avis_appel_offres_climatiseurs_01ca2020", ("avis d appel d offres", "01 ca 2020", "climatiseurs", "tuneps"), 2),
            ("cnss_fiches_services_octobre_2020", ("fiches des services", "delais", "آجال", "الخدمة", "الإنخراط", "الشهادات", "prestations"), 2),
            ("cnss_engagements_citoyen_reseau", ("engagements envers le citoyen", "bureau regional", "bureau local", "delai"), 2),
            ("cnss_conventions_bilaterales_securite_sociale_2017", ("convention bilaterale", "securite sociale", "tuniso-marocaine", "tuniso-bulgare", "tuniso-tcheque"), 2),
            ("cnss_maisons_service_administration_proche", ("administration plus proche", "maison de service", "gouvernorat", "affiliation", "immatriculation"), 2),
            ("cnss_smig_smag_2020", ("salaire minimum garanti", "smig", "smag", "decret 2020-1069", "decret 2020-1070"), 2),
            ("cnss_service_sms", ("service sms", "85785", "mandats electroniques", "cotisations", "salaires declares"), 2),
            ("cnss_communique_prets_universitaires_2017", ("prets universitaires", "decret gouvernemental 2017-369", "taux d interet", "interets de retard", "48 tranches"), 2),
            ("cnss_appels_offres_equipements_informatiques_videosurveillance_2016_2017", ("equipements informatiques", "cablage informatique", "switchs", "video-surveillance", "10 ca 2017"), 2),
            ("cnss_avis_03ca2018_linux_tuneps", ("03 ca 2018", "linux", "souscription et maintenance", "tuneps"), 2),
            ("cnss_avis_01ca2017_extension_bureau_mahdia", ("01 ca 2017", "extension", "bureau regional de mahdia", "travaux"), 2),
            ("cnss_report_ao20_2017_licences_oracle", ("20 2017", "licences oracle", "report", "14 fevrier 2018"), 2),
            ("cnss_avis_09ca2017_iso22301_continuite_activites", ("09 ca 2017", "iso 22301", "continuite des activites", "management"), 2),
            ("cnss_ao02_2020_materiel_roulant_tuneps", ("02 2020", "materiel roulant", "voiture", "camion fourgon", "tuneps"), 2),
            ("cnss_consultation_01si2020_videosurveillance_tuneps", ("01 si 2020", "video-surveillance", "tuneps", "signature electronique"), 2),
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
        trigger_any=("declaration fiscale", "declaration mensuelle", "declaration employeur", "declaration is", "declaration irpp", "delai", "controle fiscal", "penalite", "recours", "redressement", "certificat", "justificatifs", "notification", "contentieux fiscal", "teleliquidation", "licoba", "comptes bancaires", "plus-value"),
        trigger_all_any=(("declaration", "controle", "redressement", "penalite", "recours", "certificat", "licoba", "teleliquidation"), ("delai", "fiscal", "justificatif", "notification", "contentieux", "administration", "mensuelle", "employeur", "comptes bancaires")),
        source_doc_ids=("procedures_fiscales_2026", "code_irpp_is_2011", "tva_droit_consommation", "loi_finances_2026", "formulaire_declaration_mensuelle_ar_2026", "formulaire_declaration_mensuelle_ar_2025", "formulaire_declaration_is_2026", "formulaire_declaration_employeur_2025", "formulaire_declaration_irpp_ar_2025", "formulaire_plus_value_actions_ar_2025", "formulaire_impot_fortune_2026", "formulaire_adhesion_teleliquidation_impots", "cahier_charges_licoba_depot_trimestriel_comptes_2026", "schema_licoba_liste_comptes_trimestrielle_2026"),
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
            ("formulaire_declaration_mensuelle_ar_2026", ("declaration mensuelle", "mensuelle", "retenue", "tva"), 2),
            ("formulaire_declaration_is_2026", ("declaration is", "impot sur les societes", "resultats"), 2),
            ("formulaire_declaration_employeur_2025", ("declaration employeur", "employeur", "salaires"), 2),
            ("cahier_charges_licoba_depot_trimestriel_comptes_2026", ("licoba", "comptes bancaires", "depot trimestriel"), 2),
            ("schema_licoba_liste_comptes_trimestrielle_2026", ("xsd", "listecomptes", "rib"), 2),
        ),
    ),
)


def detect_cabinet_workflow(query: str) -> CabinetWorkflow | None:
    normalized = _key(query)
    if (
        any(_contains(normalized, term) for term in ("retenue a la source", "retenues a la source", "withholding tax"))
        and not any(_contains(normalized, term) for term in ("dividende", "benefices distribues", "deduire", "deductibilite", "charge deductible"))
    ):
        for workflow in CABINET_WORKFLOWS:
            if workflow.id == "withholding_tax_general_case":
                return workflow
    if (
        any(_contains(normalized, term) for term in ("ias", "ifrs"))
        and any(_contains(normalized, term) for term in ("pme tunisienne", "non cotee", "normes tunisiennes", "sct", "appliquer"))
    ):
        for workflow in CABINET_WORKFLOWS:
            if workflow.id == "accounting_closing_estimate_case":
                return workflow
    if _contains(normalized, "cnss") and any(_contains(normalized, term) for term in ("appel d offres", "appel d offre", "consultation", "tuneps", "marches publics")):
        for workflow in CABINET_WORKFLOWS:
            if workflow.family == "paie_social":
                return workflow
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
        if workflow.family == "paie_social" and _contains(normalized, "cnss") and any(_contains(normalized, term) for term in ("appel d offres", "appel d offre", "consultation", "tuneps", "marches publics")):
            score += 45
        if workflow.family == "comptabilite" and _contains(normalized, "cnss") and any(_contains(normalized, term) for term in ("appel d offres", "appel d offre", "consultation", "tuneps", "marches publics")):
            score -= 45
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
