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
    "accounting_standard": 1.08,
    "professional_text_collection": 0.93,
    "professional_circular": 0.86,
    "professional_guide": 0.78,
    "professional_guidance": 0.82,
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
}


def tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zÀ-ÿ']{3,}|[\u0600-\u06FF]{2,}", value.lower())
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


def retrieve_legal_context(query: str, limit: int = 5) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    corpus = load_corpus()
    if not corpus:
        return []

    query_counts: dict[str, int] = {}
    for token in query_tokens:
        query_counts[token] = query_counts.get(token, 0) + 1
    total_docs = len(corpus)
    doc_freq: dict[str, int] = {}
    for token in query_counts:
        doc_freq[token] = sum(1 for record in corpus if token in set(record["_tokens"]))

    query_text = query.lower()
    domain_boosts = {
        "tva_droit_consommation": r"\btva\b|taxe sur la valeur ajout|valeur ajoutee|droit de consommation|assujetti|deduction|deductions|exoner|restitution de la taxe",
        "enregistrement_timbre": r"enregistrement|timbre|mutation|acte|donation|succession|bail|vente immobili",
        "fiscalite_locale": r"fiscalite locale|taxe sur les immeubles|tcl|collectivite|commune|municipal",
        "loi_comptable": r"loi comptable|systeme comptable|normes comptables|etats financiers",
        "cadre_conceptuel_comptable": r"cadre conceptuel|qualitative|hypothese sous-jacente|information financiere",
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
        if record.get("source_tier") == "professional_guidance" and not re.search(
            r"note d'orientation|note d’orientation|circulaire bct|provisions collectives|rapport special|rapport spécial|commissaire aux comptes|etablissement de credit|établissement de crédit",
            query_text,
            re.I,
        ):
            score *= 0.24
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

        if record.get("heading") and re.search(r"article|art\.|chapitre|section|titre|الفصل|باب", record["heading"], re.I):
            score *= 1.1
        if score:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, record in scored[:limit]:
        results.append({
            "id": record["id"],
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
    return results
