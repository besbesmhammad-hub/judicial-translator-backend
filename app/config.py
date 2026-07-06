import os


def csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3-next-80b-a3b-instruct:free")
LLM_FALLBACK_MODELS = [
    item.strip()
    for item in os.getenv(
        "LLM_FALLBACK_MODELS",
        "qwen/qwen3-next-80b-a3b-instruct:free,meta-llama/llama-3.3-70b-instruct:free,google/gemma-3-27b-it:free",
    ).split(",")
    if item.strip()
]
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
ENABLE_KEYLESS_FALLBACKS = os.getenv("ENABLE_KEYLESS_FALLBACKS", "true").lower() not in {"0", "false", "no", "off"}
POLLINATIONS_ENDPOINT = os.getenv("POLLINATIONS_ENDPOINT", "https://text.pollinations.ai/openai/v1/chat/completions")
POLLINATIONS_MODELS = csv_env("POLLINATIONS_MODELS", "openai-fast,gpt-oss-20b")
SITE_URL = os.getenv("SITE_URL", "https://taupe-gingersnap-1b1260.netlify.app")
MAX_CHARS_PER_CHUNK = int(os.getenv("MAX_CHARS_PER_CHUNK", "2200"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2200"))
ALLOWED_ORIGINS = csv_env(
    "ALLOWED_ORIGINS",
    "https://taupe-gingersnap-1b1260.netlify.app,https://judicial-translator-20260706031117.netlify.app,http://localhost:8888,http://127.0.0.1:8888,http://localhost:5001,http://127.0.0.1:5001,http://localhost:5012,http://127.0.0.1:5012",
)
