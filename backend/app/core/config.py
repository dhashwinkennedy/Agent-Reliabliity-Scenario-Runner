from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

# Explicitly load .env file from backend root if present
load_dotenv(ROOT / ".env", override=True)

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'platform.db'}")
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", ROOT / "data")).resolve()
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
    max_page_size: int = int(os.getenv("MAX_PAGE_SIZE", "500"))
    cors_origins: tuple[str, ...] = tuple(x for x in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if x)
    trusted_hosts: tuple[str, ...] = tuple(x for x in os.getenv("TRUSTED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if x)
    jsonl_error_sample_limit: int = int(os.getenv("JSONL_ERROR_SAMPLE_LIMIT", "20"))
    allow_local_http_agents: bool = os.getenv("ALLOW_LOCAL_HTTP_AGENTS", "false").lower() == "true"
    http_agent_timeout_seconds: float = float(os.getenv("HTTP_AGENT_TIMEOUT_SECONDS", "15"))
    app_encryption_key: str | None = (os.getenv("APP_ENCRYPTION_KEY") or "").strip() or None
    provider_timeout_seconds: float = float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "30"))
    allow_local_llm_providers: bool = os.getenv("ALLOW_LOCAL_LLM_PROVIDERS", "false").lower() == "true"
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    tavily_search_enabled: bool = os.getenv("TAVILY_SEARCH_ENABLED", "false").lower() == "true"
    tavily_search_depth: str = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
    tavily_max_results: int = int(os.getenv("TAVILY_MAX_RESULTS", "5"))
    tavily_timeout_seconds: float = float(os.getenv("TAVILY_TIMEOUT_SECONDS", "15"))

settings = Settings()
for folder in (settings.storage_dir / "datasets", settings.storage_dir / "snapshots", settings.storage_dir / "results", settings.storage_dir / "exports"):
    folder.mkdir(parents=True, exist_ok=True)
