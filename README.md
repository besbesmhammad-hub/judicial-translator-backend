---
title: Judicial Translator Backend
emoji: 📄
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8080
---

# Judicial Translator Backend

FastAPI backend for heavy document translation workflows.

## What it does

- Parses TXT, HTML, DOCX, PPTX, XLSX and PDF on the server.
- Preserves headings, articles, pages, lists and tables where possible.
- Translates DOCX, PPTX and XLSX in-place for same-format downloads, keeping the original document package.
- Retrieves legal/accounting/technical terminology before translation.
- Splits long documents by structure.
- Calls an OpenRouter-compatible chat model.
- Exposes JSON, file-upload and translated-document download APIs for the Netlify frontend.

## Output modes

- `/v1/analyze-file`: extract structured text only.
- `/v1/translate`: translate text and return JSON.
- `/v1/translate-file`: upload a document and return translated JSON.
- `/v1/render-document`: translate text and download DOCX, PDF, HTML or TXT.
- `/v1/translate-file-document`: upload a document and download a translated document. Use `output_format=same` to keep DOCX, PPTX, XLSX, PDF, HTML or TXT when possible. DOCX/PPTX/XLSX use native in-place translation; PDF is rendered as a best-effort translated PDF.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
$env:OPENROUTER_API_KEY="your-key"
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

## Deploy

Use any Python web host that supports Docker or `uvicorn`, such as Render, Railway, Fly.io, or a VPS.

Required environment variables:

- `OPENROUTER_API_KEY`
- `LLM_MODEL`, optional, defaults to `google/gemini-2.5-flash-lite`
- `ALLOWED_ORIGINS`, optional, comma-separated

After deployment, set `BACKEND_API_URL` in Netlify to the backend URL.
