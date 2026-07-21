from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "data" / "tunisian_doctrine_core_100.jsonl"


def case(
    idx: int,
    family: str,
    question: str,
    workflow: str,
    contains: list[str],
    forbidden: list[str] | None = None,
) -> dict:
    return {
        "id": f"doctrine_core_{idx:03d}_{family}",
        "question": question,
        "language": "francais",
        "expected_intent": "legal_basis" if "tva" in family or "cdpf" in family or "facturation" in family else "accounting_treatment",
        "expected_preferred_source": "legal_corpus",
        "expected_response_style": "practical_analysis",
        "expected_workflow": workflow,
        "expected_sections": ["Reponse", "Application pratique", "Points de vigilance", "Sources utilisees"],
        "expected_answer_contains": contains,
        "forbidden_answer_contains": forbidden
        or [
            "En premiere analyse, le point doit etre rattache principalement au cadre suivant",
            "We need to",
            "rewrite answer",
            "article [X]",
            "source implicite",
        ],
    }


def build_cases() -> list[dict]:
    rows: list[dict] = []
    idx = 1

    broad_tva = [
        "Quelles sont les regles generales de TVA en Tunisie pour un cabinet comptable ?",
        "Donnez-moi le cadre general de la taxe sur la valeur ajoutee en Tunisie.",
        "Quelles lois et regles structurent la TVA tunisienne ?",
        "Expliquez la TVA en Tunisie: champ, territorialite, exigibilite, deduction et facturation.",
        "Pour un client tunisien, quelles sont les grandes obligations TVA a verifier ?",
        "Quelles sont les principales regles TVA sans entrer dans un cas particulier ?",
        "Presentation cabinet: comment analyser la TVA tunisienne en general ?",
        "Quels points TVA un expert-comptable doit-il controler en Tunisie ?",
        "Quelles sources et controles TVA faut-il verifier avant une declaration ?",
        "Resume professionnel du regime TVA tunisien.",
    ]
    for q in broad_tva:
        rows.append(case(idx, "tva_general", q, "fastpath", ["champ", "territorialite", "exigibilite", "deduction", "facturation", "declaration"]))
        idx += 1

    tva_services = [
        "Une societe tunisienne facture une prestation informatique a un client francais assujetti. Quel traitement TVA verifier ?",
        "Une prestation de conseil est realisee depuis la Tunisie pour un client italien. Quels justificatifs TVA garder ?",
        "Un client francais non assujetti achete une formation realisee en partie en France. Peut-on traiter comme export de services ?",
        "Une societe tunisienne encaisse une avance avant la fin d'une prestation de services. Quand analyser l'exigibilite TVA ?",
        "Le service est utilise en Tunisie par une societe etrangere. Quel risque TVA ?",
        "Une facture de service a l'etranger n'a aucun justificatif du lieu d'utilisation. Quelle conclusion prudente ?",
        "Prestation realisee en Tunisie et exploitee en Allemagne: quels points TVA controler ?",
        "Licence logiciel facturee a un client etranger: TVA service ou redevance, que verifier ?",
        "Formation realisee physiquement a Paris par des consultants tunisiens: quelle analyse TVA et facturation ?",
        "Service B2B export avec paiement partiel avant achevement: comment separer TVA et produit comptable ?",
    ]
    for q in tva_services:
        rows.append(case(idx, "tva_services", q, "tva_operational_case", ["tva", "client", "utilisation", "facturation", "justificatifs"]))
        idx += 1

    receivables = [
        ("Une societe a une creance client de 180 000 TND impayee depuis 14 mois. Elle recouvre 30 000 TND apres cloture. Quel traitement ?", ["180 000", "30 000", "150 000", "provision", "fiscal"]),
        ("Client en retard: facture de 250 000 TND, relances envoyees, paiement partiel de 40 000 TND apres cloture. Que provisionner ?", ["250 000", "40 000", "210 000", "relances", "fiscal"]),
        ("Une creance de 95 000 TND reste impayee 9 mois, aucune action de recouvrement. Peut-on deduire fiscalement la provision ?", ["95 000", "recouvrement", "deduction", "reserve"]),
        ("Creance client impayee sans justificatifs ni relances: quelle position comptable et fiscale prudente ?", ["creance", "provision", "justificatifs", "fiscal"]),
        ("Une creance douteuse est partiellement encaissee apres la cloture. Comment traiter l'evenement posterieur ?", ["encaissement", "cloture", "provision", "documentation"]),
        ("Une societe veut passer en perte definitive une creance seulement douteuse. Que verifier ?", ["douteuse", "perte", "justificatifs", "fiscal"]),
        ("Balance agee: client A doit 120 000 TND et regle 20 000 TND apres cloture. Quel solde a risque ?", ["120 000", "20 000", "100 000"]),
        ("Provision globale sur plusieurs clients sans detail individuel: est-ce suffisant pour un dossier fiscal ?", ["client", "individual", "fiscal", "reserve"]),
        ("Creance de 300 000 TND avec action judiciaire engagee et recuperation de 75 000 TND: comment conclure ?", ["300 000", "75 000", "225 000", "action"]),
        ("Un client conteste une facture, paie une partie apres cloture et le solde reste incertain. Quel traitement cabinet ?", ["encaissement", "solde", "provision", "fiscal"]),
    ]
    for q, contains in receivables:
        rows.append(case(idx, "creances_douteuses", q, "receivable_impairment_subsequent_event", contains))
        idx += 1

    dividends = [
        "Une SARL distribue des dividendes a une personne physique residente, une societe tunisienne et un non-resident. Comment analyser ?",
        "Benefices distribues a un actionnaire non resident etabli en France: que verifier avant paiement ?",
        "Revenus distribues a trois associes avec profils differents: retenue, declaration et certificat ?",
        "Dividendes verses sans certificat de residence du beneficiaire etranger: quelle reserve ?",
        "Une societe tunisienne distribue 600 000 TND: 300 000 a une personne physique, 200 000 a une societe, 100 000 a un non-resident.",
        "Peut-on appliquer un taux de retenue aux dividendes sans passage direct du Code IRPP/IS ?",
        "Distribution de benefices 2026: quelles pieces declaratives et attestations preparer ?",
        "Actionnaire residant en Allemagne recoit des dividendes tunisiens: quelle convention verifier ?",
        "Dividendes a une societe mere tunisienne: que verifier fiscalement et societairement ?",
        "Dividendes a associe resident et non-resident sans pays precise: quelle conclusion prudente ?",
    ]
    for q in dividends:
        rows.append(case(idx, "dividends", q, "shareholder_split_tax_analysis", ["beneficiaire", "retenue", "declaration", "certificat"]))
        idx += 1

    depreciation = [
        ("Machine achetee le 15 septembre 2025, livree le 20 septembre, installee le 10 octobre et prete a fonctionner le 15 octobre 2025. Quand commence l'amortissement ?", ["15 octobre 2025", "amortissement", "base", "fiscal"]),
        ("Equipement livre avant cloture mais tests termines apres cloture: peut-on amortir avant qu'il soit pret ?", ["pret", "tests", "amortissement"]),
        ("Actif pret a fonctionner le 1er novembre 2025 mais facture recue le 10 novembre. Quelle date comptable retenir ?", ["1er novembre 2025", "facture", "pret"]),
        ("Machine avec composant majeur remplace tous les 3 ans: comment traiter les composants ?", ["composant", "3 ans", "base"]),
        ("Vehicule de tourisme: distinguer amortissement comptable et limites fiscales.", ["vehicule", "comptable", "fiscal"]),
        ("Licence logiciel pluriannuelle: activation, amortissement et fiscalite ?", ["licence", "logiciel", "amortissement"]),
        ("Immobilisation achetee mais non installee a la cloture: quelle position prudente ?", ["installee", "pret", "cloture"]),
        ("Une machine est disponible pour utilisation avant la livraison administrative finale. Quelle documentation obtenir ?", ["disponible", "mise en service", "documentation"]),
        ("Base amortissable d'une immobilisation: quels elements inclure ou exclure ?", ["base amortissable", "cout", "fiscal"]),
        ("Goodwill cree en interne par reputation commerciale: peut-on l'activer et l'amortir ?", ["goodwill", "interne", "amortissement"]),
    ]
    for q, contains in depreciation:
        workflow = "goodwill_accounting_case" if "Goodwill" in q else "fixed_asset_depreciation_case"
        rows.append(case(idx, "amortissement", q, workflow, contains))
        idx += 1

    facturation = [
        "Quelles sont les mentions obligatoires d'une facture en Tunisie ?",
        "Une facture sans identite claire du client permet-elle la deduction TVA ?",
        "Comment controler la numerotation des factures dans un cabinet ?",
        "Facturation electronique 2026: quels points verifier sans inventer la date d'entree ?",
        "Facture de prestation avec TVA: que doivent contenir base HT, taux, TVA et TTC ?",
        "Une facture existe mais pas de contrat: que conclure sur justificatifs ?",
        "Contrat existe mais aucune facture: quel impact comptable/fiscal ?",
        "Quelles pieces conserver pour une facture de service export ?",
        "Facture en especes pour consulting: quelles preuves complementaires demander ?",
        "Facture rectificative: quels controles fiscaux et comptables ?",
    ]
    for q in facturation:
        rows.append(case(idx, "facturation", q, "tax_electronic_invoice_compliance_case", ["facture", "client", "tva", "conservation"]))
        idx += 1

    procedure = [
        "Quel est le role du Code des droits et procedures fiscaux ?",
        "Controle fiscal: quelles etapes et quels documents verifier ?",
        "Regularisation d'une dette fiscale ancienne: quelle demarche prudente ?",
        "Redressement fiscal: difference entre base imposable, penalites et recours ?",
        "Quelles reserves si le delai exact n'est pas supporte par un passage direct ?",
        "Comment traiter une notification fiscale recue par le client ?",
        "Demande de certificat fiscal: quelles pieces verifier ?",
        "Procedure de reclamation fiscale: que peut dire l'assistant sans article direct ?",
        "Contentieux fiscal: quels points orienter vers verification officielle ?",
        "Penalites fiscales: pourquoi ne pas inventer de taux ?",
    ]
    for q in procedure:
        rows.append(case(idx, "cdpf", q, "tax_procedure_compliance_case", ["procedure", "controle", "recours", "source"]))
        idx += 1

    standards = [
        "Quand peut-on utiliser IAS/IFRS pour repondre a une societe tunisienne ?",
        "Pour une PME tunisienne, IAS 16 peut-elle remplacer NC 05 ?",
        "Une question d'immobilisation en Tunisie doit-elle citer d'abord les normes tunisiennes ?",
        "Goodwill acquis: comment distinguer referentiel tunisien et IFRS ?",
        "IAS 37 suffit-elle pour justifier une provision fiscale tunisienne ?",
        "Quand IFRS peut etre presente comme comparaison seulement ?",
        "Si NC tunisienne existe et IFRS existe aussi, quelle source prioriser ?",
        "Une societe cotee demande un traitement IFRS: comment formuler la reserve ?",
        "Une SARL tunisienne ordinaire demande un traitement comptable: quel referentiel par defaut ?",
        "Comment eviter d'utiliser IAS/IFRS comme source primaire non justifiee ?",
    ]
    for q in standards:
        rows.append(case(idx, "standards_hierarchy", q, "accounting_closing_estimate_case", ["tunisien", "ifrs", "source", "reserve"]))
        idx += 1

    missing_fact = [
        "Un client dit avoir exporte un service mais ne fournit pas le pays, le statut du client ni preuve d'utilisation. Peut-on conclure TVA ?",
        "Une provision est demandee sans montant, sans client identifie et sans relances. Quelle reponse prudente ?",
        "Dividendes a un non-resident sans pays ni certificat de residence: peut-on appliquer une convention ?",
        "Machine achetee mais aucune date de mise en service n'est donnee. Peut-on fixer le debut d'amortissement ?",
        "Facture de consulting sans contrat ni rapport de mission, paiement cash: deductibilite confirmee ?",
        "Regularisation fiscale: le client ne donne ni periode ni notification. Peut-on calculer penalites ?",
        "Goodwill sans acquisition identifiee: peut-on comptabiliser ?",
        "TVA deduction sans facture originale: que doit repondre le cabinet ?",
        "Creance douteuse sans action de recouvrement ni justificatifs: expert_pass ou reserve ?",
        "CAC signale fraude mais sans date de decouverte ni materialite: quelle limite dans la reponse ?",
    ]
    workflows = [
        "tva_operational_case",
        "receivable_impairment_subsequent_event",
        "shareholder_split_tax_analysis",
        "fixed_asset_depreciation_case",
        "expense_deductibility_evidence_case",
        "tax_procedure_compliance_case",
        "goodwill_accounting_case",
        "tva_operational_case",
        "receivable_impairment_subsequent_event",
        "audit_cac_response_case",
    ]
    for q, workflow in zip(missing_fact, workflows):
        rows.append(case(idx, "missing_fact", q, workflow, ["reserve", "documents", "conclure"]))
        idx += 1

    hardchecks = [
        ("Contrat de maintenance du 1er decembre 2025 au 30 novembre 2026, paye en decembre 2025, cloture 31 decembre 2025. Quel cut-off ?", "revenue_cutoff_tva_case", ["1/12", "11/12", "produit constate"]),
        ("Contrat de service du 1er juillet 2025 au 30 juin 2026, facture d'avance, cloture 31 decembre 2025. Quel prorata ?", "revenue_cutoff_tva_case", ["6/12", "produit constate"]),
        ("Contrat du 1er janvier 2026 au 31 decembre 2026 paye en decembre 2025. Produit 2025 ?", "revenue_cutoff_tva_case", ["0/12", "12/12"]),
        ("Creance de 180 000 TND avec paiement de 30 000 TND apres cloture et 14 mois de retard.", "receivable_impairment_subsequent_event", ["180 000", "30 000", "150 000"]),
        ("Creance de 250 000 TND, paiement de 40 000 TND apres cloture, 9 mois de retard.", "receivable_impairment_subsequent_event", ["250 000", "40 000", "210 000"]),
        ("Machine prete a fonctionner le 15 octobre 2025 apres achat et installation. Date d'amortissement ?", "fixed_asset_depreciation_case", ["15 octobre 2025", "amortissement"]),
        ("Equipement pret a fonctionner le 1er novembre 2025, facture le 10 novembre. Date comptable ?", "fixed_asset_depreciation_case", ["1er novembre 2025", "amortissement"]),
        ("Quels textes/regles TVA generaux: ne donnez pas seulement les noms des codes.", "fastpath", ["champ", "territorialite", "exigibilite", "deduction", "facturation"]),
        ("Pour une societe tunisienne ordinaire, peut-on utiliser IAS comme source primaire ?", "accounting_closing_estimate_case", ["tunisien", "ifrs", "reserve"]),
        ("Service B2B France partiellement execute en Tunisie, encaissement partiel avant achevement.", "level3_multi_domain_case_analysis", ["tva", "facturation", "justificatifs"]),
    ]
    for q, workflow, contains in hardchecks:
        rows.append(case(idx, "final_answer_hardcheck", q, workflow, contains))
        idx += 1

    assert len(rows) == 100, len(rows)
    return rows


def main() -> None:
    rows = build_cases()
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} doctrine cases to {OUTPUT}")


if __name__ == "__main__":
    main()

