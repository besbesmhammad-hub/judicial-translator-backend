# Supervised Beta Operating Guide

## What The App Can Be Used For

- Preparing first-draft cabinet analyses for Tunisian accounting, fiscal, TVA, audit/CAC, company-law, social/CNSS, and procedure questions.
- Structuring facts, missing information, risk points, documents to request, and practical cabinet conclusions.
- Supporting internal review with source confidence and feedback labels.
- Running supervised blind evaluations on real cabinet questions.

## What It Must Not Be Used For

- Autonomous public or client-facing advice.
- Final legal, fiscal, audit, or accounting conclusions without expert review.
- Inventing rates, deadlines, article numbers, penalties, or treaty effects when no direct source supports them.
- Replacing official texts, professional judgment, or signed expert opinions.

## Expert Validation Requirement

Every answer that may affect a client position must be reviewed by a qualified expert. The reviewer should verify:

- Facts extracted by the app match the actual client facts.
- The workflow/domain is correct.
- The cited sources are relevant and current.
- Rates, deadlines, thresholds, and article references are directly supported.
- The final conclusion is practical, not merely a checklist.

## Reading Source Confidence

- `direct_passage`: the answer is supported by a targeted passage. Still verify legal currency before client use.
- `source-cadre` / `framework_source`: the document family is relevant, but the exact article or passage still needs verification.
- `source manquante` / `missing_source`: a required source family is not available or not precise enough. Treat the answer as cautious preparation only.
- `unclassified`: source confidence was not fully classified. Reviewer must inspect the cited source manually.

## Feedback Buttons

Use feedback after reviewing an answer:

- `correct`: usable after expert review.
- `incomplete`: safe but missing important cabinet detail.
- `wrong`: materially incorrect or wrong workflow/source.
- `unsafe`: confident wrong, misleading, or dangerous.
- `missing_source`: answer needs a source not available or not precise enough.
- `bad_routing`: the app chose the wrong workflow/domain.

## Reporting Wrong Answers

For every wrong, unsafe, or misleading answer, record:

- exact question;
- final visible app answer;
- workflow if visible or available in logs;
- why it is wrong;
- expected expert answer;
- source or document needed;
- whether the issue is routing, calculation, source precision, generic answer, contamination, or infrastructure.

Do not silently patch from one example. First classify the failure pattern, then decide if a workflow-level fix is justified.

## Failure Classification

- `expert_pass`: useful cabinet-level answer, facts applied, relevant sources, practical conclusion.
- `safe_pass`: cautious and not wrong, but incomplete or source-limited; acceptable for supervised internal use.
- `fail`: materially insufficient, wrong routing, missing essential domain split, or unusable.
- `unsafe`: confident wrong or dangerous conclusion.
- `infra_error`: no model answer was produced because the system failed, such as 502/503/504.

