import os
import subprocess


def current_revision() -> str:
    explicit = (
        os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("RENDER_COMMIT")
        or os.getenv("COMMIT_SHA")
        or os.getenv("GIT_COMMIT")
        or os.getenv("SOURCE_VERSION")
        or os.getenv("SPACE_VERSION")
        or os.getenv("APP_REVISION")
    )
    if explicit:
        return explicit[:12]
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_API_KEY_READY = bool(GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza"))
GEMINI_ENDPOINT_BASE = os.getenv("GEMINI_ENDPOINT_BASE", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_MODELS = csv_env("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash")
ENABLE_KEYLESS_FALLBACKS = os.getenv("ENABLE_KEYLESS_FALLBACKS", "true").lower() not in {"0", "false", "no", "off"}
POLLINATIONS_ENDPOINT = os.getenv("POLLINATIONS_ENDPOINT", "https://text.pollinations.ai/openai/v1/chat/completions")
POLLINATIONS_MODELS = csv_env("POLLINATIONS_MODELS", "gpt-oss-20b,openai-fast")
KILO_ENDPOINT = os.getenv("KILO_ENDPOINT", "https://api.kilo.ai/api/gateway/v1/chat/completions")
KILO_MODELS = csv_env("KILO_MODELS", "nvidia/nemotron-3-super-120b-a12b:free,stepfun/step-3.7-flash:free,poolside/laguna-xs.2:free")
SITE_URL = os.getenv("SITE_URL", "https://taupe-gingersnap-1b1260.netlify.app")
MAX_CHARS_PER_CHUNK = int(os.getenv("MAX_CHARS_PER_CHUNK", "5200"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_PROVIDER_TIMEOUT = float(os.getenv("LLM_PROVIDER_TIMEOUT", "15"))
LLM_PROVIDER_RETRIES = int(os.getenv("LLM_PROVIDER_RETRIES", "1"))
ALLOWED_ORIGINS = csv_env(
    "ALLOWED_ORIGINS",
    "https://taupe-gingersnap-1b1260.netlify.app,https://judicial-translator-20260706031117.netlify.app,http://localhost:8888,http://127.0.0.1:8888,http://localhost:5001,http://127.0.0.1:5001,http://localhost:5012,http://127.0.0.1:5012",
)
APP_REVISION = current_revision()
ACCOUNTING_CHAT_LOG_ENABLED = os.getenv("ACCOUNTING_CHAT_LOG_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
ACCOUNTING_CHAT_LOG_PATH = os.getenv("ACCOUNTING_CHAT_LOG_PATH", "/tmp/accounting_chat_requests.jsonl")
BETA_REVIEW_LOG_ENABLED = os.getenv("BETA_REVIEW_LOG_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
BETA_REVIEW_LOG_PATH = os.getenv("BETA_REVIEW_LOG_PATH", "/tmp/accounting_beta_review.jsonl")
BETA_FEEDBACK_LOG_PATH = os.getenv("BETA_FEEDBACK_LOG_PATH", "/tmp/accounting_beta_feedback.jsonl")
