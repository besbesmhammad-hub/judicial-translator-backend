import re

ACTIVE_SKILLS = [
    "server-document-parsing",
    "document-type-classification",
    "adaptive-routing",
    "layout-aware-parsing",
    "legal-rag",
    "judicial-translation-prompt",
    "long-document-chunking",
    "tunisian-finance-law",
]

ROUTE_PRESETS = {
    "legal": {
        "profile": "auto-legal-specialist",
        "label": "judicial / legal / contract",
        "rules": [
            "Use strict formal legal Arabic when translating to Arabic.",
            "Preserve liability, obligation, reservation, causality and procedural logic.",
            "Preserve article, clause, court, party, expert and exhibit references exactly.",
            "Do not turn party observations into established facts.",
        ],
    },
    "financial": {
        "profile": "auto-financial-specialist",
        "label": "invoice / accounting / finance",
        "rules": [
            "Preserve all numbers, currencies, percentages, tax labels, HT/TTC/TVA and accounting periods exactly.",
            "Use precise accounting terminology.",
            "Never invert debtor/creditor, debit/credit, assets/liabilities or paid/unpaid meaning.",
        ],
    },
    "tunisianFinance": {
        "profile": "auto-tunisian-finance-law-specialist",
        "label": "Tunisian finance / tax / customs / public accounting law",
        "rules": [
            "Use Tunisian official legal-financial terminology in Arabic and French.",
            "Preserve law numbers, article references, fiscal years, rates, amounts, declarations, deadlines and exemptions exactly.",
            "Prefer Tunisian terms: TVA = الأداء على القيمة المضافة, IRPP = الضريبة على دخل الأشخاص الطبيعيين, IS = الضريبة على الشركات.",
            "Prefer public finance terms: loi de finances = قانون المالية, comptabilité publique = المحاسبة العمومية, recouvrement = الاستخلاص.",
            "Prefer customs terms: code des douanes = مجلة الديوانة, droits de douane = المعاليم الديوانية, tarif douanier = التعريفة الديوانية.",
            "Do not replace Tunisian terminology with Moroccan, Egyptian, Gulf or generic French-law terminology.",
            "If no official source context is retrieved, translate faithfully and do not claim that a legal rule is current.",
        ],
    },
    "technical": {
        "profile": "auto-technical-specialist",
        "label": "technical / engineering / software",
        "rules": [
            "Preserve commands, file paths, API names, product names, identifiers and units.",
            "Use precise technical Arabic/French terminology.",
            "Do not simplify technical statements into general language.",
        ],
    },
    "medical": {
        "profile": "auto-medical-specialist",
        "label": "medical / clinical",
        "rules": [
            "Use precise clinical terminology.",
            "Do not add medical advice or interpretation absent from the document.",
            "Preserve dosage, dates, measurements and diagnosis wording exactly.",
        ],
    },
    "administrative": {
        "profile": "auto-administrative-specialist",
        "label": "administrative / diplomatic / international organization",
        "rules": [
            "Use formal administrative Arabic suitable for international organizations.",
            "Preserve country names, member-state lists, delegation references, session numbers and committee recommendations.",
            "Do not classify country lists, member states, delegations, conferences or committee reports as finance.",
            "Translate names consistently and keep numbering exactly.",
        ],
    },
    "presentation": {
        "profile": "auto-presentation-specialist",
        "label": "presentation / training / educational slide document",
        "rules": [
            "Treat the content as slide or training material, not as a legal or financial document unless explicit legal/financial terms dominate.",
            "Preserve slide/page order, titles, module names, learning objectives, action items and calls to action.",
            "Keep the translated style natural, concise and human, suitable for presentation pages.",
            "Do not add invoice, tax, accounting, judicial or official terminology when the source is educational or coaching content.",
        ],
    },
    "general": {
        "profile": "auto-general-specialist",
        "label": "general / mixed",
        "rules": [
            "Use fluent professional language.",
            "Do not force legal, accounting or technical terminology when not supported by context.",
            "Preserve structure and translate completely.",
        ],
    },
}

