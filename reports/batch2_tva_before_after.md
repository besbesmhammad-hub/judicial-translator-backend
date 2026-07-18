# Batch 2 TVA - Before / After

| Case | Before | After | Sources movement |
|---|---|---|---|
| tva_services_client_france | workflow=tva_operational_case safe=True expert=True source=True | workflow=tva_operational_case safe=True expert=True source=True | tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage); convention_fiscale_france_tunisie_texte_1973 p.8 (direct_passage); boi_france_tunisie_convention_fiscale_2012 p.4 (direct_passage) -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| level2_tva_services_france_sources_tva | workflow=tva_operational_case safe=False expert=False source=True | workflow=tva_operational_case safe=True expert=True source=True | tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage); convention_fiscale_france_tunisie_texte_1973 p.8 (direct_passage); boi_france_tunisie_convention_fiscale_2012 p.4 (direct_passage) -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| level2_tva_services_client_francais_non_assujetti | workflow=level3_multi_domain_case_analysis safe=False expert=False source=True | workflow=tva_operational_case safe=True expert=True source=True | tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); code_irpp_is_2025 p.89 (direct_passage); loi_finances_2026 p.6 (direct_passage); convention_fiscale_france_tunisie p.4 (direct_passage) -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| level2_user_tva_prestation_informatique_france_assujetti | workflow=level3_multi_domain_case_analysis safe=False expert=False source=True | workflow=tva_operational_case safe=True expert=True source=True | tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); code_irpp_is_2025 p.89 (direct_passage); loi_finances_2026 p.6 (direct_passage); convention_fiscale_france_tunisie p.4 (direct_passage) -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_france_b2b_assujetti | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_france_b2c_non_assujetti | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_service_used_tunisia | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_service_used_abroad | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_training_physically_france | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_partly_tunisia_partly_abroad | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_no_foreign_client_proof | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |
| batch2_tva_invoice_no_export_justification | new | workflow=tva_operational_case safe=True expert=True source=True | new case -> tva_droit_consommation p.14 (direct_passage); procedures_fiscales_2026 p.1 (framework_source); loi_finances_2026 p.6 (direct_passage) |

## Answer Previews

### tva_services_client_france

Question: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?

Before:

## Reponse
Ce dossier releve de la famille cabinet suivante: TVA: territorialite, deduction, facturation et regularisation. Faits transmis: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- qualifier l'operation, le lieu d'utilisation et le statut du client
- separer champ d'application, territorialite, exonération, exigibilite et droit a deduction
- verifier les mentions de fa

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur ajoutee. Le statut B2B/B2C du client n'est pas completement documente: il faut obtenir son identite, son pays d'etablissement et,

### level2_tva_services_france_sources_tva

Question: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?

Before:

## Reponse
Ce dossier releve de la famille cabinet suivante: TVA: territorialite, deduction, facturation et regularisation. Faits transmis: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?. La reponse doit etre construite comme une analyse de cabinet: qualifier les faits, separer les issues, rattacher chaque conclusion aux sources disponibles et reserver explicitement les points sans passage direct.

## Application pratique
Issues a traiter:
- qualifier l'operation, le lieu d'utilisation et le statut du client
- separer champ d'application, territorialite, exonération, exigibilite et droit a deduction
- verifier les mentions de fa

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe vend des prestations de services a un client etabli en France. Quel est le regime TVA applicable ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur ajoutee. Le statut B2B/B2C du client n'est pas completement documente: il faut obtenir son identite, son pays d'etablissement et,

### level2_tva_services_client_francais_non_assujetti

Question: Une societe tunisienne fournit une prestation informatique a un client francais non assujetti a la TVA. Quel regime TVA faut il verifier ?

Before:

## Reponse
Ce dossier doit etre traite comme une analyse fiscale transfrontaliere multi-issues, et non comme une simple question IRPP/IS. Les faits transmis doivent etre qualifies sans les remplacer par un cas standard: Une societe tunisienne fournit une prestation informatique a un client francais non assujetti a la TVA. Quel regime TVA faut il verifier ?. L'analyse doit separer au minimum la TVA tunisienne, la retenue a la source ou le risque d'imposition sur le paiement transfrontalier, la convention fiscale France-Tunisie, le risque d'etablissement stable, la facturation et les justificatifs.

## Application pratique
- TVA: verifier dans le Code de la taxe sur la valeur ajoutee si la pre

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe tunisienne fournit une prestation informatique a un client francais non assujetti a la TVA. Quel regime TVA faut il verifier ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur ajoutee. Le client non-assujetti doit etre analyse specifiquement: ne pas reprendre mecaniquement la 

### level2_user_tva_prestation_informatique_france_assujetti

Question: Une societe tunisienne fournit une prestation informatique a une societe etablie en France. Le client est assujetti a la TVA dans son pays. Quel est le regime TVA applicable en Tunisie ? Quelles dispositions legales doivent etre examinees ?

Before:

## Reponse
Ce dossier doit etre traite comme une analyse fiscale transfrontaliere multi-issues, et non comme une simple question IRPP/IS. Les faits transmis doivent etre qualifies sans les remplacer par un cas standard: Une societe tunisienne fournit une prestation informatique a une societe etablie en France. Le client est assujetti a la TVA dans son pays. Quel est le regime TVA applicable en Tunisie ? Quelles dispositions legales doivent etre examinees ?. L'analyse doit separer au minimum la TVA tunisienne, la retenue a la source ou le risque d'imposition sur le paiement transfrontalier, la convention fiscale France-Tunisie, le risque d'etablissement stable, la facturation et les justifica

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe tunisienne fournit une prestation informatique a une societe etablie en France. Le client est assujetti a la TVA dans son pays. Quel est le regime TVA applicable en Tunisie ? Quelles dispositions legales doivent etre examinees ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur

