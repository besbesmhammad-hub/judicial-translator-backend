import json
import math
import re
from functools import lru_cache
from pathlib import Path


CORPUS_PATH = Path(__file__).with_name("data") / "tunisian_legal_corpus.jsonl"
STOPWORDS = {
    "avec", "aux", "ces", "dans", "des", "du", "elle", "elles", "est", "etre",
    "les", "leur", "leurs", "par", "pas", "pour", "que", "qui", "sur",
    "une", "vous", "the", "and", "or", "من", "في", "على", "إلى", "عن", "ما",
}
SOURCE_TIER_WEIGHTS = {
    "primary_law": 1.12,
    "implementing_regulation": 1.02,
    "accounting_standard": 1.08,
    "professional_text_collection": 0.93,
    "professional_circular": 0.86,
    "professional_guide": 0.78,
    "professional_guidance": 0.82,
    "professional_article": 0.44,
    "audit_course": 0.57,
    "case_law": 0.72,
    "audit_report": 0.69,
    "regulatory_bulletin": 0.74,
    "regulatory_guidance": 0.70,
    "administrative_checklist": 0.66,
    "market_prospectus": 0.58,
    "public_procurement_tender": 0.54,
    "form_template": 0.60,
    "secondary_legal_guide": 0.46,
    "jurisprudence_analysis": 0.42,
    "policy_strategy": 0.34,
    "external_report": 0.26,
    "institutional_report": 0.50,
    "social_security_form": 0.68,
    "administrative_attestation": 0.58,
}


def tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-z']{3,}|[\u00C0-\u00FF]{3,}|[\u0600-\u06FF]{2,}", value.lower())
    return [token.strip("'") for token in tokens if token not in STOPWORDS]


@lru_cache(maxsize=1)
def load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        return []
    records = []
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                record["_tokens"] = tokenize(
                    " ".join([
                        record.get("title", ""),
                        record.get("heading", ""),
                        record.get("text", ""),
                    ])
                )
                records.append(record)
    return records


def corpus_status() -> dict:
    records = load_corpus()
    documents = sorted({record.get("doc_id") for record in records if record.get("doc_id")})
    return {
        "available": bool(records),
        "chunks": len(records),
        "documents": documents,
    }


DOMAIN_ROUTE_PATTERNS = {
    "fiscalite": re.compile(
        r"\bfiscal(?:ite)?\b|fiscalit[eé]|\btva\b|irpp|\bis\b|impot|impôt|retenue a la source|retenue à la source|"
        r"dividendes?|associe resident|associé résident|associe non resident|associé non résident|"
        r"prestations de services|prestation informatique|client etabli en france|client établi en france|client francais|client français|"
        r"procedure fiscale|procédure fiscale|procedures fiscales|procédures fiscales|loi de finances|"
        r"enregistrement|timbre|matricule fiscal|facturation electronique|facture electronique|"
        r"e-facturation|dette fiscale|dettes fiscales|redressement|controle fiscal|contrôle fiscal|"
        r"taxe environnementale|vehicules hybrides|véhicules hybrides|non residents|non-résidents|"
        r"d[ée]ductible|d[ée]ductibilit[ée]|deductibilite|deductibile|provision pour cr[ée]ances douteuses|cr[ée]ances douteuses|creance douteuse",
        re.I,
    ),
    "audit": re.compile(
        r"\baudit\b|commissaire aux comptes|\bisa\b|\bisre\b|\bisrs\b|\bisqc\b|\bifac\b|controle interne|contrôle interne|"
        r"rapport general|rapport général|rapport special|rapport spécial|certification des comptes|"
        r"seuil de signification|dossier permanent|dossier annuel|planification d'audit",
        re.I,
    ),
    "comptabilite": re.compile(
        r"\bcompta|\bcomptable\b|comptabilite|comptabilité|loi comptable|norme comptable|normes comptables|"
        r"\bnc\b|\bias\b|\bifrs\b|etat financier|état financier|etats financiers|états financiers|"
        r"bilan|grand livre|journal comptable|consolidation|parties liees|parties liées|"
        r"immobilisations|amortissement|amortissable|stocks|tableau des flux|resultat fiscal|résultat fiscal|"
        r"provision pour cr[ée]ances douteuses|cr[ée]ances douteuses",
        re.I,
    ),
    "droit_affaires": re.compile(
        r"code de commerce|code des obligations|coc\b|code des societes|code des sociétés|"
        r"sarl|societe anonyme|société anonyme|constitution de societe|constitution de société|"
        r"dissolution|liquidation|registre du commerce|fonds de commerce|cassation|tribunal",
        re.I,
    ),
    "social": re.compile(
        r"\bcnss\b|paie|salaire|charges sociales|bulletin de paie|code du travail|travailleur|"
        r"cotisations sociales|convention collective|rh\b|ressources humaines",
        re.I,
    ),
}


def infer_query_domain(query: str) -> str:
    query_text = (query or "").lower()
    if DOMAIN_ROUTE_PATTERNS["social"].search(query_text):
        return "social"
    for route in ("fiscalite", "audit", "comptabilite", "droit_affaires", "social"):
        if DOMAIN_ROUTE_PATTERNS[route].search(query_text):
            return route
    return "general"


def record_matches_domain(record: dict, route: str) -> bool:
    if route == "general":
        return True
    doc_id = record.get("doc_id", "")
    domain = record.get("domain", "")
    source_tier = record.get("source_tier", "")

    if route == "fiscalite":
        return (
            doc_id in {
                "code_irpp_is_2011",
                "tva_droit_consommation",
                "procedures_fiscales_2026",
                "enregistrement_timbre",
                "fiscalite_locale",
                "droits_taxes_hors_codes",
                "loi_finances_2026",
                "note_generale_contribution_solidarite_2026",
                "note_generale_facturation_electronique_2026",
                "note_generale_non_residents_services_administratifs_2026",
                "note_generale_regularisation_dettes_fiscales_2026",
                "note_generale_taxe_environnement_2026",
                "note_generale_fiscalite_vehicules_hybrides_2026",
            }
            or domain.startswith((
                "fiscalite_",
                "tva_",
                "enregistrement_",
                "procedures_",
                "taxe_",
                "facturation_",
                "regularisation_",
                "contribution_",
                "services_administratifs_",
                "loi_finances_",
            ))
        )
    if route == "comptabilite":
        return (
            source_tier == "accounting_standard"
            or doc_id in {"loi_comptable", "cadre_conceptuel_comptable", "ifrs_cadre_conceptuel_information_financiere"}
            or doc_id.startswith(("nc_", "ias_", "ifrs_", "nct_"))
            or domain.startswith(("comptabilite", "ias_", "ifrs_", "nc_", "nct_"))
        )
    if route == "audit":
        return (
            source_tier in {"audit_course", "audit_report", "professional_guidance"}
            or doc_id.startswith(("audit_", "rapport_cac_", "rapport_audit_", "rapport_reviseur_", "rapport_general_cac"))
            or doc_id in {"note_orientation_bct_2012_02"}
            or domain.startswith("audit_")
        )
    if route == "droit_affaires":
        return (
            doc_id in {
                "code_commerce_2014",
                "code_obligations_contrats_2015",
                "code_societes_commerciales_2022",
                "guide_creation_sarl_tunisie",
                "guide_fermeture_entreprise_tunisie",
                "tribunaux_premiere_instance_guide",
                "cour_cassation_guide",
            }
            or doc_id.startswith("cassation_")
            or domain.startswith(("droit_", "organisation_judiciaire", "dissolution_"))
        )
    if route == "social":
        return domain.startswith(("social_", "paie_", "cnss_", "travail_"))
    return True


