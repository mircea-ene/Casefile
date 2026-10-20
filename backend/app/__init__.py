import os

from app.config import get_settings

# Must run before huggingface_hub / docling are imported: both read these at import time.
_cache_dir = get_settings().cache_dir.resolve()
os.environ["HF_HOME"] = str(_cache_dir / "huggingface")
os.environ["DOCLING_CACHE_DIR"] = str(_cache_dir / "docling")

# The Langfuse SDK reads its settings from the environment, not from our Settings.
# setdefault, so an explicit environment (e.g. tests turning tracing off) wins.
_settings = get_settings()
if _settings.langfuse_public_key and _settings.langfuse_secret_key:
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", _settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", _settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_BASE_URL", _settings.langfuse_base_url)
else:
    os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