LEGAL_KNOWLEDGE = [
    {
        "id": "tribunal",
        "match": re.compile(r"tribunal|cour d'appel|juridiction|court|appeal", re.I),
        "source": "tribunal / cour d'appel / juridiction",
        "target": "mahkama / mahkamat al-istinaf / jiha qadaiya",
        "guidance": "Preserve the exact type of court or jurisdiction.",
        "routes": {"legal"},
    },
    {
        "id": "expert-judiciaire",
        "match": re.compile(r"expert judiciaire|expertise judiciaire|rapport d'expertise|judicial expert", re.I),
        "source": "expert judiciaire / rapport d'expertise",
        "target": "khabir qadai / taqrir khibra qadaiya",
        "guidance": "Distinguish mission, findings, analysis, party observations and conclusions.",
        "routes": {"legal"},
    },
    {
        "id": "contrat",
        "match": re.compile(r"contrat|convention|clause|avenant|article|obligation|contract|agreement", re.I),
        "source": "contrat, clause, article, obligation",
        "target": "aqd, band, mada, iltizam",
        "guidance": "Preserve numbering and legal scope of obligations.",
        "routes": {"legal"},
    },
    {
        "id": "responsabilite-prejudice",
        "match": re.compile(r"responsabilite|prejudice|dommage|indemnisation|faute|causalite|liability|damage", re.I),
        "source": "responsabilite, prejudice, dommage, causalite",
        "target": "masouliya, darar, taawid, alaqa sababiyya",
        "guidance": "Respect nuances between fact, fault, damage, prejudice and causal link.",
        "routes": {"legal"},
    },
    {
        "id": "expertise-comptable",
        "match": re.compile(r"expertise comptable|comptable|bilan|grand livre|compte de resultat|accounting", re.I),
        "source": "expertise comptable, bilan, grand livre",
        "target": "khibra muhasabiyya, mizaniya, daftar al-ustadh",
        "guidance": "Keep accounting periods, ledgers and references exact.",
        "routes": {"legal", "financial"},
    },
    {
        "id": "tax-amounts",
        "match": re.compile(r"facture|tva|ht|ttc|montant|devise|pourcentage|invoice|vat|amount|currency", re.I),
        "source": "facture, TVA, HT, TTC, montant",
        "target": "fatoura, TVA, without tax, including tax, amount",
        "guidance": "Preserve all amounts, currencies, percentages, tax labels and invoice references exactly.",
        "routes": {"financial", "legal"},
    },
    {
        "id": "tn-loi-finances",
        "match": re.compile(r"tunisie|tunisien|tunisienne|loi de finances|loi de finances complémentaire|budget de l'etat|budget de l’état|ميزانية الدولة|قانون المالية", re.I),
        "source": "loi de finances, budget de l'Etat, loi de finances complémentaire",
        "target": "قانون المالية، ميزانية الدولة، قانون المالية التكميلي",
        "guidance": "Use Tunisian official terms and preserve fiscal year, articles, rates and amounts exactly.",
        "routes": {"tunisianFinance"},
    },
    {
        "id": "tn-tax",
        "match": re.compile(r"tva|taxe sur la valeur ajoutée|irpp|impôt sur le revenu|is|impôt sur les sociétés|droit de consommation|retenue à la source|retenue a la source|droits d'enregistrement|timbre|exonération|assiette|déduction|تصريح جبائي|الأداء على القيمة المضافة|الضريبة على الشركات|الخصم من المورد", re.I),
        "source": "TVA, IRPP, IS, droit de consommation, retenue a la source, droits d'enregistrement et de timbre",
        "target": "الأداء على القيمة المضافة، الضريبة على دخل الأشخاص الطبيعيين، الضريبة على الشركات، معلوم الاستهلاك، الخصم من المورد، معاليم التسجيل والطابع الجبائي",
        "guidance": "Translate as Tunisian tax law; preserve rates, base, exemptions, deductions, declarations and deadlines exactly.",
        "routes": {"tunisianFinance"},
    },
    {
        "id": "tn-customs",
        "match": re.compile(r"douane|douanier|code des douanes|droits de douane|tarif douanier|valeur en douane|origine des marchandises|déclaration en détail|ديوانة|مجلة الديوانة|المعاليم الديوانية|التعريفة الديوانية", re.I),
        "source": "code des douanes, droits de douane, tarif douanier, valeur en douane, origine des marchandises",
        "target": "مجلة الديوانة، المعاليم الديوانية، التعريفة الديوانية، القيمة لدى الديوانة، منشأ البضائع",
        "guidance": "Use Tunisian customs terminology and preserve tariff, origin, nomenclature and restrictions.",
        "routes": {"tunisianFinance"},
    },
    {
        "id": "tn-public-accounting",
        "match": re.compile(r"comptabilité publique|comptabilite publique|recouvrement|créance publique|ordonnateur|comptable public|trésor public|tresor public|code de la comptabilité publique|المحاسبة العمومية|الاستخلاص|آمر بالصرف|محاسب عمومي|الخزينة", re.I),
        "source": "comptabilité publique, recouvrement, ordonnateur, comptable public, Trésor public",
        "target": "المحاسبة العمومية، الاستخلاص، آمر بالصرف، محاسب عمومي، الخزينة العامة",
        "guidance": "Use Tunisian public finance terminology; never invert ordonnateur/comptable public or debt/recovery.",
        "routes": {"tunisianFinance"},
    },
    {
        "id": "creance",
        "match": re.compile(r"creance|debiteur|creancier|paiement|solde|impaye|debt|debtor|creditor", re.I),
        "source": "creance, debiteur, creancier, solde",
        "target": "dayn, madin, dain, rasid",
        "guidance": "Never invert debtor and creditor.",
        "routes": {"financial", "legal"},
    },
    {
        "id": "technical",
        "match": re.compile(r"api|serveur|logiciel|configuration|installation|database|endpoint|server|software", re.I),
        "source": "API, serveur, logiciel, configuration",
        "target": "API, khadim, barnamaj, idadat",
        "guidance": "Keep identifiers, commands, paths, product names and units.",
        "routes": {"technical"},
    },
    {
        "id": "medical",
        "match": re.compile(r"patient|diagnostic|traitement|ordonnance medicale|medecin|clinical|medical", re.I),
        "source": "patient, diagnostic, traitement",
        "target": "marid, tashkhis, ilaj",
        "guidance": "Translate clinically without adding medical advice.",
        "routes": {"medical"},
    },
    {
        "id": "international-organization",
        "match": re.compile(r"etats membres|états membres|delegations|délégations|conference generale|conférence générale|comite|comité|session|member states|general conference|committee", re.I),
        "source": "Etats membres, delegations, conference generale, comite, session",
        "target": "الدول الأعضاء، الوفود، المؤتمر العام، اللجنة، الدورة",
        "guidance": "Use formal international administrative style and preserve session/recommendation numbering.",
        "routes": {"administrative"},
    },
    {
        "id": "country-list",
        "match": re.compile(r"bahrein|bahrain|bangladesh|barbade|belgique|benin|bresil|brésil|canada|chine|france|maroc|mali|palau|panama|pays-bas|perou|pérou|royaume-uni|yemen|zambie|zimbabwe", re.I),
        "source": "liste d'Etats / pays",
        "target": "قائمة الدول / البلدان",
        "guidance": "Translate country names without adding financial or legal terminology.",
        "routes": {"administrative"},
    },
]


