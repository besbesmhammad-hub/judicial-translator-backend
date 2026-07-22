# Production Monitoring Checklist

Use this checklist before supervised beta sessions and before any deployment.

## Live Alignment

- Frontend URL: `https://judicial-translator-20260706031117.netlify.app`
- Backend URL: `https://judicial-translator-backend.onrender.com`
- Check frontend backend config:
  - `https://judicial-translator-20260706031117.netlify.app/.netlify/functions/config`
- Confirm it points to the Render backend above.

## Backend Health

- Check `/health`:
  - `https://judicial-translator-backend.onrender.com/health`
- Confirm:
  - `ok: true`
  - expected `commit_hash`
  - expected environment/service name
  - corpus available
  - accounting chat available

## Backend Version

- Check `/version`:
  - `https://judicial-translator-backend.onrender.com/version`
- Confirm the live commit before any beta test.
- Official supervised beta commit: `fc72c5452672`.

## Feedback Endpoint

- Endpoint: `/v1/accounting-feedback`
- Confirm feedback can store:
  - question;
  - answer;
  - workflow;
  - deterministic flag;
  - sources;
  - feedback label;
  - reviewer note;
  - timestamp/log entry.

## Server And Provider Errors

Monitor for:

- HTTP `502`, `503`, `504`;
- Render restarts or failed deploys;
- provider 429/rate limits;
- provider 404/5xx;
- request timeouts;
- repeated frontend temporary-server messages.

Evaluator rule: classify HTTP 502/503/504 as `infra_error`, not model failure, and do not fabricate an answer.

## Release Gate Before Deploy

Before deploying backend changes:

1. Compile backend:
   - `python -m compileall app scripts`
2. Run deterministic release gate:
   - `.venv\Scripts\python.exe scripts\run_deterministic_release_gate.py`
3. Required result:
   - static deterministic tests pass;
   - mutation tests pass across configured seeds;
   - `0` wrong calculations;
   - `0` contradictory dates;
   - `0` legacy template contamination;
   - `0` fake service dates not in prompt;
   - `0` irrelevant final-answer blocks.

## Deployment Rule

Do not deploy unless one of these applies:

- infrastructure bug;
- security/privacy issue;
- deterministic calculation error;
- unsafe answer;
- severe routing failure.

Do not deploy for ordinary safe_pass cases unless they are wrong, unsafe, or misleading.