def retrieve_legal_context(query: str, limit: int = 5) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    corpus = load_corpus()
    if not corpus:
        return []
    route = infer_query_domain(query)
    candidate_corpus = [record for record in corpus if record_matches_domain(record, route)]
    if len({record.get("doc_id") for record in candidate_corpus}) >= 3:
        corpus = candidate_corpus

    query_counts: dict[str, int] = {}
    for token in query_tokens:
        query_counts[token] = query_counts.get(token, 0) + 1
    total_docs = len(corpus)
    doc_freq: dict[str, int] = {}
    for token in query_counts:
        doc_freq[token] = sum(1 for record in corpus if token in set(record["_tokens"]))

    query_text = query.lower()
    domain_boosts = {
        "code_irpp_is_2011": r"\birpp\b|\bis\b|impot sur le revenu|impôt sur le revenu|impot sur les societes|impôt sur les sociétés|benefice imposable|bénéfice imposable|retenue a la source|retenue à la source|plus-value|plus value",
        "tva_droit_consommation": r"\btva\b|taxe sur la valeur ajout|valeur ajoutee|droit de consommation|assujetti|deduction|deductions|exoner|restitution de la taxe",
        "procedures_fiscales_2026": r"procedure fiscale|procédure fiscale|procedures fiscales|procédures fiscales|controle fiscal|contrôle fiscal|verification fiscale|vérification fiscale|contentieux fiscal|recouvrement|redressement fiscal|droit de reprise|taxation d'office|taxation d’office|reclamation fiscale|réclamation fiscale",
        "enregistrement_timbre": r"enregistrement|timbre|mutation|acte|donation|succession|bail|vente immobili",
        "fiscalite_locale": r"fiscalite locale|taxe sur les immeubles|tcl|collectivite|commune|municipal",
        "loi_finances_2026": r"loi de finances|finance 2026|budget 2026|mesures fiscales 2026|mesure fiscale|dispositions fiscales nouvelles",
        "note_generale_contribution_solidarite_2026": r"contribution sociale solidaire|contribution sociale solidarite|mcss|cotisation sociale solidaire|contribution exceptionnelle",
        "cnss_f1_demande_affiliation_employeur": r"\bcnss\b|caisse nationale de securite sociale|demande d'affiliation|demande d affiliation|affiliation employeur|representant legal|entreprise|employeur",
        "cnss_n43_liste_nominative_personnel": r"\bcnss\b|liste nominative du personnel|personnel|salaire mensuel|date de recrutement|numero assure social|qualification professionnelle|employeur",
        "cnss_p326_prise_en_charge_indemnites_licenciement": r"\bcnss\b|indemnites de licenciement|indemnites de licenciement|droits legaux|licenciement economique|raisons economiques|raisons technologiques|fermeture definitive",
        "cnss_n44_affiliation_independants": r"\bcnss\b|travailleur pour son propre compte|personnes travaillant pour leur propre compte|secteur agricole|secteur non agricole|independant|affiliation",
        "cnss_n40_affiliation_employes_maison": r"\bcnss\b|employes de maison|aide de menage|jardinier|chauffeur|affiliation employes de maison",
        "cnss_n54_affiliation_artistes_createurs": r"\bcnss\b|artistes|createurs|intellectuels|regime de securite sociale des artistes|affiliation artistes",
        "cnss_n42_affiliation_petits_armateurs": r"\bcnss\b|petits armateurs|bateaux|jauge brute|armateurs|affiliation",
        "cnss_n41_affiliation_organismes_publics": r"\bcnss\b|etat|collectivites locales|etablissements publics|organisme employeur|affiliation",
        "cnss_p212_affiliation_travailleurs_non_salaries": r"\bcnss\b|travailleurs non salaries|travailleurs non salariés|non salaries|non salariés|secteurs agricole et non agricole|decret n 95-1166|affiliation",
        "cnss_p304_affiliation_travailleurs_tunisiens_etranger": r"\bcnss\b|travailleurs tunisiens a l'etranger|travailleurs tunisiens a l etranger|tunisiens a l'etranger|tunisiens a l etranger|decret n 89-107|affiliation",
        "cnss_n66_declaration_accident_non_professionnel": r"\bcnss\b|accident non professionnel|declaration d'accident|declaration d accident|temoins|circonstances de l'accident",
        "cnss_p57_demande_indemnite_deces": r"\bcnss\b|indemnite de deces|indemnité de décès|demande d'indemnite de deces|deces de l'assure|deces du conjoint|extrait d'acte de deces",
        "cnss_p58_constat_medical_de_deces": r"\bcnss\b|constat medical de deces|constat médical de décès|cause de deces|medecin traitant|accident|suicide|homicide",
        "cnss_a144bis_pension_capital_deces_survivants": r"\bcnss\b|pension et capital deces|pension et capital décès|survivants|conjoint survivant|orphelins|jugement de deces|capital deces",
        "cnss_a144_demande_pension": r"\bcnss\b|demande de pension|pension demandee|vieillesse|invalidite|retraite anticipee|travailleur non salarie|convention bilaterale|cnrps",
        "cnss_n104_declaration_fille_orpheline": r"\bcnss\b|fille orpheline|orpheline non mariee|sans revenu|declaration sur l'honneur|déclaration sur l'honneur|defunt",
        "cnss_n102_declaration_orphelin_infirme": r"\bcnss\b|orphelin|infirmit[eé]|maladie incurable|sans revenu|non marie|non marié|declaration sur l'honneur",
        "cnss_p314_fonds_garantie_pension_alimentaire": r"\bcnss\b|fonds de garantie de la pension alimentaire|rente de divorce|abandon de famille|pension alimentaire|tribunal de premiere instance|femme divorcee",
        "cnss_p314bis_engagement_fonds_garantie_pension_alimentaire": r"\bcnss\b|fonds de garantie de la pension alimentaire|rente de divorce|engagement|non mariee|sans revenu|informer la caisse",
        "cnss_f56bis_demande_pret_logement": r"\bcnss\b|pret logement|prêt logement|demande de pret logement|construction d'un logement|acquisition d'un logement|terrain viabilise|promoteur immobilier",
        "cnss_i16_declaration_trimestrielle_salaires": r"\bcnss\b|declaration trimestrielle des salaires|déclaration trimestrielle des salaires|remuneration mensuelle|rémunération mensuelle|salaires declares|trimestre|employeur",
        "cnss_i27_declaration_trimestrielle_salaries_agricoles": r"\bcnss\b|declaration trimestrielle des salaries du secteur agricole|secteur agricole|salaries agricoles|qualification professionnelle|trimestre|employeur",
        "cnss_i28_etat_recapitulatif_salaires_agricoles": r"\bcnss\b|etat recapitulatif des salaires|état récapitulatif des salaires|salaires declares|secteur agricole|cotisation forfaitaire|accidents du travail",
        "cnss_i3_etat_recapitulatif_salaires_declares": r"\bcnss\b|etat recapitulatif des salaires declares|état récapitulatif des salaires déclarés|cotisations|salaires declares|penalites de retard|montant a payer",
        "cnss_c084_majoration_salaire_unique": r"\bcnss\b|majoration pour salaire unique|salaire unique|engagement relatif|conjoint|majoration",
        "cnss_n101_declaration_enfant_handicape": r"\bcnss\b|enfant handicape|enfant handicapé|infirmit[eé]|maladie incurable|declaration sur l'honneur|déclaration sur l'honneur",
        "cnss_f52_demande_pret_universitaire": r"\bcnss\b|pret universitaire|prêt universitaire|demande de pret universitaire|etudiant|étudiant|inscription universitaire|delai de 30 jours",
        "cnss_n45_inscription_travailleur_salarie": r"\bcnss\b|inscription travailleur salarie|inscription d'un travailleur|travailleur salarie|secteur non agricole|secteur agricole|employe de maison|employeur",
        "cnss_p100_inscription_ayants_droit": r"\bcnss\b|ayants droit|ayant droit|conjoint|enfants a charge|parents a charge|inscription d'ayants droit|immatriculation",
        "cnss_p112_immatriculation_etudiant_stagiaire_diplome": r"\bcnss\b|immatriculation etudiant|immatriculation étudiant|stagiaire|diplome|diplômé|demande d'immatriculation|etudiant stagiaire diplome",
        "cnss_n74_attestation_contentieuse": r"\bcnss\b|attestation contentieuse|accord sur un litige|accord sur un conflit|solution d'un litige|contentieux|numero d'affiliation",
        "cnss_n124_attestation_non_assujettissement": r"\bcnss\b|attestation de non assujettissement|non assujettissement|non-assujettissement|profession|registre de commerce|identifiant fiscal",
        "cnss_n75_attestation_de_solde": r"\bcnss\b|attestation de solde|demande d'attestation de solde|certificat de solde|numero d'affiliation|nom ou raison sociale",
        "attestation_activite_agricole": r"attestation|activite agricole|poursuite d'activite agricole|poursuite d activite agricole|agriculture|formation agricole",
        "note_generale_facturation_electronique_2026": r"facturation electronique|facture electronique|e-facturation|e facture|e-facture|plateforme facture|operations de services|obligation de facturation",
        "note_generale_non_residents_services_administratifs_2026": r"tunisien non resident|tunisiens non residents|non resident|services administratifs|article 109|certificat d'immatriculation|depot des declarations fiscales|dépôt des déclarations fiscales",
        "note_generale_regularisation_dettes_fiscales_2026": r"regularisation des dettes fiscales|régularisation des dettes fiscales|dettes fiscales|dettes fiscales admin|penalites fiscales|pénalités fiscales|remise des penalites|remise des pénalités|echeancier fiscal|échéancier fiscal|roznam|roseman|30 juin 2026",
        "note_generale_taxe_environnement_2026": r"mecenvironnement|taxe environnementale|taxe pour la protection de l'environnement|mpp|mou3allim lil mouhafadha 3ala al b2ia|produits manufactures localement|produits importes|produits importés|protection de l environnement",
        "note_generale_fiscalite_vehicules_hybrides_2026": r"batteries lithium|vehicules hybrides|véhicules hybrides|hybrides rechargeables|voitures hybrides|bornes de recharge|appareils de charge|moteur electrique|moteur électrique|taxation automobile",
        "loi_comptable": r"loi comptable|systeme comptable|normes comptables|etats financiers",
        "cadre_conceptuel_comptable": r"cadre conceptuel|qualitative|hypothese sous-jacente|information financiere",
        "ifrs_cadre_conceptuel_information_financiere": r"cadre conceptuel|ifrs|iasb|information financiere|caracteristiques qualitatives|image fidele|pertinence|representation fidele",
        "ifrs_1_premiere_application": r"\bifrs 1\b|premiere application des normes internationales d'information financiere|premiere application des normes internationales d information financiere|premiere adoption des ifrs|first-time adoption|bilan d'ouverture ifrs",
        "ifrs_2_paiement_fonde_sur_actions": r"\bifrs 2\b|paiement fonde sur des actions|stock-options|actions gratuites|transactions reglees en instruments de capitaux propres|share-based payment",
        "ifrs_3_regroupements_entreprises": r"\bifrs 3\b|regroupements d'entreprises|business combinations|goodwill|ecart d'acquisition|contrepartie eventuelle",
        "ifrs_4_contrats_assurance": r"\bifrs 4\b|contrats d'assurance|insurance contracts|assureur|reassurance|passif d'assurance",
        "ifrs_5_actifs_non_courants_vente": r"\bifrs 5\b|actifs non courants detenus en vue de la vente|activites abandonnees|actifs detenus en vue de la vente|discontinued operations",
        "ifrs_6_ressources_minieres": r"\bifrs 6\b|prospection et evaluation de ressources minerales|ressources minieres|minieres|actifs de prospection|exploration and evaluation",
        "ifrs_7_instruments_financiers_informations": r"\bifrs 7\b|instruments financiers\s*:?\s*informations a fournir|risque de credit|risque de liquidite|risque de marche|juste valeur|informations a fournir sur les instruments financiers",
        "ifrs_8_secteurs_operationnels": r"\bifrs 8\b|secteurs operationnels|operating segments|principal decideur operationnel|information sectorielle|segmentation operationnelle",
        "ifrs_9_instruments_financiers": r"\bifrs 9\b|instruments financiers|classement et evaluation des actifs financiers|pertes de credit attendues|expected credit loss|ecl|depreciation des actifs financiers|comptabilite de couverture|hedge accounting",
        "ifrs_10_etats_financiers_consolides": r"\bifrs 10\b|etats financiers consolides|controle d'une entite|pouvoir sur l'entite|rendements variables|consolidation|controle exclusif",
        "ifrs_11_partenariats": r"\bifrs 11\b|partenariats|joint arrangements|coentreprise|entreprise commune|activite conjointe|joint venture|joint operation",
        "ifrs_12_interets_autres_entites": r"\bifrs 12\b|interets detenus dans d'autres entites|informations a fournir sur les interets detenus dans d'autres entites|filiales|entites structurees|structured entities|participations dans d'autres entites",
        "ifrs_13_juste_valeur": r"\bifrs 13\b|juste valeur|fair value|hiérarchie de la juste valeur|hierarchie de la juste valeur|niveau 1|niveau 2|niveau 3|techniques d'evaluation|prix de sortie",
        "ifrs_14_comptes_report_reglementaires": r"\bifrs 14\b|comptes de report reglementaires|regulatory deferral accounts|soldes de report reglementaire|activites a tarifs reglementes|activites à tarifs réglementés",
        "ifrs_15_produits_contrats_clients": r"\bifrs 15\b|produits des activites ordinaires tires de contrats conclus avec des clients|reconnaissance du revenu|obligations de prestation|prix de transaction|contrat conclu avec un client|revenue from contracts with customers",
        "ifrs_16_contrats_location": r"\bifrs 16\b|contrats de location|leasing|droit d'utilisation|right-of-use|actif au titre du droit d'utilisation|passif locatif|preneur|bailleur",
        "ias_1_presentation_etats_financiers": r"\bias 1\b|presentation des etats financiers|présentation des états financiers|classement courant non courant|going concern|continuité d'exploitation|etat de la situation financiere|état de la situation financière",
        "ias_2_stocks": r"\bias 2\b|stocks|cout net de realisation|coût net de réalisation|cout des stocks|formules de cout|formules de coût",
        "ias_7_tableau_flux_tresorerie": r"\bias 7\b|tableau des flux de tresorerie|tableau des flux de trésorerie|flux de tresorerie|flux de trésorerie|activites operationnelles|activités opérationnelles|activites d'investissement|activités d'investissement",
        "ias_8_methodes_comptables_estimations_erreurs": r"\bias 8\b|methodes comptables|méthodes comptables|changements d'estimations comptables|changements d’estimations comptables|erreurs|application retrospective|application rétrospective",
        "ias_10_evenements_post_cloture": r"\bias 10\b|evenements posterieurs a la date de cloture|événements postérieurs à la date de clôture|dividendes declares apres la date de cloture|ajustement post cloture",
        "ias_11_contrats_construction": r"\bias 11\b|contrats de construction|pourcentage d'avancement|pourcentage d’avancement|produits et couts des contrats de construction|produits et coûts des contrats de construction",
        "ias_12_impots_resultat": r"\bias 12\b|impots sur le resultat|impôts sur le résultat|differences temporelles|différences temporelles|impot differe|impôt différé|actif d'impot differe|passif d'impot differe",
        "ias_16_immobilisations_corporelles": r"\bias 16\b|immobilisations corporelles|composants significatifs|amortissement|valeur residuelle|coût initial|cout initial|modele du cout|modèle du coût|modele de reevaluation|modèle de réévaluation",
        "ias_17_contrats_location": r"\bias 17\b|contrats de location|location-financement|location financement|location simple|credit-bail|preneur|bailleur",
        "ias_18_produits_activites_ordinaires": r"\bias 18\b|produits des activites ordinaires|produits des activités ordinaires|vente de biens|prestations de services|interets redevances dividendes|intérêts redevances dividendes",
        "ias_19_avantages_personnel": r"\bias 19\b|avantages du personnel|indemnites de fin de carriere|indemnités de fin de carrière|regimes a prestations definies|régimes à prestations définies|regimes a cotisations definies|régimes à cotisations définies|ecarts actuariels|écarts actuariels",
        "ias_20_subventions_publiques_aide_publique": r"\bias 20\b|subventions publiques|aide publique|aides publiques|comptabilisation des subventions publiques|informations a fournir sur l'aide publique|informations à fournir sur l'aide publique",
        "ias_21_variations_cours_monnaies_etrangeres": r"\bias 21\b|variations des cours des monnaies etrangeres|variations des cours des monnaies étrangères|ecarts de change|écarts de change|monnaie fonctionnelle|conversion des etats financiers|conversion des états financiers",
        "ias_23_couts_emprunt": r"\bias 23\b|couts d'emprunt|coûts d'emprunt|actif qualifie|actif qualifié|capitalisation des couts d'emprunt|capitalisation des coûts d'emprunt",
        "ias_24_parties_liees": r"\bias 24\b|parties liees|parties liées|transactions entre parties liees|transactions entre parties liées|personnel cle de la direction|key management personnel",
        "ias_26_regimes_retraite": r"\bias 26\b|regimes de retraite|régimes de retraite|rapports financiers des regimes de retraite|fonds de pension|plans de retraite",
        "ias_27_etats_financiers_individuels": r"\bias 27\b|etats financiers individuels|états financiers individuels|filiales dans les etats financiers individuels|participations comptabilisees au cout|méthode du coût",
        "ias_28_associees_coentreprises": r"\bias 28\b|entreprises associees|entreprises associées|coentreprises|mise en equivalence|mise en équivalence|influence notable",
        "ias_32_instruments_financiers_presentation": r"\bias 32\b|instruments financiers presentation|instruments financiers : presentation|classement passif ou capitaux propres|compensation d'actifs financiers|compensation de passifs financiers|instrument compose",
        "ias_33_resultat_par_action": r"\bias 33\b|resultat par action|résultat par action|eps de base|eps dilue|eps dilué|actions ordinaires potentielles",
        "ias_34_information_financiere_intermediaire": r"\bias 34\b|information financiere intermediaire|information financière intermédiaire|rapport financier intermediaire|rapport financier intermédiaire|periode intermediaire|période intermédiaire",
        "ias_36_depreciation_actifs": r"\bias 36\b|depreciation d'actifs|dépréciation d'actifs|perte de valeur|valeur recouvrable|unite generatrice de tresorerie|unité génératrice de trésorerie|ugt|impairment",
        "ias_37_provisions_passifs_actifs_eventuels": r"\bias 37\b|provisions|passifs eventuels|passifs éventuels|actifs eventuels|actifs éventuels|obligation actuelle|sortie de ressources|contrat deficitaire|contrat déficitaire",
        "ias_38_immobilisations_incorporelles": r"\bias 38\b|immobilisations incorporelles|actifs incorporels|recherche et developpement|recherche et développement|frais de developpement|frais de développement|duree d'utilite indefinie|durée d'utilité indéfinie",
        "ias_39_instruments_financiers_comptabilisation_evaluation": r"\bias 39\b|instruments financiers comptabilisation et evaluation|instruments financiers : comptabilisation et évaluation|derive incorpore|dérivé incorporé|actif financier disponible a la vente|actif financier disponible à la vente|comptabilite de couverture|comptabilité de couverture",
        "ias_40_immeubles_placement": r"\bias 40\b|immeubles de placement|juste valeur des immeubles de placement|modele de la juste valeur|modèle de la juste valeur|modele du cout|modèle du coût",
        "ias_41_agriculture": r"\bias 41\b|agriculture|actifs biologiques|production agricole|recolte|récolte|juste valeur diminuee des couts de vente|juste valeur diminuée des coûts de vente",
        "audit_resume_gaida_normes_missions": r"isa|isre|isrs|isqc|ifac|missions connexes|assurance|normes d'audit|normes d’audit",
        "audit_resume_maaloul_audit_financier": r"audit financier|risque d'audit|risque d’audit|planification|seuil de signification|controle interne|contrôle interne",
        "audit_resume_acceptation_controle_qualite": r"acceptation de la mission|maintien des relations client|controle qualite|contrôle qualité|isqc 1|isa 220",
        "audit_resume_chakroun_scan": r"resume d'audit|isa|isre|isqc|ifac",
        "audit_pratique_moez_chaabeen": r"dossier permanent|dossier annuel|mission d'audit|mission d’audit|organisation d'une mission d'audit|programme de travail",
        "audit_controle_qualite_imed_ennouri": r"controle de qualite|contrôle de qualité|chapitre 3|isa 220|isqc 1",
        "cours_audit_chiheb_ghanmi": r"cours d'audit|cours d’audit|audit financier|chiheb ghanmi|revision comptable|révision comptable",
        "cours_audit_imed_ennouri": r"cours d'audit financier|cours d’audit financier|imed ennouri|revsion comptable|révision comptable|audit financier",
        "droits_taxes_hors_codes": r"taxes non incorporees|circulation|voyage|assurance|telecommunication|hotel",
        "nc_01_norme_generale": r"\bnc 01\b|norme comptable generale|presentation des etats financiers|organisation comptable",
        "nc_02_capitaux_propres": r"\bnc 02\b|capitaux propres|reserve|dividende|resultat reporte",
        "nc_03_revenus": r"\bnc 03\b|revenus|produits|prestations de services|vente de biens|interets|redevances",
        "nc_04_stocks": r"\bnc 04\b|stocks|cout d'acquisition|cout de production|depreciation des stocks",
        "nc_05_immobilisations_corporelles": r"\bnc 05\b|immobilisations corporelles|amortissement|valeur residuelle|depreciation",
        "nc_06_immobilisations_incorporelles": r"\bnc 06\b|immobilisations incorporelles|actifs incorporels|logiciel|fonds commercial|recherche et developpement",
        "nc_07_placements": r"\bnc 07\b|placements|titres|portefeuille|placement a court terme|placement a long terme",
        "nc_08_resultat_net": r"\bnc 08\b|resultat net|element extraordinaire|activites ordinaires|performance",
        "nc_09_contrats_construction": r"\bnc 09\b|contrats de construction|avancement|pourcentage d'avancement|chantier|maitre d'ouvrage",
        "nc_10_charges_reportees": r"\bnc 10\b|charges reportees|frais preliminaires|frais d'emission|report de charges",
        "nc_11_modifications_comptables": r"\bnc 11\b|modifications comptables|changement de methode|correction d'erreur|estimation comptable",
        "nc_12_subventions_publiques": r"\bnc 12\b|subventions publiques|aides publiques|subvention d'investissement|subvention d'exploitation|prime d'investissement|aide de l'etat",
        "nc_13_charges_emprunt": r"\bnc 13\b|charges d'emprunt|cout d'emprunt|interets intercalaires",
        "nc_14_eventualites_post_cloture": r"\bnc 14\b|eventualites|evenements posterieurs|date de cloture|passif eventuel",
        "nc_15_monnaies_etrangeres": r"\bnc 15\b|monnaies etrangeres|ecart de change|difference de change|taux de change|devise",
        "nc_16_opcvm_etats_financiers": r"\bnc 16\b|opcvm|sicav|fcp|presentation des etats financiers des opcvm|valeur liquidative",
        "nc_17_opcvm_portefeuille_titres": r"\bnc 17\b|portefeuille-titres|operations des opcvm|cours boursier|seuil de reservation",
        "nc_18_opcvm_controle_interne": r"\bnc 18\b|controle interne des opcvm|organisation comptable des opcvm|sicav|gerant du fcp",
        "nc_19_etats_financiers_intermediaires": r"\bnc 19\b|etats financiers intermediaires|information intermediaire|periode intermediaire",
        "nc_20_recherche_developpement": r"\bnc 20\b|recherche et developpement|frais de recherche|frais de developpement",
        "nc_21_bancaire_etats_financiers": r"\bnc 21\b|etats financiers des etablissements bancaires|bilan bancaire|produit bancaire|etablissement bancaire",
        "nc_22_bancaire_controle_interne": r"\bnc 22\b|controle interne bancaire|organisation comptable bancaire|conformite bancaire",
        "nc_23_bancaire_devises": r"\bnc 23\b|operations en devises|comptabilite multi-devises|cours de change interbancaire|banque centrale de tunisie",
        "nc_24_bancaire_engagements_revenus": r"\bnc 24\b|engagements bancaires|engagement de garantie|engagement de financement|credits documentaires|prets et avances",
        "nc_25_bancaire_portefeuille_titres": r"\bnc 25\b|portefeuille-titres bancaire|titres a revenu fixe|titres a revenu variable|banque portefeuille titres",
        "nc_27_assurance_controle_interne": r"\bnc 27\b|controle interne assurance|organisation comptable assurance|reassurance|entreprise d'assurance",
        "nc_28_assurance_revenus": r"\bnc 28\b|revenus assurance|revenus reassurance|prime pure|prime d'assurance|taxes d'assurance|chargements",
        "nc_29_assurance_provisions_techniques": r"\bnc 29\b|provisions techniques|provision mathematique|provision pour sinistres|participation aux benefices|assurance provision",
        "nc_30_assurance_charges_techniques": r"\bnc 30\b|charges techniques|sinistres|ristournes|participation aux benefices|charges assurance",
        "nc_31_assurance_placements": r"\bnc 31\b|placements assurance|placements reassurance|passif reglemente|couverture des engagements|juste valeur placement",
        "nc_32_microcredit_etats_financiers": r"\bnc 32\b|micro-credits|micro credits|microcredit|etats financiers des associations|association autorisee",
        "nc_33_microcredit_controle_interne": r"\bnc 33\b|controle interne micro-credit|organisation comptable micro-credit|association de micro-credit",
        "nc_34_microcredit_revenus": r"\bnc 34\b|micro-credits et revenus y afferents|evaluation des micro-credits|revenus micro-credit",
        "nc_35_consolidation": r"\bnc 35\b|etats financiers consolides|consolidation|entreprise mere|groupe d'entreprises",
        "nc_36_associees": r"\bnc 36\b|entreprises associees|influence notable|mise en equivalence",
        "nc_37_coentreprises": r"\bnc 37\b|coentreprises|entite controlee conjointement|activites controlees conjointement|controle conjoint",
        "nc_38_regroupements_entreprises": r"\bnc 38\b|regroupements d'entreprises|fusion|acquisition d'une entreprise|goodwill|ecart d'acquisition",
        "nc_39_parties_liees": r"\bnc 39\b|parties liees|transactions entre parties liees|societe mere|filiale liee",
        "nc_40_structures_sportives": r"\bnc 40\b|structures sportives privees|federation sportive|association sportive|club sportif",
        "nc_41_contrats_location": r"\bnc 41\b|contrats de location|location-financement|location financement|credit-bail|location simple|preneur|bailleur",
        "nc_42_comptabilite_simplifiee": r"\bnc 42\b|comptabilite simplifiee|petite entreprise|regime simplifie",
        "nct_43_takaful_etats_financiers": r"\bnct 43\b|takaful|retakaful|etats financiers takaful|commission wakala|moudharaba",
        "nct_44_takaful_controle_interne": r"\bnct 44\b|controle interne takaful|organisation comptable takaful|retakaful|operateur du fonds",
        "nct_45_osbl": r"\bnct 45\b|organismes sans but lucratif|osbl|associations|partis politiques|organisme sans but lucratif|fonds associatif",
        "textes_profession_comptable_2018": r"expert-comptable|experts-comptables|comptable|compagnie des comptables|ordre des experts comptables|commissaire aux comptes|commissariat aux comptes|مراقبي الحسابات|الخبراء المحاسبين|المحاسبين",
        "circulaire_stagiaires_2018": r"stagiaire|stagiaires|stage|compte rendu de stage|controleur de stage|maitre de stage|ترسيم|تربص",
        "formulaire_compte_rendu_stagiaire": r"compte rendu d'activite|compte rendu d.activit|formulaire|stage|stagiaire|controleur de stage|maitre de stage",
        "code_commerce_2014": r"code de commerce|fonds de commerce|commercant|commerçant|registre du commerce|effets de commerce|faillite|cheque|chèque",
        "code_obligations_contrats_2015": r"\bcoc\b|code des obligations et des contrats|obligations et contrats|responsabilite civile|responsabilité civile|nullite|nullité|preuve des obligations|contrat",
        "code_societes_commerciales_2022": r"code des societes commerciales|code des sociétés commerciales|societe commerciale|société commerciale|sarl|constitution de societe|constitution de société|gerant|gérant|assemblee generale|assemblée générale",
        "guide_inscription_personnes_morales_2026": r"inscription personnes morales|inscription societes|inscription sociétés|societe de comptabilite|société de comptabilité|قسم شركات المحاسبة|ترسيم.*شركات",
        "guide_inscription_stagiaires_2026": r"inscription stagiaires|guide inscription stagiaires|attestation de prise en charge|قائمة المتربصين|دليل الترسيم بقائمة المتربصين",
        "guide_inscription_personnes_physiques_2026": r"inscription personnes physiques|guide inscription personnes physiques|قسم المحاسبين|أشخاص طبيعيين|جدول المجمع",
        "formulaire_radiation_2026": r"radiation|demande de radiation|شطب نهائي|مطلب شطب",
        "demande_attestation_inscription_2026": r"attestation d[' ]?inscription|attestation inscription|شهادة ترسيم|مطلب في الحصول على شهادة ترسيم",
        "formulaire_suspension_2026": r"suspension|demande de suspension|تعليق عضوية|مطلب تعليق",
        "tribunaux_premiere_instance_guide": r"tribunal de premiere instance|tribunaux de premiere instance|competence territoriale|competence d'attribution|juge cantonal|cour d'appel",
        "cour_cassation_guide": r"cour de cassation|pourvoi en cassation|recours en cassation|reglement de juges|renvoi d'un tribunal",
        "checklist_constitution_sa_api": r"societe anonyme|société anonyme|\bsa\b|constitution d'une sa|constitution d une sa|appel public a l'epargne|appel public à l'épargne|agc|conseil d'administration",
        "guide_creation_sarl_tunisie": r"\bsarl\b|societe a responsabilite limitee|société à responsabilité limitée|creation d'une sarl|creation d une sarl|immatriculation sarl|parts sociales|capital social minimal",
        "guide_fermeture_entreprise_tunisie": r"fermeture d[' ]une entreprise|fermeture d'entreprise|fermeture d entreprise|fermeture entreprise|dissolution anticipee|dissolution anticipée|liquidation de la societe|liquidation de la société|cessation d'activite|cessation d'activité|radiation personne morale",
        "cassation_chambres_reunies_terrorisme_2019": r"chambres reunies|chambres réunies|terrorisme|pôle judiciaire de lutte contre le terrorisme|juge d'instruction militaire|article 273 du cpp|qualification juridique correcte",
        "cassation_acte_commerce_accessoire_2019": r"acte de commerce par accessoire|commercialite par accessoire|commercialité par accessoire|chambre commerciale|article 40 cpcc|article 2 du code de commerce",
        "cassation_sequestre_societe_anonyme_2018": r"sequestre de la societe|séquestre de la société|societe anonyme cotee|société anonyme cotée|mise sous sequestre|mise sous séquestre|loi n°71-1997",
        "cassation_arbitrage_interne_2018": r"arbitrage interne|sentence arbitrale|recours en annulation|article 42 du code de l'arbitrage|article 44 du code de l'arbitrage",
        "cassation_dissolution_sarl_affectio_2018": r"dissolution de la sarl|dissolution judiciaire de la société|affectio societatis|mésintelligence grave entre associés|mesintelligence grave entre associes|article 26 du csc|article 1323 du coc",
        "cassation_reglement_judiciaire_cotisations_2017": r"reglement judiciaire|règlement judiciaire|cotisations complementaires de retraite|cotisations complémentaires de retraite|loi n°2016-36|redressement des entreprises en difficulte|entreprises en difficulté",
        "cassation_terrorisme_participation_groupe_2017": r"participation a un groupe terroriste|participation à un groupe terroriste|element materiel|élément matériel|element moral|élément moral|articles 162/168/199 cpp|syrie|entraînement militaire",
        "cassation_accident_route_baremes_2017": r"accident de la voie publique|barèmes de responsabilité|baremes de responsabilite|article 123 du code des assurances|préjudice économique|préjudic e economique|conducteur victime",
        "cassation_clause_compromissoire_2017": r"clause compromissoire|promesse de vente|procuration|arbitrage interne|validité du contrat|validite du contrat|article 119 du cpcc",
        "cmf_bulletin_officiel_2017_04_11": r"bulletin officiel du conseil du marche financier|bulletin officiel du cmf|appel public a l'epargne|appel public à l'épargne|assemblees generales|assemblées générales|societes admises a la cote|sociétés admises à la cote",
        "guide_agrement_etablissement_paiement_tunisie": r"etablissement de paiement|établissement de paiement|dossier d'agrement|dossier d’agrément|agrément de principe|agrément définitif|business model canvas|banque centrale",
        "appel_offres_assurance_tunisie_autoroutes_2026": r"appel d'offres|appel d’offres|tunisie autoroutes|contrats d'assurance|contrats d’assurances|ccap|cctp|cahier des charges|souscription des contrats d'assurance",
        "prospectus_hexabyte_2011_2012": r"hexabyte|marche alternatif|marché alternatif|augmentation de capital|offre a prix ferme|offre à prix ferme|listing sponsor|visa du conseil du marche financier",
        "prospectus_fusion_tunisie_leasing": r"tunisie leasing|fusion|prospectus de fusion|amen bank|fitch ratings|encours financiers|creances classees|créances classées",
        "strategie_habitat_tunisie_2015": r"strategie de l'habitat|stratégie de l'habitat|politique de l'habitat|logement|ministere de l'equipement|ministère de l'équipement",
        "banque_mondiale_strategie_transports_tunisie": r"banque mondiale|strategie des transports|stratégie des transports|transport|moyen-orient et afrique du nord",
        "rapport_cac_ance_2016": r"rapport du reviseur des comptes|rapport de revision des comptes|commissaire aux comptes|certification des comptes|opinion|avec reserves|sans reserves|ance|agence nationale de certification electronique",
        "rapport_cac_innorpi_2021": r"rapport du reviseur des comptes|rapport special du reviseur des comptes|innorpi|etats financiers|notes relatives aux etats financiers|commissaire aux comptes|certification des comptes",
        "rapport_cac_bna_2018": r"rapport general et special|rapport général et spécial|banque nationale agricole|bna|conventions reglementees|conventions réglementées|commissaire aux comptes|etats financiers",
        "rapport_cac_ote_2014": r"rapport general du commissaire aux comptes|ote|opinion du commissaire aux comptes|exercice clos le 31/12/2014|certification",
        "rapport_cac_cefa_tunisie_2020": r"cefa tunisie|rapport du commissaire aux comptes|exercice clos le 31 decembre 2020|exercice clos le 31 décembre 2020|audit|certification des comptes",
        "rapport_cac_act_2021": r"association for cooperation in tunisia|act|rapport cac|commissaire aux comptes|association|financial statements|opinion",
        "rapport_cac_irc_2017": r"irc tunisie|international rescue committee|rapport d'audit|rapport d’audit|commissaire aux comptes|exercice clos le 31 decembre 2017|exercice clos le 31 décembre 2017",
        "note_orientation_bct_2012_02": r"circulaire bct 2012-02|note d'orientation|note d’orientation|provisions collectives|etablissement de credit|établissement de crédit|rapport special|rapport spécial|niveau d'assurance|niveau d’assurance",
        "rapport_reviseur_legal_smls_2017": r"rapport reviseur legal|rapport réviseur légal|etats financiers|états financiers|societe de metro leger de sfax|société de métro léger de sfax|exercice clos au 31 decembre 2017|exercice clos au 31 décembre 2017",
        "rapport_general_cac_2017": r"rapport general des commissaires aux comptes|rapport général des commissaires aux comptes|rapport general|rapport général|commissaires aux comptes",
        "rapport_audit_nebras_2023": r"rapport du commissaire aux comptes|nebras|institut tunisien de rehabilitation des survivants de la torture|institut tunisien de réhabilitation des survivants de la torture|etats financiers arretes|états financiers arrêtés|31 decembre 2023|31 décembre 2023",
        "loi_experts_judiciaires_1993": r"experts judiciaires|expert judiciaire|loi n° 93-61|loi 93-61|liste des experts judiciaires|commission regionale|conseil de discipline",
        "arrete_composition_commission_experts_1993": r"composition de la commission regionale|commission régionale|demandes d'inscription des experts judiciaires|article 5 de la loi n° 93-61",
        "arrete_delais_inscription_experts_1993": r"delais de presentation des demandes d'inscription|délais de présentation des demandes d'inscription|premiere liste des experts judiciaires|première liste des experts judiciaires",
        "arrete_manuel_procedures_expert_judiciaire_2000": r"manuel de procedures de l'expert judiciaire|manuel de procédures de l'expert judiciaire|approbation du manuel de procedures|3 juin 2000",
        "loi_modification_experts_judiciaires_2010": r"experts judiciaires|article 4 nouveau|personne morale dans la liste des experts|conditions d'inscription|loi 2010|resident en tunisie",
        "article_revue_expertise_comptable_2011": r"revue comptable et financiere|reforme du cursus|réforme du cursus|examen national|revision comptable|révision comptable|expertise comptable",
        "analyse_amnistie_reconciliation_administrative": r"amnistie|réconciliation nationale|reconciliation nationale|loi du 24 octobre 2017|loi n° 02 du 24/10/2017|profit personnel|fonctionnaire public",
        "rapport_moral_2023": r"rapport moral|rapport d'activite|conseil national|compagnie des comptables",
        "rapport_moral_2024": r"rapport moral|rapport d'activite|conseil national|compagnie des comptables",
        "rapport_moral_2025": r"rapport moral|rapport d'activite|conseil national|compagnie des comptables",
    }

    scored = []
    for record in corpus:
        tokens = record["_tokens"]
        if not tokens:
            continue
        token_counts: dict[str, int] = {}
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
        score = 0.0
        for token, query_count in query_counts.items():
            frequency = token_counts.get(token, 0)
            if not frequency:
                continue
            inverse_df = math.log((1 + total_docs) / (1 + doc_freq.get(token, 0))) + 1
            score += query_count * (1 + math.log(frequency)) * inverse_df

        score *= SOURCE_TIER_WEIGHTS.get(record.get("source_tier", ""), 1.0)
        pattern = domain_boosts.get(record.get("doc_id", ""))
        if pattern and re.search(pattern, query_text, re.I):
            if score == 0:
                score = 1.0
            score *= 2.8

        if record.get("source_tier") == "institutional_report" and not re.search(
            r"rapport moral|rapport d'activite|conseil national|ordre des experts|compagnie des comptables|cct",
            query_text,
            re.I,
        ):
            score *= 0.18
        if record.get("source_tier") == "form_template" and not re.search(
            r"formulaire|compte rendu|stagiaire|stage|controleur de stage|maitre de stage|radiation|suspension|attestation",
            query_text,
            re.I,
        ):
            score *= 0.15
        if record.get("source_tier") == "professional_circular" and not re.search(
            r"stagiaire|stage|ترسيم|تربص|controleur de stage|maitre de stage|inscription au stage",
            query_text,
            re.I,
        ):
            score *= 0.42
        if record.get("source_tier") == "professional_guide" and not re.search(
            r"inscription|guide|stagiaire|stage|societe|société|personne morale|personne physique|ترسيم|شطب|تعليق|attestation",
            query_text,
            re.I,
        ):
            score *= 0.38
        if record.get("source_tier") == "implementing_regulation" and not re.search(
            r"experts judiciaires|expert judiciaire|arrete|arrêté|commission regionale|commission régionale|inscription|manuel de procedures|manuel de procédures",
            query_text,
            re.I,
        ):
            score *= 0.24
        if record.get("source_tier") == "professional_guidance" and not re.search(
            r"note d'orientation|note d’orientation|circulaire bct|provisions collectives|rapport special|rapport spécial|commissaire aux comptes|etablissement de credit|établissement de crédit",
            query_text,
            re.I,
        ):
            score *= 0.24
        if record.get("source_tier") == "professional_article" and not re.search(
            r"expertise comptable|examen national|revision comptable|révision comptable|reforme du cursus|réforme du cursus|revue comptable et financiere",
            query_text,
            re.I,
        ):
            score *= 0.16
        if record.get("source_tier") == "audit_course" and not re.search(
            r"\baudit\b|commissaire aux comptes|isa|isre|isrs|isqc|ifac|controle qualite|contrôle qualité|acceptation de la mission|planification|risque d'audit|risque d’audit|controle interne|contrôle interne|dossier permanent|dossier annuel|seuil de signification|programme de travail|revision comptable|révision comptable",
            query_text,
            re.I,
        ):
            score *= 0.18
        if record.get("source_tier") == "audit_report" and not re.search(
            r"commissaire aux comptes|reviseur des comptes|réviseur des comptes|rapport general|rapport général|rapport special|rapport spécial|certification des comptes|opinion|reserves|réserves|etats financiers|états financiers|conventions reglementees|conventions réglementées",
            query_text,
            re.I,
        ):
            score *= 0.26
        if record.get("source_tier") == "regulatory_bulletin" and not re.search(
            r"cmf|conseil du marche financier|conseil du marché financier|bulletin officiel|appel public a l'epargne|appel public à l'épargne|assemblee generale|assemblée générale|cote de la bourse",
            query_text,
            re.I,
        ):
            score *= 0.28
        if record.get("source_tier") == "regulatory_guidance" and not re.search(
            r"etablissement de paiement|établissement de paiement|agrement|agrément|banque centrale|dossier d'agrement|dossier d’agrément|business plan",
            query_text,
            re.I,
        ):
            score *= 0.24
        if record.get("source_tier") == "administrative_checklist" and not re.search(
            r"societe anonyme|société anonyme|\bsa\b|constitution|immatriculation|registre national des entreprises|appel public a l'epargne|appel public à l'épargne",
            query_text,
            re.I,
        ):
            score *= 0.32
        if record.get("source_tier") == "market_prospectus" and not re.search(
            r"prospectus|introduction en bourse|introduction en bourse|augmentation de capital|fusion|cmf|conseil du marche financier|marché alternatif|marche alternatif|listing sponsor|tunisie leasing|hexabyte",
            query_text,
            re.I,
        ):
            score *= 0.22
        if record.get("source_tier") == "public_procurement_tender" and not re.search(
            r"appel d'offres|appel d’offres|cahier des charges|ccap|cctp|tunisie autoroutes|contrats d'assurance|contrats d’assurances|marche public|marché public",
            query_text,
            re.I,
        ):
            score *= 0.20
        if record.get("source_tier") == "secondary_legal_guide" and not re.search(
            r"tribunal|cassation|sarl|societe anonyme|société anonyme|\bsa\b|creation d'entreprise|création d'entreprise|fermeture d'entreprise|dissolution|liquidation",
            query_text,
            re.I,
        ):
            score *= 0.22
        if record.get("source_tier") == "case_law" and not re.search(
            r"cassation|pourvoi|jurisprudence|arbitrage|terrorisme|competence juridictionnelle|compétence juridictionnelle|acte de commerce|sequestre|séquestre|dissolution|affectio societatis|reglement judiciaire|règlement judiciaire|cotisations|accident de la voie publique|barèmes de responsabilité|clause compromissoire",
            query_text,
            re.I,
        ):
            score *= 0.26
        if record.get("source_tier") == "jurisprudence_analysis" and not re.search(
            r"amnistie|réconciliation nationale|reconciliation nationale|fonctionnaire public|profit personnel|poursuites judiciaires",
            query_text,
            re.I,
        ):
            score *= 0.18
        if record.get("source_tier") == "policy_strategy" and not re.search(
            r"strategie|stratégie|habitat|logement|politique publique|ministere de l'equipement|ministère de l'équipement",
            query_text,
            re.I,
        ):
            score *= 0.16
        if record.get("source_tier") == "external_report" and not re.search(
            r"banque mondiale|strategie des transports|stratégie des transports|transport|etude|étude",
            query_text,
            re.I,
        ):
            score *= 0.12
        if record.get("doc_id", "").startswith("ifrs_") and not re.search(
            r"\bifrs\b|iasb|normes internationales d'information financiere|normes internationales d information financiere|cadre conceptuel|goodwill|ecart d'acquisition|paiement fonde sur des actions|stock-options|regroupements d'entreprises|contrats d'assurance|actifs non courants detenus en vue de la vente|activites abandonnees|ressources minieres|bilan d'ouverture ifrs|first-time adoption|instruments financiers|pertes de credit attendues|expected credit loss|comptabilite de couverture|hedge accounting|secteurs operationnels|consolidation|etats financiers consolides|partenariats|coentreprise|activite conjointe|filiales|entites structurees|juste valeur|fair value|reconnaissance du revenu|obligations de prestation|prix de transaction|contrats de location|droit d'utilisation|passif locatif|comptes de report reglementaires",
            query_text,
            re.I,
        ):
            score *= 0.52
        if record.get("doc_id", "").startswith("ias_") and not re.search(
            r"\bias\b|norme comptable internationale|normes comptables internationales|presentation des etats financiers|stocks|flux de tresorerie|flux de trésorerie|methodes comptables|méthodes comptables|estimations comptables|evenements posterieurs|événements postérieurs|contrats de construction|impots sur le resultat|impôts sur le résultat|impot differe|impôt différé|immobilisations corporelles|location-financement|location financement|credit-bail|avantages du personnel|subventions publiques|aide publique|ecarts de change|écarts de change|monnaie fonctionnelle|couts d'emprunt|coûts d'emprunt|parties liees|parties liées|regimes de retraite|régimes de retraite|etats financiers individuels|états financiers individuels|mise en equivalence|mise en équivalence|resultat par action|résultat par action|information financiere intermediaire|information financière intermédiaire|depreciation d'actifs|dépréciation d'actifs|valeur recouvrable|provisions|passifs eventuels|passifs éventuels|actifs eventuels|actifs éventuels|immobilisations incorporelles|actifs incorporels|derive incorpore|dérivé incorporé|immeubles de placement|actifs biologiques|production agricole",
            query_text,
            re.I,
        ):
            score *= 0.58

        if "subvention" in query_text or "aide publique" in query_text or "aides publiques" in query_text:
            if record.get("doc_id") == "nc_12_subventions_publiques":
                score *= 4.0
            elif record.get("doc_id") == "tva_droit_consommation" and "tva" not in query_text:
                score *= 0.35
        if "opcvm" in query_text and ("controle interne" in query_text or "contrôle interne" in query_text):
            if record.get("doc_id") == "nc_18_opcvm_controle_interne":
                score *= 4.0
            elif record.get("doc_id") == "nc_16_opcvm_etats_financiers":
                score *= 0.45
        if ("assurance" in query_text or "réassurance" in query_text or "reassurance" in query_text) and ("controle interne" in query_text or "contrôle interne" in query_text):
            if record.get("doc_id") == "nc_27_assurance_controle_interne":
                score *= 4.0
        if ("assurance" in query_text or "réassurance" in query_text or "reassurance" in query_text) and "revenu" in query_text:
            if record.get("doc_id") == "nc_28_assurance_revenus":
                score *= 4.0
            elif record.get("doc_id") == "droits_taxes_hors_codes":
                score *= 0.25
        if ("assurance" in query_text or "réassurance" in query_text or "reassurance" in query_text) and "placement" in query_text:
            if record.get("doc_id") == "nc_31_assurance_placements":
                score *= 4.0
            elif record.get("doc_id") in {"droits_taxes_hors_codes", "nc_07_placements"}:
                score *= 0.35
        if ("banque" in query_text or "bancaire" in query_text) and "portefeuille" in query_text:
            if record.get("doc_id") == "nc_25_bancaire_portefeuille_titres":
                score *= 3.5
        if ("micro-credit" in query_text or "micro credit" in query_text or "microcrédit" in query_text or "microcredits" in query_text or "micro-crédits" in query_text) and ("controle interne" in query_text or "contrôle interne" in query_text):
            if record.get("doc_id") == "nc_33_microcredit_controle_interne":
                score *= 4.0
            elif record.get("doc_id") == "nc_32_microcredit_etats_financiers":
                score *= 0.45
        if ("micro-credit" in query_text or "micro credit" in query_text or "microcrédit" in query_text or "microcredits" in query_text or "micro-crédits" in query_text) and ("etat financier" in query_text or "état financier" in query_text or "etats financiers" in query_text or "états financiers" in query_text or "presentation" in query_text or "présentation" in query_text):
            if record.get("doc_id") == "nc_32_microcredit_etats_financiers":
                score *= 4.0
            elif record.get("doc_id") == "nc_33_microcredit_controle_interne":
                score *= 0.4
        if ("micro-credit" in query_text or "micro credit" in query_text or "microcrédit" in query_text or "microcredits" in query_text or "micro-crédits" in query_text) and "revenu" in query_text:
            if record.get("doc_id") == "nc_34_microcredit_revenus":
                score *= 4.0
            elif record.get("doc_id") == "nc_32_microcredit_etats_financiers":
                score *= 0.4
        if ("consolid" in query_text or "groupe" in query_text) and "assoc" in query_text:
            if record.get("doc_id") == "nc_36_associees":
                score *= 3.5
            elif record.get("doc_id") == "droits_taxes_hors_codes":
                score *= 0.2
        if ("ifrs 3" in query_text or "regroupements d'entreprises" in query_text or "goodwill" in query_text or "ecart d'acquisition" in query_text):
            if record.get("doc_id") == "ifrs_3_regroupements_entreprises":
                score *= 4.4
            elif record.get("doc_id") == "nc_38_regroupements_entreprises":
                score *= 2.4
        if ("ifrs 2" in query_text or "paiement fonde sur des actions" in query_text or "stock-options" in query_text or "share-based payment" in query_text):
            if record.get("doc_id") == "ifrs_2_paiement_fonde_sur_actions":
                score *= 4.4
        if ("ifrs 1" in query_text or "premiere application des normes internationales d'information financiere" in query_text or "premiere application des normes internationales d information financiere" in query_text or "first-time adoption" in query_text or "bilan d'ouverture ifrs" in query_text):
            if record.get("doc_id") == "ifrs_1_premiere_application":
                score *= 4.4
            elif record.get("doc_id") == "ifrs_cadre_conceptuel_information_financiere":
                score *= 1.6
        if ("ifrs 4" in query_text or "contrats d'assurance" in query_text or "insurance contracts" in query_text):
            if record.get("doc_id") == "ifrs_4_contrats_assurance":
                score *= 4.4
            elif record.get("doc_id") in {"nc_27_assurance_controle_interne", "nc_28_assurance_revenus", "nc_29_assurance_provisions_techniques", "nc_30_assurance_charges_techniques", "nc_31_assurance_placements"}:
                score *= 1.8
        if ("ifrs 5" in query_text or "actifs non courants detenus en vue de la vente" in query_text or "activites abandonnees" in query_text or "discontinued operations" in query_text):
            if record.get("doc_id") == "ifrs_5_actifs_non_courants_vente":
                score *= 4.4
        if ("ifrs 6" in query_text or "prospection et evaluation de ressources minerales" in query_text or "ressources minieres" in query_text or "exploration and evaluation" in query_text):
            if record.get("doc_id") == "ifrs_6_ressources_minieres":
                score *= 4.4
        if ("ifrs 7" in query_text or "informations a fournir sur les instruments financiers" in query_text or "risque de credit" in query_text or "risque de liquidite" in query_text or "risque de marche" in query_text):
            if record.get("doc_id") == "ifrs_7_instruments_financiers_informations":
                score *= 4.4
            elif record.get("doc_id") == "ifrs_9_instruments_financiers":
                score *= 1.7
        if ("ifrs 8" in query_text or "secteurs operationnels" in query_text or "operating segments" in query_text or "principal decideur operationnel" in query_text):
            if record.get("doc_id") == "ifrs_8_secteurs_operationnels":
                score *= 4.4
        if ("ifrs 9" in query_text or "pertes de credit attendues" in query_text or "expected credit loss" in query_text or "comptabilite de couverture" in query_text or "hedge accounting" in query_text or "classement et evaluation des actifs financiers" in query_text):
            if record.get("doc_id") == "ifrs_9_instruments_financiers":
                score *= 4.6
            elif record.get("doc_id") == "ifrs_7_instruments_financiers_informations":
                score *= 1.8
        if ("ifrs 10" in query_text or "etats financiers consolides" in query_text or "états financiers consolidés" in query_text or "controle d'une entite" in query_text or "contrôle d'une entité" in query_text):
            if record.get("doc_id") == "ifrs_10_etats_financiers_consolides":
                score *= 4.4
            elif record.get("doc_id") in {"nc_35_consolidation", "nc_36_associees", "nc_37_coentreprises"}:
                score *= 1.8
        if ("ifrs 11" in query_text or "partenariats" in query_text or "joint arrangements" in query_text or "coentreprise" in query_text or "activite conjointe" in query_text or "activité conjointe" in query_text):
            if record.get("doc_id") == "ifrs_11_partenariats":
                score *= 4.4
            elif record.get("doc_id") in {"nc_37_coentreprises", "nc_36_associees"}:
                score *= 1.7
        if ("ifrs 12" in query_text or "interets detenus dans d'autres entites" in query_text or "intérêts détenus dans d'autres entités" in query_text or "entites structurees" in query_text or "entités structurées" in query_text or "filiales" in query_text):
            if record.get("doc_id") == "ifrs_12_interets_autres_entites":
                score *= 4.4
            elif record.get("doc_id") == "ifrs_10_etats_financiers_consolides":
                score *= 1.7
        if ("ifrs 13" in query_text or "juste valeur" in query_text or "fair value" in query_text or "hierarchie de la juste valeur" in query_text or "hiérarchie de la juste valeur" in query_text):
            if record.get("doc_id") == "ifrs_13_juste_valeur":
                score *= 4.6
            elif record.get("doc_id") == "ifrs_7_instruments_financiers_informations":
                score *= 1.6
        if ("ifrs 14" in query_text or "comptes de report reglementaires" in query_text or "regulatory deferral accounts" in query_text or "soldes de report reglementaire" in query_text):
            if record.get("doc_id") == "ifrs_14_comptes_report_reglementaires":
                score *= 4.4
        if ("ifrs 15" in query_text or "produits des activites ordinaires tires de contrats conclus avec des clients" in query_text or "reconnaissance du revenu" in query_text or "obligations de prestation" in query_text or "prix de transaction" in query_text):
            if record.get("doc_id") == "ifrs_15_produits_contrats_clients":
                score *= 4.6
            elif record.get("doc_id") in {"nc_03_revenus", "nc_09_contrats_construction"}:
                score *= 1.7
        if ("ifrs 16" in query_text or "contrats de location" in query_text or "leasing" in query_text or "droit d'utilisation" in query_text or "droit dutilisation" in query_text or "passif locatif" in query_text):
            if record.get("doc_id") == "ifrs_16_contrats_location":
                score *= 4.6
            elif record.get("doc_id") == "nc_41_contrats_location":
                score *= 1.9
        if ("ias 1" in query_text or "presentation des etats financiers" in query_text or "présentation des états financiers" in query_text or "classement courant non courant" in query_text or "continuité d'exploitation" in query_text or "continuite d'exploitation" in query_text):
            if record.get("doc_id") == "ias_1_presentation_etats_financiers":
                score *= 4.6
            elif record.get("doc_id") in {"nc_01_norme_generale", "loi_comptable"}:
                score *= 1.8
        if ("ias 2" in query_text or "cout net de realisation" in query_text or "coût net de réalisation" in query_text or ("stocks" in query_text and "ias" in query_text)):
            if record.get("doc_id") == "ias_2_stocks":
                score *= 4.4
            elif record.get("doc_id") == "nc_04_stocks":
                score *= 1.8
        if ("ias 7" in query_text or "tableau des flux de tresorerie" in query_text or "tableau des flux de trésorerie" in query_text or "flux de tresorerie" in query_text or "flux de trésorerie" in query_text):
            if record.get("doc_id") == "ias_7_tableau_flux_tresorerie":
                score *= 4.4
        if ("ias 8" in query_text or "methodes comptables" in query_text or "méthodes comptables" in query_text or "changements d'estimations comptables" in query_text or "changements d’estimations comptables" in query_text or "application retrospective" in query_text or "application rétrospective" in query_text):
            if record.get("doc_id") == "ias_8_methodes_comptables_estimations_erreurs":
                score *= 4.4
            elif record.get("doc_id") == "nc_11_modifications_comptables":
                score *= 1.8
        if ("ias 10" in query_text or "evenements posterieurs a la date de cloture" in query_text or "événements postérieurs à la date de clôture" in query_text or "post cloture" in query_text):
            if record.get("doc_id") == "ias_10_evenements_post_cloture":
                score *= 4.4
            elif record.get("doc_id") == "nc_14_eventualites_post_cloture":
                score *= 1.8
        if ("dividendes" in query_text and ("associe resident" in query_text or "associe" in query_text or "retenue a la source" in query_text or "consequences fiscales" in query_text)):
            if record.get("doc_id") == "code_irpp_is_2011":
                score *= 5.4
            elif record.get("doc_id") == "procedures_fiscales_2026":
                score *= 1.8
            elif record.get("doc_id") == "loi_finances_2026":
                score *= 1.4
            elif record.get("doc_id") in {"code_societes_commerciales_2022", "guide_creation_sarl_tunisie"}:
                score *= 0.45
        if (("prestations de services" in query_text or "prestation informatique" in query_text) and ("france" in query_text or "client etabli" in query_text or "client établi" in query_text)):
            if record.get("doc_id") == "tva_droit_consommation":
                score *= 5.6
            elif record.get("doc_id") == "procedures_fiscales_2026":
                score *= 1.6
            elif record.get("doc_id") == "code_irpp_is_2011":
                score *= 0.28
            elif record.get("doc_id") in {"droits_taxes_hors_codes", "fiscalite_locale"}:
                score *= 0.35
        if ("ias 11" in query_text or "contrats de construction" in query_text or "pourcentage d'avancement" in query_text or "pourcentage d’avancement" in query_text):
            if record.get("doc_id") == "ias_11_contrats_construction":
                score *= 4.2
            elif record.get("doc_id") == "nc_09_contrats_construction":
                score *= 1.9
        if ("ias 12" in query_text or "impots sur le resultat" in query_text or "impôts sur le résultat" in query_text or "impot differe" in query_text or "impôt différé" in query_text or "differences temporelles" in query_text or "différences temporelles" in query_text):
            if record.get("doc_id") == "ias_12_impots_resultat":
                score *= 4.6
        if ("ias 16" in query_text or "immobilisations corporelles" in query_text or "modele de reevaluation" in query_text or "modèle de réévaluation" in query_text or "valeur residuelle" in query_text):
            if record.get("doc_id") == "ias_16_immobilisations_corporelles":
                score *= 4.4
            elif record.get("doc_id") == "nc_05_immobilisations_corporelles":
                score *= 1.8
        if ("ias 17" in query_text or "location-financement" in query_text or "location financement" in query_text or "credit-bail" in query_text):
            if record.get("doc_id") == "ias_17_contrats_location":
                score *= 4.3
            elif record.get("doc_id") in {"nc_41_contrats_location", "ifrs_16_contrats_location"}:
                score *= 1.7
        if ("ias 18" in query_text or "produits des activites ordinaires" in query_text or "produits des activités ordinaires" in query_text or "vente de biens" in query_text or "prestations de services" in query_text):
            if record.get("doc_id") == "ias_18_produits_activites_ordinaires":
                score *= 4.3
            elif record.get("doc_id") in {"nc_03_revenus", "ifrs_15_produits_contrats_clients"}:
                score *= 1.7
        if ("ias 19" in query_text or "avantages du personnel" in query_text or "regimes a prestations definies" in query_text or "régimes à prestations définies" in query_text or "ecarts actuariels" in query_text or "écarts actuariels" in query_text):
            if record.get("doc_id") == "ias_19_avantages_personnel":
                score *= 4.4
        if ("ias 20" in query_text or "subventions publiques" in query_text or "aide publique" in query_text or "aides publiques" in query_text):
            if record.get("doc_id") == "ias_20_subventions_publiques_aide_publique":
                score *= 4.8
            elif record.get("doc_id") == "nc_12_subventions_publiques":
                score *= 1.9
        if "ias 20" in query_text:
            if record.get("doc_id") == "ias_20_subventions_publiques_aide_publique":
                score *= 1.6
            elif record.get("doc_id") == "nc_12_subventions_publiques":
                score *= 0.72
        if ("ias 21" in query_text or "ecarts de change" in query_text or "écarts de change" in query_text or "monnaie fonctionnelle" in query_text or "conversion des etats financiers" in query_text or "conversion des états financiers" in query_text):
            if record.get("doc_id") == "ias_21_variations_cours_monnaies_etrangeres":
                score *= 4.4
            elif record.get("doc_id") == "nc_15_monnaies_etrangeres":
                score *= 1.9
        if ("ias 23" in query_text or "couts d'emprunt" in query_text or "coûts d'emprunt" in query_text or "actif qualifie" in query_text or "actif qualifié" in query_text):
            if record.get("doc_id") == "ias_23_couts_emprunt":
                score *= 4.4
            elif record.get("doc_id") == "nc_13_charges_emprunt":
                score *= 1.9
        if ("ias 24" in query_text or "parties liees" in query_text or "parties liées" in query_text or "transactions entre parties liees" in query_text or "transactions entre parties liées" in query_text):
            if record.get("doc_id") == "ias_24_parties_liees":
                score *= 4.4
            elif record.get("doc_id") == "nc_39_parties_liees":
                score *= 1.9
        if ("ias 26" in query_text or "regimes de retraite" in query_text or "régimes de retraite" in query_text or "rapports financiers des regimes de retraite" in query_text):
            if record.get("doc_id") == "ias_26_regimes_retraite":
                score *= 4.3
        if ("ias 27" in query_text or "etats financiers individuels" in query_text or "états financiers individuels" in query_text):
            if record.get("doc_id") == "ias_27_etats_financiers_individuels":
                score *= 4.3
            elif record.get("doc_id") == "ifrs_10_etats_financiers_consolides":
                score *= 0.85
        if ("ias 28" in query_text or "mise en equivalence" in query_text or "mise en équivalence" in query_text or "entreprises associees" in query_text or "entreprises associées" in query_text):
            if record.get("doc_id") == "ias_28_associees_coentreprises":
                score *= 4.8
            elif record.get("doc_id") in {"nc_36_associees", "nc_37_coentreprises"}:
                score *= 1.9
        if "ias 28" in query_text:
            if record.get("doc_id") == "ias_28_associees_coentreprises":
                score *= 1.45
            elif record.get("doc_id") in {"nc_36_associees", "nc_37_coentreprises"}:
                score *= 0.78
        if ("ias 32" in query_text or "instruments financiers presentation" in query_text or "instruments financiers : presentation" in query_text or "capitaux propres" in query_text and "passif financier" in query_text):
            if record.get("doc_id") == "ias_32_instruments_financiers_presentation":
                score *= 4.4
            elif record.get("doc_id") in {"ifrs_7_instruments_financiers_informations", "ifrs_9_instruments_financiers"}:
                score *= 1.6
        if ("ias 33" in query_text or "resultat par action" in query_text or "résultat par action" in query_text or "eps dilue" in query_text or "eps dilué" in query_text):
            if record.get("doc_id") == "ias_33_resultat_par_action":
                score *= 4.4
        if ("ias 34" in query_text or "information financiere intermediaire" in query_text or "information financière intermédiaire" in query_text or "rapport financier intermediaire" in query_text):
            if record.get("doc_id") == "ias_34_information_financiere_intermediaire":
                score *= 4.4
            elif record.get("doc_id") == "nc_19_etats_financiers_intermediaires":
                score *= 1.9
        if ("ias 36" in query_text or "depreciation d'actifs" in query_text or "dépréciation d'actifs" in query_text or "perte de valeur" in query_text or "valeur recouvrable" in query_text or "unite generatrice de tresorerie" in query_text or "unité génératrice de trésorerie" in query_text):
            if record.get("doc_id") == "ias_36_depreciation_actifs":
                score *= 4.6
            elif record.get("doc_id") in {"nc_05_immobilisations_corporelles", "nc_06_immobilisations_incorporelles", "ifrs_13_juste_valeur"}:
                score *= 1.5
        if ("ias 37" in query_text or "passifs eventuels" in query_text or "passifs éventuels" in query_text or "actifs eventuels" in query_text or "actifs éventuels" in query_text or "contrat deficitaire" in query_text or "contrat déficitaire" in query_text):
            if record.get("doc_id") == "ias_37_provisions_passifs_actifs_eventuels":
                score *= 4.5
            elif record.get("doc_id") == "nc_14_eventualites_post_cloture":
                score *= 1.5
        if ("ias 38" in query_text or "immobilisations incorporelles" in query_text or "actifs incorporels" in query_text or "recherche et developpement" in query_text or "recherche et développement" in query_text):
            if record.get("doc_id") == "ias_38_immobilisations_incorporelles":
                score *= 4.5
            elif record.get("doc_id") == "nc_06_immobilisations_incorporelles":
                score *= 1.9
        if ("ias 39" in query_text or "derive incorpore" in query_text or "dérivé incorporé" in query_text or "instruments financiers comptabilisation et evaluation" in query_text or "instruments financiers : comptabilisation et évaluation" in query_text):
            if record.get("doc_id") == "ias_39_instruments_financiers_comptabilisation_evaluation":
                score *= 4.9
            elif record.get("doc_id") in {"ias_32_instruments_financiers_presentation", "ifrs_7_instruments_financiers_informations", "ifrs_9_instruments_financiers"}:
                score *= 1.7
        if "ias 39" in query_text:
            if record.get("doc_id") == "ias_39_instruments_financiers_comptabilisation_evaluation":
                score *= 1.55
            elif record.get("doc_id") == "ifrs_9_instruments_financiers":
                score *= 0.62
        if ("ias 40" in query_text or "immeubles de placement" in query_text or "modele de la juste valeur" in query_text or "modèle de la juste valeur" in query_text):
            if record.get("doc_id") == "ias_40_immeubles_placement":
                score *= 4.8
            elif record.get("doc_id") == "ifrs_13_juste_valeur":
                score *= 1.6
        if "ias 40" in query_text:
            if record.get("doc_id") == "ias_40_immeubles_placement":
                score *= 1.45
            elif record.get("doc_id") == "ifrs_13_juste_valeur":
                score *= 0.76
        if ("ias 41" in query_text or "actifs biologiques" in query_text or "production agricole" in query_text or "agriculture" in query_text and "ias" in query_text):
            if record.get("doc_id") == "ias_41_agriculture":
                score *= 4.4
        if ("cadre conceptuel" in query_text or "caracteristiques qualitatives" in query_text or "representation fidele" in query_text or "pertinence" in query_text) and ("ifrs" in query_text or "iasb" in query_text or "information financiere" in query_text):
            if record.get("doc_id") == "ifrs_cadre_conceptuel_information_financiere":
                score *= 4.0
            elif record.get("doc_id") == "cadre_conceptuel_comptable":
                score *= 2.2
        if "entreprise assoc" in query_text or "influence notable" in query_text:
            if record.get("doc_id") == "nc_36_associees":
                score *= 4.0
            elif record.get("doc_id") == "droits_taxes_hors_codes":
                score *= 0.15
        if ("consolid" in query_text or "groupe" in query_text) and ("coentreprise" in query_text or "controle conjoint" in query_text or "contrôle conjoint" in query_text):
            if record.get("doc_id") == "nc_37_coentreprises":
                score *= 3.5
        if ("takaful" in query_text or "retakaful" in query_text or "rétakaful" in query_text) and ("controle interne" in query_text or "contrôle interne" in query_text):
            if record.get("doc_id") == "nct_44_takaful_controle_interne":
                score *= 4.0
            elif record.get("doc_id") == "nct_43_takaful_etats_financiers":
                score *= 0.45
        if ("takaful" in query_text or "retakaful" in query_text or "rétakaful" in query_text) and ("etat financier" in query_text or "état financier" in query_text or "etats financiers" in query_text or "états financiers" in query_text or "presentation" in query_text or "présentation" in query_text):
            if record.get("doc_id") == "nct_43_takaful_etats_financiers":
                score *= 4.0
            elif record.get("doc_id") == "nct_44_takaful_controle_interne":
                score *= 0.4
        if ("structure sportive" in query_text or "club sportif" in query_text or "federation sportive" in query_text or "fédération sportive" in query_text):
            if record.get("doc_id") == "nc_40_structures_sportives":
                score *= 4.0
            elif record.get("doc_id") == "loi_comptable":
                score *= 0.3
        if ("association" in query_text or "osbl" in query_text or "organisme sans but lucratif" in query_text or "parti politique" in query_text) and ("etat financier" in query_text or "état financier" in query_text or "etats financiers" in query_text or "états financiers" in query_text):
            if record.get("doc_id") == "nct_45_osbl":
                score *= 4.0
        if ("stagiaire" in query_text or "stage" in query_text or "ترسيم" in query_text or "تربص" in query_text):
            if record.get("doc_id") == "circulaire_stagiaires_2018":
                score *= 4.2
            elif record.get("doc_id") == "formulaire_compte_rendu_stagiaire":
                score *= 3.8
            elif record.get("doc_id") == "guide_inscription_stagiaires_2026":
                score *= 4.6
        if ("stagiaire" in query_text or "stage" in query_text or "ترسيم" in query_text or "تربص" in query_text) and (
            "condition" in query_text or "inscription" in query_text or "validation" in query_text or "duree" in query_text or "durée" in query_text
        ):
            if record.get("doc_id") == "circulaire_stagiaires_2018":
                score *= 5.0
            elif record.get("doc_id") == "formulaire_compte_rendu_stagiaire":
                score *= 0.12
            elif record.get("doc_id") == "guide_inscription_stagiaires_2026":
                score *= 5.2
        if "rapport moral" in query_text or "rapport d'activite" in query_text or "rapport d’activité" in query_text:
            if record.get("doc_id", "").startswith("rapport_moral_"):
                score *= 4.0
            elif record.get("source_tier") == "primary_law":
                score *= 0.25
        if ("commerce" in query_text or "commercant" in query_text or "commerçant" in query_text or "fonds de commerce" in query_text):
            if record.get("doc_id") == "code_commerce_2014":
                score *= 4.0
        if ("tribunal de premiere instance" in query_text or "tribunaux de premiere instance" in query_text or "compétence territoriale" in query_text or "competence territoriale" in query_text):
            if record.get("doc_id") == "tribunaux_premiere_instance_guide":
                score *= 5.0
        if ("cour de cassation" in query_text or "pourvoi en cassation" in query_text or "recours en cassation" in query_text):
            if record.get("doc_id") == "cour_cassation_guide":
                score *= 5.0
        if ("chambres reunies" in query_text or "chambres réunies" in query_text or "terrorisme" in query_text or "juge d'instruction militaire" in query_text):
            if record.get("doc_id") == "cassation_chambres_reunies_terrorisme_2019":
                score *= 5.0
        if ("acte de commerce par accessoire" in query_text or "commercialite par accessoire" in query_text or "commercialité par accessoire" in query_text):
            if record.get("doc_id") == "cassation_acte_commerce_accessoire_2019":
                score *= 5.0
        if ("coc" in query_text or "obligations et contrats" in query_text or "responsabilite civile" in query_text or "responsabilité civile" in query_text):
            if record.get("doc_id") == "code_obligations_contrats_2015":
                score *= 4.0
        if ("sequestre" in query_text or "séquestre" in query_text) and ("societe anonyme" in query_text or "société anonyme" in query_text or "actionnaires" in query_text):
            if record.get("doc_id") == "cassation_sequestre_societe_anonyme_2018":
                score *= 5.0
        if ("arbitrage interne" in query_text or "sentence arbitrale" in query_text or "recours en annulation" in query_text):
            if record.get("doc_id") == "cassation_arbitrage_interne_2018":
                score *= 5.0
        if ("dissolution" in query_text or "affectio societatis" in query_text or "mésintelligence grave entre associés" in query_text or "mesintelligence grave entre associes" in query_text):
            if record.get("doc_id") == "cassation_dissolution_sarl_affectio_2018":
                score *= 5.0
        if ("reglement judiciaire" in query_text or "règlement judiciaire" in query_text or "cotisations complementaires de retraite" in query_text or "cotisations complémentaires de retraite" in query_text):
            if record.get("doc_id") == "cassation_reglement_judiciaire_cotisations_2017":
                score *= 5.0
        if ("participation a un groupe terroriste" in query_text or "participation à un groupe terroriste" in query_text or "element materiel" in query_text or "élément matériel" in query_text or "element moral" in query_text or "élément moral" in query_text):
            if record.get("doc_id") == "cassation_terrorisme_participation_groupe_2017":
                score *= 5.0
        if ("accident de la voie publique" in query_text or "barèmes de responsabilité" in query_text or "baremes de responsabilite" in query_text or "article 123 du code des assurances" in query_text):
            if record.get("doc_id") == "cassation_accident_route_baremes_2017":
                score *= 5.0
        if ("clause compromissoire" in query_text or "promesse de vente" in query_text or "procuration" in query_text):
            if record.get("doc_id") == "cassation_clause_compromissoire_2017":
                score *= 5.0
        if ("cmf" in query_text or "conseil du marche financier" in query_text or "conseil du marché financier" in query_text or "bulletin officiel" in query_text):
            if record.get("doc_id") == "cmf_bulletin_officiel_2017_04_11":
                score *= 5.0
        if ("experts judiciaires" in query_text or "expert judiciaire" in query_text):
            if record.get("doc_id") in {
                "loi_experts_judiciaires_1993",
                "arrete_composition_commission_experts_1993",
                "arrete_delais_inscription_experts_1993",
                "arrete_manuel_procedures_expert_judiciaire_2000",
                "loi_modification_experts_judiciaires_2010",
            }:
                score *= 4.8
        if ("commission regionale" in query_text or "commission régionale" in query_text):
            if record.get("doc_id") == "arrete_composition_commission_experts_1993":
                score *= 5.0
        if ("premiere liste des experts judiciaires" in query_text or "première liste des experts judiciaires" in query_text or "delais d'inscription" in query_text or "délais d'inscription" in query_text):
            if record.get("doc_id") == "arrete_delais_inscription_experts_1993":
                score *= 5.0
        if ("manuel de procedures de l'expert judiciaire" in query_text or "manuel de procédures de l'expert judiciaire" in query_text or ("manuel" in query_text and "procedures" in query_text and "expert judiciaire" in query_text) or ("manuel" in query_text and "procédures" in query_text and "expert judiciaire" in query_text)):
            if record.get("doc_id") == "arrete_manuel_procedures_expert_judiciaire_2000":
                score *= 8.5
            elif record.get("doc_id") == "loi_experts_judiciaires_1993":
                score *= 0.18
        if ("personne morale" in query_text or "personnes morales" in query_text) and ("experts judiciaires" in query_text or "inscription" in query_text):
            if record.get("doc_id") == "loi_modification_experts_judiciaires_2010":
                score *= 6.2
            elif record.get("doc_id") == "arrete_delais_inscription_experts_1993":
                score *= 0.3
        if ("reforme du cursus" in query_text or "réforme du cursus" in query_text or "examen national de revision comptable" in query_text or "examen national de révision comptable" in query_text):
            if record.get("doc_id") == "article_revue_expertise_comptable_2011":
                score *= 4.2
        if ("circulaire bct 2012-02" in query_text or "note d'orientation" in query_text or "note d’orientation" in query_text or "provisions collectives" in query_text):
            if record.get("doc_id") == "note_orientation_bct_2012_02":
                score *= 4.8
        if ("commissaire aux comptes" in query_text or "reviseur des comptes" in query_text or "réviseur des comptes" in query_text or "rapport general" in query_text or "rapport général" in query_text or "rapport special" in query_text or "rapport spécial" in query_text or "certification des comptes" in query_text):
            if record.get("doc_id") in {
                "rapport_cac_ance_2016",
                "rapport_cac_innorpi_2021",
                "rapport_cac_bna_2018",
                "rapport_cac_ote_2014",
                "rapport_cac_cefa_tunisie_2020",
                "rapport_cac_act_2021",
                "rapport_cac_irc_2017",
                "rapport_reviseur_legal_smls_2017",
                "rapport_general_cac_2017",
                "rapport_audit_nebras_2023",
            }:
                score *= 4.6
        if (("anomalie significative" in query_text or "apres l emission de son rapport" in query_text or "apres emission de son rapport" in query_text or "reglementation" in query_text) and ("commissaire aux comptes" in query_text or "rapport" in query_text)):
            if record.get("doc_id") in {
                "audit_resume_gaida_normes_missions",
                "audit_resume_maaloul_audit_financier",
                "audit_resume_acceptation_controle_qualite",
                "audit_resume_chakroun_scan",
            }:
                score *= 4.8
            elif record.get("source_tier") == "audit_report":
                score *= 0.42
        if ("association" in query_text or "ong" in query_text or "audit 2023" in query_text or "nebras" in query_text) and ("rapport" in query_text or "audit" in query_text or "commissaire aux comptes" in query_text):
            if record.get("doc_id") == "rapport_audit_nebras_2023":
                score *= 6.2
            elif record.get("doc_id") == "rapport_cac_act_2021":
                score *= 2.8
        if ("association" in query_text or "ong" in query_text) and "2023" in query_text:
            if record.get("doc_id") == "rapport_audit_nebras_2023":
                score *= 7.0
            elif record.get("source_tier") == "audit_report" and record.get("year") != 2023:
                score *= 0.35
        if ("audit" in query_text or "isa" in query_text or "commissaire aux comptes" in query_text or "controle qualite" in query_text or "contrôle qualité" in query_text):
            if record.get("doc_id") in {
                "audit_resume_gaida_normes_missions",
                "audit_resume_maaloul_audit_financier",
                "audit_resume_acceptation_controle_qualite",
                "audit_resume_chakroun_scan",
                "audit_pratique_moez_chaabeen",
                "audit_controle_qualite_imed_ennouri",
                "cours_audit_chiheb_ghanmi",
                "cours_audit_imed_ennouri",
            }:
                score *= 3.8
        if ("acceptation de la mission" in query_text or "maintien des relations client" in query_text or "isa 220" in query_text or "isqc 1" in query_text):
            if record.get("doc_id") == "audit_resume_acceptation_controle_qualite":
                score *= 4.8
            elif record.get("doc_id") == "audit_controle_qualite_imed_ennouri":
                score *= 3.8
        if ("dossier permanent" in query_text or "dossier annuel" in query_text or "programme de travail" in query_text):
            if record.get("doc_id") == "audit_pratique_moez_chaabeen":
                score *= 4.6
        if ("isa" in query_text or "isre" in query_text or "isrs" in query_text or "ifac" in query_text):
            if record.get("doc_id") == "audit_resume_gaida_normes_missions":
                score *= 4.6
        if ("etablissement de paiement" in query_text or "établissement de paiement" in query_text or "agrement" in query_text or "agrément" in query_text):
            if record.get("doc_id") == "guide_agrement_etablissement_paiement_tunisie":
                score *= 4.8
        if ("appel d'offres" in query_text or "appel d’offres" in query_text or "tunisie autoroutes" in query_text or "cahier des charges" in query_text):
            if record.get("doc_id") == "appel_offres_assurance_tunisie_autoroutes_2026":
                score *= 4.8
        if ("hexabyte" in query_text or "marche alternatif" in query_text or "marché alternatif" in query_text):
            if record.get("doc_id") == "prospectus_hexabyte_2011_2012":
                score *= 4.8
        if ("tunisie leasing" in query_text or "prospectus de fusion" in query_text or ("fusion" in query_text and "leasing" in query_text)):
            if record.get("doc_id") == "prospectus_fusion_tunisie_leasing":
                score *= 4.8
        if ("strategie de l'habitat" in query_text or "stratégie de l'habitat" in query_text or "habitat" in query_text or "logement" in query_text):
            if record.get("doc_id") == "strategie_habitat_tunisie_2015":
                score *= 4.2
        if ("banque mondiale" in query_text or "strategie des transports" in query_text or "stratégie des transports" in query_text):
            if record.get("doc_id") == "banque_mondiale_strategie_transports_tunisie":
                score *= 4.0
        if ("societe anonyme" in query_text or "société anonyme" in query_text or re.search(r"\bsa\b", query_text, re.I)):
            if record.get("doc_id") == "checklist_constitution_sa_api":
                score *= 4.8
        if ("societe" in query_text or "société" in query_text or "sarl" in query_text or "societes commerciales" in query_text or "sociétés commerciales" in query_text):
            if record.get("doc_id") == "code_societes_commerciales_2022":
                score *= 3.8
            if record.get("doc_id") == "guide_inscription_personnes_morales_2026" and ("inscription" in query_text or "guide" in query_text):
                score *= 5.0
        if ("sarl" in query_text or "societe a responsabilite limitee" in query_text or "société à responsabilité limitée" in query_text):
            if record.get("doc_id") == "guide_creation_sarl_tunisie":
                score *= 4.4
        if (
            re.search(r"fermeture d[' ]une entreprise|fermeture d'entreprise|fermeture d entreprise|fermeture entreprise", query_text, re.I)
            or "dissolution" in query_text
            or "liquidation" in query_text
            or "cessation d'activite" in query_text
            or "cessation d'activité" in query_text
        ):
            if record.get("doc_id") == "guide_fermeture_entreprise_tunisie":
                score *= 4.2
            elif record.get("doc_id") == "formulaire_radiation_2026" and ("societe" in query_text or "entreprise" in query_text or "personne morale" in query_text):
                score *= 0.22
        if ("amnistie" in query_text or "réconciliation nationale" in query_text or "reconciliation nationale" in query_text):
            if record.get("doc_id") == "analyse_amnistie_reconciliation_administrative":
                score *= 4.6
        if ("personne physique" in query_text or "personnes physiques" in query_text) and ("inscription" in query_text or "terssim" in query_text or "ترسيم" in query_text):
            if record.get("doc_id") == "guide_inscription_personnes_physiques_2026":
                score *= 5.0
        if ("radiation" in query_text or "شطب" in query_text):
            if record.get("doc_id") == "formulaire_radiation_2026":
                score *= 5.0
        if ("suspension" in query_text or "تعليق" in query_text):
            if record.get("doc_id") == "formulaire_suspension_2026":
                score *= 5.0
        if (re.search(r"attestation d[' ]?inscription|attestation inscription", query_text, re.I) or "شهادة ترسيم" in query_text):
            if record.get("doc_id") == "demande_attestation_inscription_2026":
                score *= 5.0
            elif record.get("source_tier") == "primary_law":
                score *= 0.08
            elif record.get("source_tier") == "form_template":
                score *= 2.2
        if ("inscription" in query_text or "ترسيم" in query_text) and ("personne morale" in query_text or "societe" in query_text or "société" in query_text):
            if record.get("doc_id") == "guide_inscription_personnes_morales_2026":
                score *= 5.0
        if ("inscription" in query_text or "ترسيم" in query_text) and ("personne physique" in query_text or "personnes physiques" in query_text):
            if record.get("doc_id") == "guide_inscription_personnes_physiques_2026":
                score *= 5.0
        if ("inscription" in query_text or "ترسيم" in query_text) and re.search(
            r"attestation|radiation|suspension|personne morale|personnes morales|personne physique|personnes physiques|stagiaire",
            query_text,
            re.I,
        ):
            if record.get("source_tier") == "primary_law":
                score *= 0.18
            elif record.get("source_tier") == "professional_guide":
                score *= 2.1
            elif record.get("source_tier") == "form_template":
                score *= 2.4

        if re.search(
            r"\bfiscal(?:ite)?\b|fiscalit[eé]|impot|impôt|taxe|taxes|\btva\b|irpp|impot sur les societes|impôt sur les sociétés|enregistrement|timbre|procedure fiscale|procédure fiscale|procedures fiscales|procédures fiscales|loi de finances|recouvrement|redressement",
            query_text,
            re.I,
        ):
            if record.get("doc_id") in {
                "code_irpp_is_2011",
                "tva_droit_consommation",
                "procedures_fiscales_2026",
                "enregistrement_timbre",
                "fiscalite_locale",
                "droits_taxes_hors_codes",
                "loi_finances_2026",
                "note_generale_contribution_solidarite_2026",
            }:
                score = (score * 4.6) + 12.0
            elif record.get("doc_id") in {
                "code_commerce_2014",
                "code_obligations_contrats_2015",
                "code_societes_commerciales_2022",
            }:
                score *= 0.03
        if re.search(
            r"\bfiscal(?:ite)?\b|fiscalit[eé]|impot|impôt|taxe|taxes|loi de finances",
            query_text,
            re.I,
        ) and any(
            token in query_text
            for token in ["general", "général", "generalement", "généralement", "ensemble", "principales lois", "cadre fiscal"]
        ):
            if record.get("doc_id") in {
                "code_irpp_is_2011",
                "tva_droit_consommation",
                "procedures_fiscales_2026",
                "enregistrement_timbre",
            }:
                score += 60.0
            elif record.get("doc_id") in {"fiscalite_locale", "droits_taxes_hors_codes"}:
                score *= 0.4
            if record.get("doc_id") == "loi_finances_2026":
                score *= 1.35
            elif record.get("doc_id") == "note_generale_contribution_solidarite_2026":
                score *= 0.82
        if re.search(r"facturation electronique|facture electronique|e-facturation|e facture|e-facture|fou?tur", query_text, re.I):
            if record.get("doc_id") == "note_generale_facturation_electronique_2026":
                score = (score * 5.2) + 28.0
            elif record.get("doc_id") == "tva_droit_consommation":
                score *= 2.0
        if re.search(r"regularisation des dettes fiscales|régularisation des dettes fiscales|dettes fiscales|penalites fiscales|pénalités fiscales|echeancier fiscal|échéancier fiscal|remise des penalites|remise des pénalités", query_text, re.I):
            if record.get("doc_id") == "note_generale_regularisation_dettes_fiscales_2026":
                score = (score * 5.0) + 28.0
            elif record.get("doc_id") == "procedures_fiscales_2026":
                score *= 2.2
            elif record.get("doc_id", "").startswith(("nc_", "ias_", "ifrs_", "nct_")):
                score *= 0.08
        if re.search(r"vehicules hybrides|véhicules hybrides|hybrides rechargeables|voitures hybrides|batteries lithium|bornes de recharge|appareils de charge", query_text, re.I):
            if record.get("doc_id") == "note_generale_fiscalite_vehicules_hybrides_2026":
                score = (score * 7.0) + 54.0
            elif record.get("doc_id") == "droits_taxes_hors_codes":
                score *= 0.52
            elif record.get("doc_id") == "tva_droit_consommation":
                score *= 1.4
        if re.search(r"tunisiens non residents|non residents|non-résidents|non residents.*services administratifs|article 109|services administratifs fiscaux", query_text, re.I):
            if record.get("doc_id") == "note_generale_non_residents_services_administratifs_2026":
                score = (score * 5.0) + 26.0
            elif record.get("doc_id") == "procedures_fiscales_2026":
                score *= 2.0
        if re.search(r"taxe environnementale|protection de l'environnement|protection de l environnement|produits manufactures localement|produits importes|produits importés|mecenvironnement", query_text, re.I):
            if record.get("doc_id") == "note_generale_taxe_environnement_2026":
                score = (score * 8.0) + 96.0
            elif record.get("doc_id") == "droits_taxes_hors_codes":
                score *= 0.55
            elif record.get("doc_id") == "fiscalite_locale":
                score *= 0.35

        if record.get("heading") and re.search(r"article|art\.|chapitre|section|titre|الفصل|باب", record["heading"], re.I):
            score *= 1.1
        if score:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    per_doc_counts: dict[str, int] = {}
    for score, record in scored:
        doc_id = record.get("doc_id") or record["id"]
        if per_doc_counts.get(doc_id, 0) >= 2:
            continue
        results.append({
            "id": record["id"],
            "doc_id": record.get("doc_id"),
            "title": record["title"],
            "filename": record["filename"],
            "page": record["page"],
            "heading": record.get("heading", ""),
            "excerpt": record["text"][:1400],
            "source_tier": record.get("source_tier", ""),
            "authority": record.get("authority", ""),
            "year": record.get("year"),
            "score": round(score, 3),
        })
        per_doc_counts[doc_id] = per_doc_counts.get(doc_id, 0) + 1
        if len(results) >= limit:
            break
    return results
