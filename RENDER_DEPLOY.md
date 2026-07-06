# Render Free Deployment

This backend is prepared for Render Free using `render.yaml`.

## Service

- Type: Web Service
- Runtime: Docker
- Plan: Free
- Health check: `/health`
- Start command: included in `Dockerfile`

## Required environment variable

- `OPENROUTER_API_KEY`

## Optional environment variables

- `LLM_MODEL`
- `LLM_FALLBACK_MODELS`
- `SITE_URL`
- `ALLOWED_ORIGINS`
- `MAX_CHARS_PER_CHUNK`
- `LLM_MAX_TOKENS`

## After Deploy

1. Copy the Render backend URL, for example:
   `https://judicial-translator-backend.onrender.com`
2. Set Netlify environment variable:
   `BACKEND_API_URL=https://your-render-service.onrender.com`
3. Redeploy Netlify.

## Notes

Render Free can sleep after inactivity. First request after sleep can be slow.
For client production, upgrade only the backend service when needed.
