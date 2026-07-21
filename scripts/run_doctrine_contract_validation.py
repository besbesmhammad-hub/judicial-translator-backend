from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ENABLE_KEYLESS_FALLBACKS", "false")
os.environ.setdefault("LLM_PROVIDER_TIMEOUT", "4")
os.environ.setdefault("LLM_PROVIDER_RETRIES", "1")

from app.main import app


DEFAULT_OUTPUT = ROOT / "reports" / "doctrine_contract_all_workflows_local.json"


PROBES = (
    ("tva_general_framework", "Donnez-moi les lois de TVA en Tunisie generalement."),
    ("tva_services_exigibility", "Une societe tunisienne facture un service informatique a un client francais assujetti, utilise en France. Quel traitement TVA et quels justificatifs ?"),
    ("tva_deduction", "Une societe veut deduire la TVA d'une facture d'achat sans original. Que faut-il verifier ?"),
    ("facturation_tunisia", "Quelles mentions et quels controles faut-il verifier sur une facture tunisienne et pour sa conservation ?"),
    ("doubtful_debt_provision", "Une creance de 180 000 TND est impayee depuis 14 mois et 30 000 TND sont encaisses apres cloture. Quel traitement comptable et fiscal ?"),
    ("revenue_cutoff", "Contrat du 1er juillet 2025 au 30 juin 2026 facture d'avance, cloture le 31 decembre 2025. Quel produit et quel produit constate d'avance ?"),
    ("expense_evidence", "Facture de consulting de 80 000 TND, sans contrat ni livrable et payee en especes: peut-on valider la deduction ?"),
    ("dividends_withholding", "Une SARL distribue des dividendes a une personne physique residente, une societe tunisienne et un associe non-resident. Quel traitement ?"),
    ("fixed_asset_depreciation", "Machine achetee le 15 septembre 2025, livree le 20 septembre, installee le 10 octobre et prete a fonctionner le 15 octobre 2025. Quand commence l'amortissement ?"),
    ("irpp_is_framework", "Expliquez le cadre IRPP et IS en Tunisie, assiette, charges, retenues et declarations."),
    ("fiscal_framework_tunisia", "Quelles sont les principales lois de fiscalite en Tunisie generalement ?"),
    ("cdpf_procedure", "Comment le CDPF encadre-t-il controle fiscal, redressement, penalites et recours ?"),
    ("registration_stamp", "Une societe vend un immeuble. Quels controles d'enregistrement, timbre, TVA et comptabilite faut-il faire ?"),
    ("local_taxation", "Quels controles de fiscalite locale une entreprise tunisienne doit-elle effectuer pour un immeuble et son activite ?"),
    ("cnss_social", "Un employeur recrute un salarie. Quelles verifications CNSS, assiette, declaration et pieces faut-il effectuer ?"),
    ("audit_cac", "Le CAC decouvre une fraude significative avant son rapport et la direction refuse de corriger. Que doit-il faire ?"),
    ("standards_hierarchy_tunisia", "Pour une societe tunisienne ordinaire, faut-il appliquer d'abord les normes tunisiennes ou IAS/IFRS ?"),
    ("goodwill_accounting", "Une societe veut comptabiliser un goodwill genere en interne, sans acquisition. Quel traitement selon le referentiel applicable ?"),
)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    probes = PROBES[: args.limit or None]
    client = TestClient(app)
    results = []
    counts = {"expert_pass": 0, "safe_pass": 0, "fail": 0, "error": 0}

    for expected_card, question in probes:
        started = time.time()
        try:
            response = client.post(
                "/v1/accounting-chat",
                json={"message": question, "language": "francais", "history": [], "debug": True},
                timeout=120,
            )
            data = response.json()
            answer = data.get("answer") or ""
            debug = data.get("debug_trace") or {}
            card_ids = [row.get("doctrine_id") for row in debug.get("doctrine_cards") or []]
            no_visible_control = "controle doctrine" not in normalize(answer)
            expected_card_selected = expected_card in card_ids
            validation_pass = bool(debug.get("doctrine_validation_pass"))
            if response.status_code != 200 or not no_visible_control:
                status = "fail"
            elif expected_card_selected and validation_pass:
                status = "expert_pass"
            else:
                status = "safe_pass"
            counts[status] += 1
            results.append(
                {
                    "expected_doctrine_card": expected_card,
                    "question": question,
                    "status": status,
                    "http_status": response.status_code,
                    "workflow": debug.get("workflow"),
                    "doctrine_cards": card_ids,
                    "expected_card_selected": expected_card_selected,
                    "doctrine_validation_pass": validation_pass,
                    "doctrine_regenerated": bool(debug.get("doctrine_regenerated")),
                    "missing_elements_before": debug.get("doctrine_missing_elements_before") or [],
                    "missing_elements": debug.get("doctrine_missing_elements") or [],
                    "source_support_gaps": debug.get("doctrine_source_support_gaps") or [],
                    "visible_control_hidden": no_visible_control,
                    "quality_status": data.get("quality_status"),
                    "latency_ms": round((time.time() - started) * 1000, 1),
                    "answer": answer,
                }
            )
        except Exception as exc:
            counts["error"] += 1
            results.append(
                {
                    "expected_doctrine_card": expected_card,
                    "question": question,
                    "status": "error",
                    "error": repr(exc),
                    "latency_ms": round((time.time() - started) * 1000, 1),
                }
            )

    payload = {
        "total": len(results),
        "counts": counts,
        "regenerated_count": sum(1 for row in results if row.get("doctrine_regenerated")),
        "safe_pass_count": counts["safe_pass"],
        "visible_control_hidden_count": sum(1 for row in results if row.get("visible_control_hidden")),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ["total", "counts", "regenerated_count", "safe_pass_count", "visible_control_hidden_count"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
