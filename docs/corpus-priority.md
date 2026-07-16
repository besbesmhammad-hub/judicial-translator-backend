# Corpus Priority

Next source-ingestion priorities for the Expert-Comptable assistant.

## Current Status

1. France-Tunisia tax treaty: indexed from the official impots.gouv.fr convention PDF as `convention_fiscale_france_tunisie`.
2. Dividend withholding and declaration passages: IRPP/IS coverage expanded through Article 52, Article 55 and declaration pages; Article 14 of the France-Tunisia treaty is indexed for non-resident dividend cases.
3. Doubtful receivable fiscal deductibility passages: IRPP/IS coverage expanded beyond the previous first-page cap; direct passage support exists for the Level 3 receivable workflow, but more exact administrative doctrine may still improve precision.
4. Audit standards on fraud, subsequent events and opinion modification: still needs stronger primary/professional-standard source coverage.
5. Exact procedure, invoicing and supporting-document passages: procedures code coverage expanded, but extraction/search quality still needs review because several source passages are Arabic/OCR-heavy.

These priorities should improve source precision for Level 3 cabinet cases. A safe guardrail answer is not enough for these topics when an expert-level answer is expected.

## Next Validation

After each corpus enrichment, rerun Level 2.5 and Level 3 and inspect which sources move from `framework_source` or `missing_source` to `direct_passage`.
