import json
import math
import re
from functools import lru_cache
from pathlib import Path


CORPUS_PATH = Path(__file__).with_name("data") / "tunisian_legal_corpus.jsonl"
STOPWORDS = {
    "avec", "aux", "ces", "dans", "des", "du", "elle", "elles", "est", "etre",
    "être", "les", "leur", "leurs", "par", "pas", "pour", "que", "qui", "sur",
    "une", "vous", "the", "and", "or", "من", "في", "على", "إلى", "عن", "ما",
}


def tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9']{3,}|[\u0600-\u06FF]{2,}", value.lower())
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
        "tva_droit_consommation": r"\btva\b|taxe sur la valeur ajout|valeur ajoutee|valeur ajoutée|droit de consommation|assujetti|deduction|déduction|exoner|exonér|restitution de la taxe",
        "enregistrement_timbre": r"enregistrement|timbre|mutation|acte|donation|succession|bail|vente immobili",
        "fiscalite_locale": r"fiscalite locale|fiscalité locale|taxe sur les immeubles|tcl|collectivite|collectivité|commune|municipal",
        "loi_comptable": r"loi comptable|systeme comptable|système comptable|normes comptables|etats financiers|états financiers",
        "cadre_conceptuel_comptable": r"cadre conceptuel|qualitative|hypothese sous-jacente|hypothèse sous-jacente|information financiere|information financière",
        "droits_taxes_hors_codes": r"taxes non incorporees|taxes non incorporées|circulation|voyage|assurance|telecommunication|télécommunication|hotel|hôtel",
        "nc_01_norme_generale": r"\bnc 01\b|norme comptable generale|norme comptable générale|presentation des etats financiers|présentation des états financiers|organisation comptable",
        "nc_02_capitaux_propres": r"\bnc 02\b|capitaux propres|reserve|réserve|dividende|resultat reporte|résultat reporté",
        "nc_03_revenus": r"\bnc 03\b|revenus|produits|prestations de services|vente de biens|interets|intérêts|redevances",
        "nc_04_stocks": r"\bnc 04\b|stocks|cout d'acquisition|coût d'acquisition|cout de production|coût de production|depreciation des stocks|dépréciation des stocks",
        "nc_05_immobilisations_corporelles": r"\bnc 05\b|immobilisations corporelles|amortissement|valeur residuelle|valeur résiduelle|depreciation|dépréciation",
        "nc_06_immobilisations_incorporelles": r"\bnc 06\b|immobilisations incorporelles|actifs incorporels|logiciel|fonds commercial|recherche et developpement|recherche et développement",
        "nc_07_placements": r"\bnc 07\b|placements|titres|portefeuille|placement a court terme|placement à court terme|placement a long terme|placement à long terme",
        "nc_08_resultat_net": r"\bnc 08\b|resultat net|résultat net|element extraordinaire|élément extraordinaire|activites ordinaires|activités ordinaires|performance",
        "nc_09_contrats_construction": r"\bnc 09\b|contrats de construction|avancement|pourcentage d'avancement|pourcentage d’avancement|chantier|maitre d'ouvrage|maître d'ouvrage",
        "nc_10_charges_reportees": r"\bnc 10\b|charges reportees|charges reportées|frais preliminaires|frais préliminaires|frais d'emission|frais d’émission|report de charges",
        "nc_11_modifications_comptables": r"\bnc 11\b|modifications comptables|changement de methode|changement de méthode|correction d'erreur|correction d’erreur|estimation comptable",
        "nc_12_subventions_publiques": r"\bnc 12\b|subventions publiques|aides publiques|subvention d'investissement|subvention d’exploitation|subvention d'exploitation|prime d'investissement|aide de l'etat|aide de l'état",
        "nc_13_charges_emprunt": r"\bnc 13\b|charges d'emprunt|charges d’emprunt|cout d'emprunt|coût d'emprunt|interets intercalaires|intérêts intercalaires",
        "nc_14_eventualites_post_cloture": r"\bnc 14\b|eventualites|éventualités|evenements posterieurs|événements postérieurs|date de cloture|date de clôture|passif eventuel|passif éventuel",
        "nc_15_monnaies_etrangeres": r"\bnc 15\b|monnaies etrangeres|monnaies étrangères|ecart de change|écart de change|difference de change|différence de change|taux de change|devise",
        "nc_16_opcvm_etats_financiers": r"\bnc 16\b|opcvm|sicav|fcp|presentation des etats financiers des opcvm|présentation des états financiers des opcvm|valeur liquidative",
        "nc_17_opcvm_portefeuille_titres": r"\bnc 17\b|portefeuille-titres|portefeuille titres|operations des opcvm|opérations des opcvm|cours boursier|seuil de reservation|seuil de réservation",
        "nc_18_opcvm_controle_interne": r"\bnc 18\b|controle interne des opcvm|contrôle interne des opcvm|organisation comptable des opcvm|sicav|gerant du fcp|gérant du fcp",
        "nc_19_etats_financiers_intermediaires": r"\bnc 19\b|etats financiers intermediaires|états financiers intermédiaires|information intermediaire|information intermédiaire|periode intermediaire|période intermédiaire",
        "nc_20_recherche_developpement": r"\bnc 20\b|recherche et developpement|recherche et développement|frais de recherche|frais de developpement|frais de développement",
        "nc_21_bancaire_etats_financiers": r"\bnc 21\b|etats financiers des etablissements bancaires|états financiers des établissements bancaires|bilan bancaire|produit bancaire|etablissement bancaire|établissement bancaire",
        "nc_22_bancaire_controle_interne": r"\bnc 22\b|controle interne bancaire|contrôle interne bancaire|organisation comptable bancaire|etablissement bancaire|établissement bancaire|conformite bancaire|conformité bancaire",
        "nc_23_bancaire_devises": r"\bnc 23\b|operations en devises|opérations en devises|comptabilite multi-devises|comptabilité multi-devises|cours de change interbancaire|banque centrale de tunisie",
        "nc_24_bancaire_engagements_revenus": r"\bnc 24\b|engagements bancaires|engagement de garantie|engagement de financement|credits documentaires|crédits documentaires|prets et avances|prêts et avances",
        "nc_25_bancaire_portefeuille_titres": r"\bnc 25\b|portefeuille-titres bancaire|portefeuille titres bancaire|titres a revenu fixe|titres à revenu fixe|titres a revenu variable|titres à revenu variable|banque portefeuille titres",
        "nc_27_assurance_controle_interne": r"\bnc 27\b|controle interne assurance|contrôle interne assurance|organisation comptable assurance|reassurance|réassurance|entreprise d'assurance|entreprise d’assurances",
        "nc_28_assurance_revenus": r"\bnc 28\b|revenus assurance|revenus reassurance|revenus réassurance|prime pure|prime d'assurance|taxes d'assurance|chargements",
        "nc_29_assurance_provisions_techniques": r"\bnc 29\b|provisions techniques|provision mathematique|provision mathématique|provision pour sinistres|participation aux benefices|participation aux bénéfices|assurance provision",
        "nc_30_assurance_charges_techniques": r"\bnc 30\b|charges techniques|sinistres|ristournes|participation aux benefices|participation aux bénéfices|charges assurance",
        "nc_31_assurance_placements": r"\bnc 31\b|placements assurance|placements reassurance|placements réassurance|passif reglemente|passif réglementé|couverture des engagements|juste valeur placement",
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
        pattern = domain_boosts.get(record.get("doc_id", ""))
        if pattern and re.search(pattern, query_text, re.I):
            score *= 2.8
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
            "score": round(score, 3),
        })
    return results