### batch2_tva_france_b2b_assujetti

Question: Une societe tunisienne facture une prestation de conseil informatique a une societe francaise assujettie a la TVA. Le service est utilise en France. Quel traitement TVA tunisien faut-il examiner et quelles preuves demander ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe tunisienne facture une prestation de conseil informatique a une societe francaise assujettie a la TVA. Le service est utilise en France. Quel traitement TVA tunisien faut-il examiner et quelles preuves demander ?. Si le service est utilise hors de Tunisie ou exploite hors de Tunisie, notamment en France, et que les preuves existent, l'analyse peut s'orienter vers un traitement d'exportation de services ou de non-imposition tunisienne a verifier dans le Code de la taxe sur la valeur ajoutee. Le client est p

### batch2_tva_france_b2c_non_assujetti

Question: Une societe tunisienne fournit un service numerique a un client francais non assujetti. Peut-on appliquer le meme regime TVA qu'une prestation B2B exportee ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe tunisienne fournit un service numerique a un client francais non assujetti. Peut-on appliquer le meme regime TVA qu'une prestation B2B exportee ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur ajoutee. Le client non-assujetti doit etre analyse specifiquement: ne pas reprendr

### batch2_tva_service_used_tunisia

Question: Une societe tunisienne facture un client etabli en France, mais la prestation informatique est utilisee en Tunisie par la filiale tunisienne du client. Peut-on la traiter comme exportation de services ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe tunisienne facture un client etabli en France, mais la prestation informatique est utilisee en Tunisie par la filiale tunisienne du client. Peut-on la traiter comme exportation de services ?. Si le service est utilise ou exploite en Tunisie, il ne faut pas conclure automatiquement a une exportation de services: le risque de TVA tunisienne doit rester ouvert et documente. Le statut B2B/B2C du client n'est pas completement documente: il faut obtenir son identite, son pays d'etablissement et, si possible, son

### batch2_tva_service_used_abroad

Question: Une prestation de support logiciel est facturee par une societe tunisienne a un client francais; le logiciel est exploite en France. Quel regime TVA et quels justificatifs verifier ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une prestation de support logiciel est facturee par une societe tunisienne a un client francais; le logiciel est exploite en France. Quel regime TVA et quels justificatifs verifier ?. Si le service est utilise hors de Tunisie ou exploite hors de Tunisie, notamment en France, et que les preuves existent, l'analyse peut s'orienter vers un traitement d'exportation de services ou de non-imposition tunisienne a verifier dans le Code de la taxe sur la valeur ajoutee. Le statut B2B/B2C du client n'est pas completement docume

### batch2_tva_training_physically_france

Question: Une societe tunisienne facture une formation informatique a une societe francaise. Les consultants se deplacent et la formation est realisee physiquement en France. Quelle analyse TVA faut-il faire ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une societe tunisienne facture une formation informatique a une societe francaise. Les consultants se deplacent et la formation est realisee physiquement en France. Quelle analyse TVA faut-il faire ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur ajoutee. Le statut B2B/B2C du client n'e

### batch2_tva_partly_tunisia_partly_abroad

Question: Une mission de maintenance informatique pour un client francais est realisee partiellement depuis la Tunisie et partiellement en France. Comment securiser le traitement TVA et la facture ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une mission de maintenance informatique pour un client francais est realisee partiellement depuis la Tunisie et partiellement en France. Comment securiser le traitement TVA et la facture ?. Si le service est rendu a un client etranger et effectivement utilise ou exploite hors de Tunisie avec justificatifs, le traitement peut relever d'une exportation de services, d'une operation hors champ tunisien ou d'une exoneration a verifier dans le Code de la taxe sur la valeur ajoutee. Le statut B2B/B2C du client n'est pas comp

### batch2_tva_no_foreign_client_proof

Question: Une facture de prestation informatique est emise a un nom francais, mais le client ne fournit aucun justificatif de son etablissement hors de Tunisie. Peut-on appliquer un regime export TVA ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: Une facture de prestation informatique est emise a un nom francais, mais le client ne fournit aucun justificatif de son etablissement hors de Tunisie. Peut-on appliquer un regime export TVA ?. Sans preuve du client etranger, du lieu d'utilisation ou de l'exploitation hors de Tunisie, le cabinet ne peut pas securiser un traitement d'exportation de services ou d'exoneration. Le statut B2B/B2C du client n'est pas completement documente: il faut obtenir son identite, son pays d'etablissement et, si possible, son statut fi

### batch2_tva_invoice_no_export_justification

Question: La societe a emis une facture sans TVA a un client francais, mais la facture ne contient aucune justification du regime d'exportation de services. Quels risques et corrections verifier ?

Before:

New variant added in Batch 2.

After:

## Reponse
Pour cette prestation de services transfrontaliere, la base TVA doit etre le Code de la taxe sur la valeur ajoutee, pas le Code de l'IRPP et de l'IS. Faits transmis: La societe a emis une facture sans TVA a un client francais, mais la facture ne contient aucune justification du regime d'exportation de services. Quels risques et corrections verifier ?. Sans preuve du client etranger, du lieu d'utilisation ou de l'exploitation hors de Tunisie, le cabinet ne peut pas securiser un traitement d'exportation de services ou d'exoneration. Le statut B2B/B2C du client n'est pas completement documente: il faut obtenir son identite, son pays d'etablissement et, si possible, son statut fiscal 