def detect_language(text: str) -> str:
    arabic = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", text))
    latin = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
    return "arabe" if arabic > latin else "francais"


def detect_document_kind(text: str) -> str:
    route = choose_route(text, "")
    return {
        "legal": "judicial / legal / contract document",
        "financial": "invoice / accounting / finance document",
        "tunisianFinance": "Tunisian finance law / tax / customs / public accounting document",
        "technical": "technical / engineering / software document",
        "medical": "medical / clinical document",
        "administrative": "administrative / international organization document",
        "presentation": "presentation / training / educational slide document",
        "general": "general / mixed document",
    }[route]


def choose_route(text: str, document_kind: str) -> str:
    sample = f"{document_kind}\n{text}".lower()
    if re.search(r"\[(?:page|slide) \d+\]|powerpoint|presentation|slide deck|diapositive|module|formation|training|workshop|webinaire|course|coaching|learning objective|objectif|exercice|appel a l'action|call to action|حقيبة تدريبية|دقيبة تدريبية|تدريبية|الوحدة|الهدف|التحول|تمرين|المهارات|الكفاءات|المراهق|التربوي|الشاشات|الباك|سجل الآن", sample):
        return "presentation"
    if re.search(r"tunisie|tunisien|tunisienne|loi de finances|code des douanes|comptabilité publique|comptabilite publique|recouvrement|irpp|impôt sur les sociétés|droits de douane|retenue à la source|retenue a la source|droits d'enregistrement|droit de consommation|قانون المالية|ميزانية الدولة|ديوانة|مجلة الديوانة|المحاسبة العمومية|الأداء على القيمة المضافة|الضريبة على الشركات", sample):
        return "tunisianFinance"
    if re.search(r"etats membres|états membres|delegations|délégations|conference generale|conférence générale|comite|comité|session|member states|general conference|committee|recommande la commission|recommande le comite", sample):
        return "administrative"
    if re.search(r"tribunal|court|cour d'appel|expert judiciaire|jugement|ordonnance|contrat|clause|article|prejudice|responsabilite|liability|contract", sample):
        return "legal"
    if re.search(r"\bbilan\b|\bgrand livre\b|\bfacture\b|\btva\b|\bht\b|\bttc\b|\bdebit\b|\bcredit\b|\bcreance\b|\bdebiteur\b|\bcreancier\b|\binvoice\b|\bvat\b|\bbalance sheet\b|\baccounting\b", sample):
        return "financial"
    if re.search(r"patient|diagnostic|traitement|medecin|clinical|medical|dosage", sample):
        return "medical"
    if re.search(r"api|serveur|logiciel|configuration|database|endpoint|server|software|engineering|technical", sample):
        return "technical"
    return "general"


def choose_skill_profile(text: str, document_kind: str) -> str:
    return ROUTE_PRESETS[choose_route(text, document_kind)]["profile"]


def retrieve_terms(text: str, document_kind: str, route: str | None = None) -> list[dict]:
    selected_route = route or choose_route(text, document_kind)
    haystack = f"{document_kind}\n{text}"
    matches = [
        item for item in LEGAL_KNOWLEDGE
        if selected_route in item["routes"] and item["match"].search(haystack)
    ]
    if not matches:
        matches = [item for item in LEGAL_KNOWLEDGE if selected_route in item["routes"]]
    if not matches:
        matches = LEGAL_KNOWLEDGE[:3]
    return [
        {
            "id": item["id"],
            "source": item["source"],
            "target": item["target"],
            "guidance": item["guidance"],
        }
        for item in matches[:12]
    ]
