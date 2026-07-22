# Supervised Beta Status

Candidate status: supervised beta candidate. The assistant is not autonomous client-facing software.

## Live endpoints

- Frontend URL: `https://judicial-translator-20260706031117.netlify.app`
- Backend URL: `https://judicial-translator-backend.onrender.com`
- Current supervised beta infrastructure commit: `e93b0b61fb3f`
- Last protected reasoning baseline before beta-infrastructure changes: `a76ef8e2ab2d`
- Backend branch: `level35-adversarial-benchmark`

## Protected gates

- Deterministic release gate is mandatory before deployment.
- Latest accepted deterministic gate before deploying `e93b0b61fb3f`: 18 static regressions passed, 375 mutation regressions passed.
- Mutation seeds: `20260722`, `20260723`, `20260724`, `20260725`, `20260726`
- Acceptance criteria: 0 wrong deterministic calculations, 0 contradictory dates, 0 fact mutations, 0 legacy-template contamination, 0 irrelevant final-answer blocks.

## Protected workflows

- `fixed_asset_depreciation_case`
- `revenue_cutoff_tva_case`
- `expense_cutoff_prepaid_case`
- `sales_cutoff_delivery_case`
- `goods_advance_delivery_case`
- `receivable_impairment_subsequent_event`
- `tva_operational_case`
- `withholding_tax_classification_case`
- `nonresident_service_payment_tax_case`
- `accounting_standards_hierarchy_case`

## Known limitations

- Supervised internal use only; expert validation is required before client use.
- Source precision can still be broad for standards, audit, dividends, conventions and some procedure questions.
- Rates, deadlines, articles and final legal conclusions must not be invented without a direct source.
- Missing-source cases must remain reserved until the precise corpus source is added and tested.
- Feedback and beta logs may contain confidential facts; they must remain server-side and reviewed by authorized experts only.

## Beta safeguards added

- Visible UI disclaimer: "Assistant de préparation pour cabinet. Les réponses doivent être validées par un expert avant usage client."
- Answer safety display: sources, source confidence, missing-source warning and validation-expert-required flag.
- Feedback labels: `correct`, `incomplete`, `wrong`, `unsafe`, `missing_source`, `bad_routing`.
- Private beta review logs: question, workflow, deterministic facts/decision, final answer, sources, source confidence and validation flags.

## Round 3 blind evaluation

Use `app/data/blind_round3_template.jsonl` as a blank 30-case template. Replace the empty `question` values with unseen real cabinet questions before running:

```powershell
.\.venv\Scripts\python.exe scripts\run_blind_cabinet_eval.py --dataset app\data\blind_round3_template.jsonl --base-url https://judicial-translator-backend.onrender.com --output reports\blind_round3_eval.json
```

The evaluator reports `expert_pass`, `safe_pass`, `fail`, or `unsafe`, plus reason, missing workflow/source, wrong calculation, wrong routing, fact mutation and contamination indicators.
