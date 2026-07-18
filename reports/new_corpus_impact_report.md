# New Corpus Impact Report

- `code_irpp_is_2025`: current/default IRPP/IS source for cabinet questions; replaces `code_irpp_is_2011` as default while keeping 2011 historical-only.
- `loi_finances_2026_ar`: improves Arabic finance-law routing from missing or irrelevant source toward direct/framework source support.
- CDPF, TVA, enregistrement/timbre, fiscalite locale yearly editions: enable explicit source-year routing instead of accidental year matching from transaction facts.
- Declaration forms and LICOBA schema: targeted form/document workflow support; not general legal authority unless the query concerns that form.

Detailed source movement must be confirmed by `scripts/run_corpus_governance_checks.py` and the Level 1/2/2.5/3/3.5 benchmarks.