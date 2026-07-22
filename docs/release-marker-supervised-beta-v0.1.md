# tunisian-cabinet-assistant-supervised-beta-v0.1

Official supervised beta marker for the Tunisian cabinet assistant.

## Release Identity

- Beta name: `tunisian-cabinet-assistant-supervised-beta-v0.1`
- Backend commit: `fc72c5452672`
- Frontend URL: `https://judicial-translator-20260706031117.netlify.app`
- Backend URL: `https://judicial-translator-backend.onrender.com`
- Intended use: supervised internal cabinet beta only
- Not intended for autonomous public or client-facing legal/fiscal advice

## Validation Snapshot

- Deterministic release gate: passed
- Static deterministic tests: `18/18`
- Mutation deterministic tests: `375/375`
- Mutation seeds: `20260722`, `20260723`, `20260724`, `20260725`, `20260726`
- Wrong deterministic calculations: `0`
- Contradictory dates: `0`
- Legacy template contamination: `0`
- Fake service dates not in prompt: `0`
- Irrelevant final-answer blocks: `0`

## Round 3 Blind Evaluation

Before the two targeted fixes:

- Total cases: `30`
- Expert pass: `20`
- Safe pass: `8`
- Fail: `2`
- Unsafe: `0`
- Safe for supervised internal use: `28/30`

Post-fix verification:

- `r3_ref_003`: HTTP 200, passes public path
- `r3_report_002`: HTTP 200, passes public path
- Reference/standards smoke: `3/3`
- Report-generation mini-suite: `5/5`

## Operating Limitation

This release is a supervised beta. All legal, fiscal, accounting, audit, social, or client-facing answers must be reviewed by a qualified expert before use. The assistant may prepare analysis, structure issues, surface sources, and suggest checks, but it must not be treated as a final authority.

