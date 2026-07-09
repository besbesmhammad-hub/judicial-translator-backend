import json
import math
import re
from functools import lru_cache
from pathlib import Path


CORPUS_PATH = Path(__file__).with_name("data") / "tunisian_legal_corpus.jsonl"
STOPWORDS = {
    "avec", "aux", "ces", "dans", "des", "du", "elle", "elles", "est", "etre",
    "Ãªtre", "les", "leur", "leurs", "par", "pas", "pour", "que", "qui", "sur",
    "une", "vous", "the", "and", "or", "Ù…Ù†", "ÙÙŠ", "Ø¹Ù„Ù‰", "Ø¥Ù„Ù‰", "Ø¹Ù†", "Ù…Ø§",
}
SOURCE_TIER_WEIGHTS = {
    "primary_law": 1.12,
    "accounting_standard": 1.08,
    "professional_text_collection": 0.93,
    "professional_circular": 0.86,
    "form_template": 0.60,
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
        "tva_droit_consommation": r"\btva\b|taxe sur la valeur ajout|valeur ajoutee|valeur ajoutÃ©e|droit de consommation|assujetti|deduction|dÃ©duction|exoner|exonÃ©r|restitution de la taxe",
        "enregistrement_timbre": r"enregistrement|timbre|mutation|acte|donation|succession|bail|vente immobili",
        "fiscalite_locale": r"fiscalite locale|fiscalitÃ© locale|taxe sur les immeubles|tcl|collectivite|collectivitÃ©|commune|municipal",
        "loi_comptable": r"loi comptable|systeme comptable|systÃ¨me comptable|normes comptables|etats financiers|Ã©tats financiers",
        "cadre_conceptuel_comptable": r"cadre conceptuel|qualitative|hypothese sous-jacente|hypothÃ¨se sous-jacente|information financiere|information financiÃ¨re",
        "droits_taxes_hors_codes": r"taxes non incorporees|taxes non incorporÃ©es|circulation|voyage|assurance|telecommunication|tÃ©lÃ©communication|hotel|hÃ´tel",
        "nc_01_norme_generale": r"\bnc 01\b|norme comptable generale|norme comptable gÃ©nÃ©rale|presentation des etats financiers|prÃ©sentation des Ã©tats financiers|organisation comptable",
        "nc_02_capitaux_propres": r"\bnc 02\b|capitaux propres|reserve|rÃ©serve|dividende|resultat reporte|rÃ©sultat reportÃ©",
        "nc_03_revenus": r"\bnc 03\b|revenus|produits|prestations de services|vente de biens|interets|intÃ©rÃªts|redevances",
        "nc_04_stocks": r"\bnc 04\b|stocks|cout d'acquisition|coÃ»t d'acquisition|cout de production|coÃ»t de production|depreciation des stocks|dÃ©prÃ©ciation des stocks",
        "nc_05_immobilisations_corporelles": r"\bnc 05\b|immobilisations corporelles|amortissement|valeur residuelle|valeur rÃ©siduelle|depreciation|dÃ©prÃ©ciation",
        "nc_06_immobilisations_incorporelles": r"\bnc 06\b|immobilisations incorporelles|actifs incorporels|logiciel|fonds commercial|recherche et developpement|recherche et dÃ©veloppement",
        "nc_07_placements": r"\bnc 07\b|placements|titres|portefeuille|placement a court terme|placement Ã  court terme|placement a long terme|placement Ã  long terme",
        "nc_08_resultat_net": r"\bnc 08\b|resultat net|rÃ©sultat net|element extraordinaire|Ã©lÃ©ment extraordinaire|activites ordinaires|activitÃ©s ordinaires|performance",
        "nc_09_contrats_construction": r"\bnc 09\b|contrats de construction|avancement|pourcentage d'avancement|pourcentage dâ€™avancement|chantier|maitre d'ouvrage|maÃ®tre d'ouvrage",
        "nc_10_charges_reportees": r"\bnc 10\b|charges reportees|charges reportÃ©es|frais preliminaires|frais prÃ©liminaires|frais d'emission|frais dâ€™Ã©mission|report de charges",
        "nc_11_modifications_comptables": r"\bnc 11\b|modifications comptables|changement de methode|changement de mÃ©thode|correction d'erreur|correction dâ€™erreur|estimation comptable",
        "nc_12_subventions_publiques": r"\bnc 12\b|subventions publiques|aides publiques|subvention d'investissement|subvention dâ€™exploitation|subvention d'exploitation|prime d'investissement|aide de l'etat|aide de l'Ã©tat",
        "nc_13_charges_emprunt": r"\bnc 13\b|charges d'emprunt|charges dâ€™emprunt|cout d'emprunt|coÃ»t d'emprunt|interets intercalaires|intÃ©rÃªts intercalaires",
        "nc_14_eventualites_post_cloture": r"\bnc 14\b|eventualites|Ã©ventualitÃ©s|evenements posterieurs|Ã©vÃ©nements postÃ©rieurs|date de cloture|date de clÃ´ture|passif eventuel|passif Ã©ventuel",
        "nc_15_monnaies_etrangeres": r"\bnc 15\b|monnaies etrangeres|monnaies Ã©trangÃ¨res|ecart de change|Ã©cart de change|difference de change|diffÃ©rence de change|taux de change|devise",
        "nc_16_opcvm_etats_financiers": r"\bnc 16\b|opcvm|sicav|fcp|presentation des etats financiers des opcvm|prÃ©sentation des Ã©tats financiers des opcvm|valeur liquidative",
        "nc_17_opcvm_portefeuille_titres": r"\bnc 17\b|portefeuille-titres|portefeuille titres|operations des opcvm|opÃ©rations des opcvm|cours boursier|seuil de reservation|seuil de rÃ©servation",
        "nc_18_opcvm_controle_interne": r"\bnc 18\b|controle interne des opcvm|contrÃ´le interne des opcvm|organisation comptable des opcvm|sicav|gerant du fcp|gÃ©rant du fcp",
        "nc_19_etats_financiers_intermediaires": r"\bnc 19\b|etats financiers intermediaires|Ã©tats financiers intermÃ©diaires|information intermediaire|information intermÃ©diaire|periode intermediaire|pÃ©riode intermÃ©diaire",
        "nc_20_recherche_developpement": r"\bnc 20\b|recherche et developpement|recherche et dÃ©veloppement|frais de recherche|frais de developpement|frais de dÃ©veloppement",
        "nc_21_bancaire_etats_financiers": r"\bnc 21\b|etats financiers des etablissements bancaires|Ã©tats financiers des Ã©tablissements bancaires|bilan bancaire|produit bancaire|etablissement bancaire|Ã©tablissement bancaire",
        "nc_22_bancaire_controle_interne": r"\bnc 22\b|controle interne bancaire|contrÃ´le interne bancaire|organisation comptable bancaire|etablissement bancaire|Ã©tablissement bancaire|conformite bancaire|conformitÃ© bancaire",
        "nc_23_bancaire_devises": r"\bnc 23\b|operations en devises|opÃ©rations en devises|comptabilite multi-devises|comptabilitÃ© multi-devises|cours de change interbancaire|banque centrale de tunisie",
        "nc_24_bancaire_engagements_revenus": r"\bnc 24\b|engagements bancaires|engagement de garantie|engagement de financement|credits documentaires|crÃ©dits documentaires|prets et avances|prÃªts et avances",
        "nc_25_bancaire_portefeuille_titres": r"\bnc 25\b|portefeuille-titres bancaire|portefeuille titres bancaire|titres a revenu fixe|titres Ã  revenu fixe|titres a revenu variable|titres Ã  revenu variable|banque portefeuille titres",
        "nc_27_assurance_controle_interne": r"\bnc 27\b|controle interne assurance|contrÃ´le interne assurance|organisation comptable assurance|reassurance|rÃ©assurance|entreprise d'assurance|entreprise dâ€™assurances",
        "nc_28_assurance_revenus": r"\bnc 28\b|revenus assurance|revenus reassurance|revenus rÃ©assurance|prime pure|prime d'assurance|taxes d'assurance|chargements",
        "nc_29_assurance_provisions_techniques": r"\bnc 29\b|provisions techniques|provision mathematique|provision mathÃ©matique|provision pour sinistres|participation aux benefices|participation aux bÃ©nÃ©fices|assurance provision",
        "nc_30_assurance_charges_techniques": r"\bnc 30\b|charges techniques|sinistres|ristournes|participation aux benefices|participation aux bÃ©nÃ©fices|charges assurance",
        "nc_31_assurance_placements": r"\bnc 31\b|placements assurance|placements reassurance|placements rÃ©assurance|passif reglemente|passif rÃ©glementÃ©|couverture des engagements|juste valeur placement",
        "nc_32_microcredit_etats_financiers": r"\bnc 32\b|micro-credits|micro crÃ©dits|microcrÃ©dits|etats financiers des associations|Ã©tats financiers des associations|association autorisee|association autorisÃ©e",
        "nc_33_microcredit_controle_interne": r"\bnc 33\b|controle interne micro-credit|contrÃ´le interne micro-crÃ©dit|organisation comptable micro-credit|organisation comptable micro-crÃ©dit|association de micro-credit|association de micro-crÃ©dit",
        "nc_34_microcredit_revenus": r"\bnc 34\b|micro-credits et revenus y afferents|micro-crÃ©dits et revenus y affÃ©rents|evaluation des micro-credits|Ã©valuation des micro-crÃ©dits|revenus micro-credit|revenus micro-crÃ©dit",
        "nc_35_consolidation": r"\bnc 35\b|etats financiers consolides|Ã©tats financiers consolidÃ©s|consolidation|entreprise mere|entreprise mÃ¨re|groupe d'entreprises",
        "nc_36_associees": r"\bnc 36\b|entreprises associees|entreprises associÃ©es|influence notable|mise en equivalence|mise en Ã©quivalence",
        "nc_37_coentreprises": r"\bnc 37\b|coentreprises|entite controlee conjointement|entitÃ© contrÃ´lÃ©e conjointement|activites controlees conjointement|activitÃ©s contrÃ´lÃ©es conjointement|controle conjoint|contrÃ´le conjoint",
        "nc_38_regroupements_entreprises": r"\bnc 38\b|regroupements d'entreprises|regroupement d'entreprises|fusion|acquisition d'une entreprise|acquisition dâ€™une entreprise|goodwill|ecart d'acquisition|Ã©cart dâ€™acquisition",
        "nc_39_parties_liees": r"\bnc 39\b|parties liees|parties liÃ©es|transactions entre parties liees|transactions entre parties liÃ©es|societe mere|sociÃ©tÃ© mÃ¨re|filiale liÃ©e",
        "nc_40_structures_sportives": r"\bnc 40\b|structures sportives privees|structures sportives privÃ©es|federation sportive|fÃ©dÃ©ration sportive|association sportive|club sportif",
        "nc_41_contrats_location": r"\bnc 41\b|contrats de location|location-financement|location financement|credit-bail|crÃ©dit-bail|location simple|preneur|bailleur",
        "nc_42_comptabilite_simplifiee": r"\bnc 42\b|comptabilite simplifiee|comptabilitÃ© simplifiÃ©e|petite entreprise|regime simplifie|rÃ©gime simplifiÃ©",
        "nct_43_takaful_etats_financiers": r"\bnct 43\b|takaful|retakaful|rÃ©takaful|etats financiers takaful|Ã©tats financiers takaful|commission wakala|moudharaba",
        "nct_44_takaful_controle_interne": r"\bnct 44\b|controle interne takaful|contrÃ´le interne takaful|organisation comptable takaful|retakaful|rÃ©takaful|operateur du fonds|opÃ©rateur du fonds",
        "nct_45_osbl": r"\bnct 45\b|organismes sans but lucratif|osbl|associations|partis politiques|organisme sans but lucratif|fonds associatif",
        "textes_profession_comptable_2018": r"expert-comptable|experts-comptables|comptable|compagnie des comptables|ordre des experts comptables|commissaire aux comptes|commissariat aux comptes|مراقبي الحسابات|الخبراء المحاسبين|المحاسبين",
        "circulaire_stagiaires_2018": r"stagiaire|stagiaires|stage|compte rendu de stage|controleur de stage|maitre de stage|ترسيم|تربص",
        "formulaire_compte_rendu_stagiaire": r"compte rendu d'activite|compte rendu d’activit|formulaire|stage|stagiaire|controleur de stage|maitre de stage",
        "rapport_moral_2023": r"rapport moral|rapport d'activite|rapport d’activite|conseil national|compagnie des comptables",
        "rapport_moral_2024": r"rapport moral|rapport d'activite|rapport d’activite|conseil national|compagnie des comptables",
        "rapport_moral_2025": r"rapport moral|rapport d'activite|rapport d’activite|conseil national|compagnie des comptables",
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
            r"rapport moral|rapport d'activite|rapport d’activite|conseil national|ordre des experts|compagnie des comptables|cct",
            query_text,
            re.I,
        ):
            score *= 0.18
        if record.get("source_tier") == "form_template" and not re.search(
            r"formulaire|compte rendu|stagiaire|stage|controleur de stage|maitre de stage",
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
        if "subvention" in query_text or "aide publique" in query_text or "aides publiques" in query_text:
            if record.get("doc_id") == "nc_12_subventions_publiques":
                score *= 4.0
            elif record.get("doc_id") == "tva_droit_consommation" and "tva" not in query_text:
                score *= 0.35
        if "opcvm" in query_text and ("controle interne" in query_text or "contrÃ´le interne" in query_text):
            if record.get("doc_id") == "nc_18_opcvm_controle_interne":
                score *= 4.0
            elif record.get("doc_id") == "nc_16_opcvm_etats_financiers":
                score *= 0.45
        if ("assurance" in query_text or "rÃ©assurance" in query_text or "reassurance" in query_text) and ("controle interne" in query_text or "contrÃ´le interne" in query_text):
            if record.get("doc_id") == "nc_27_assurance_controle_interne":
                score *= 4.0
        if ("assurance" in query_text or "rÃ©assurance" in query_text or "reassurance" in query_text) and "revenu" in query_text:
            if record.get("doc_id") == "nc_28_assurance_revenus":
                score *= 4.0
            elif record.get("doc_id") == "droits_taxes_hors_codes":
                score *= 0.25
        if ("assurance" in query_text or "rÃ©assurance" in query_text or "reassurance" in query_text) and "placement" in query_text:
            if record.get("doc_id") == "nc_31_assurance_placements":
                score *= 4.0
            elif record.get("doc_id") in {"droits_taxes_hors_codes", "nc_07_placements"}:
                score *= 0.35
        if ("banque" in query_text or "bancaire" in query_text) and "portefeuille" in query_text:
            if record.get("doc_id") == "nc_25_bancaire_portefeuille_titres":
                score *= 3.5
        if ("micro-credit" in query_text or "micro credit" in query_text or "microcrÃ©dit" in query_text or "microcredits" in query_text or "micro-crÃ©dits" in query_text) and ("controle interne" in query_text or "contrÃ´le interne" in query_text):
            if record.get("doc_id") == "nc_33_microcredit_controle_interne":
                score *= 4.0
            elif record.get("doc_id") == "nc_32_microcredit_etats_financiers":
                score *= 0.45
        if ("micro-credit" in query_text or "micro credit" in query_text or "microcrÃ©dit" in query_text or "microcredits" in query_text or "micro-crÃ©dits" in query_text) and ("etat financier" in query_text or "Ã©tat financier" in query_text or "etats financiers" in query_text or "Ã©tats financiers" in query_text or "presentation" in query_text or "prÃ©sentation" in query_text):
            if record.get("doc_id") == "nc_32_microcredit_etats_financiers":
                score *= 4.0
            elif record.get("doc_id") == "nc_33_microcredit_controle_interne":
                score *= 0.4
        if ("micro-credit" in query_text or "micro credit" in query_text or "microcrÃ©dit" in query_text or "microcredits" in query_text or "micro-crÃ©dits" in query_text) and "revenu" in query_text:
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
        if ("consolid" in query_text or "groupe" in query_text) and ("coentreprise" in query_text or "controle conjoint" in query_text or "contrÃ´le conjoint" in query_text):
            if record.get("doc_id") == "nc_37_coentreprises":
                score *= 3.5
        if ("takaful" in query_text or "retakaful" in query_text or "rÃ©takaful" in query_text) and ("controle interne" in query_text or "contrÃ´le interne" in query_text):
            if record.get("doc_id") == "nct_44_takaful_controle_interne":
                score *= 4.0
            elif record.get("doc_id") == "nct_43_takaful_etats_financiers":
                score *= 0.45
        if ("takaful" in query_text or "retakaful" in query_text or "rÃ©takaful" in query_text) and ("etat financier" in query_text or "Ã©tat financier" in query_text or "etats financiers" in query_text or "Ã©tats financiers" in query_text or "presentation" in query_text or "prÃ©sentation" in query_text):
            if record.get("doc_id") == "nct_43_takaful_etats_financiers":
                score *= 4.0
            elif record.get("doc_id") == "nct_44_takaful_controle_interne":
                score *= 0.4
        if ("structure sportive" in query_text or "club sportif" in query_text or "federation sportive" in query_text or "fÃ©dÃ©ration sportive" in query_text):
            if record.get("doc_id") == "nc_40_structures_sportives":
                score *= 4.0
            elif record.get("doc_id") == "loi_comptable":
                score *= 0.3
        if ("association" in query_text or "osbl" in query_text or "organisme sans but lucratif" in query_text or "parti politique" in query_text) and ("etat financier" in query_text or "Ã©tat financier" in query_text or "etats financiers" in query_text or "Ã©tats financiers" in query_text):
            if record.get("doc_id") == "nct_45_osbl":
                score *= 4.0
        if ("stagiaire" in query_text or "stage" in query_text or "ترسيم" in query_text or "تربص" in query_text):
            if record.get("doc_id") == "circulaire_stagiaires_2018":
                score *= 4.2
            elif record.get("doc_id") == "formulaire_compte_rendu_stagiaire":
                score *= 3.8
        if ("stagiaire" in query_text or "stage" in query_text or "ترسيم" in query_text or "تربص" in query_text) and (
            "condition" in query_text or "inscription" in query_text or "validation" in query_text or "duree" in query_text or "durée" in query_text
        ):
            if record.get("doc_id") == "circulaire_stagiaires_2018":
                score *= 5.0
            elif record.get("doc_id") == "formulaire_compte_rendu_stagiaire":
                score *= 0.12
        if "rapport moral" in query_text or "rapport d'activite" in query_text or "rapport d’activite" in query_text:
            if record.get("doc_id", "").startswith("rapport_moral_"):
                score *= 4.0
            elif record.get("source_tier") == "primary_law":
                score *= 0.25
        if record.get("heading") and re.search(r"article|art\.|chapitre|section|titre", record["heading"], re.I):
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
