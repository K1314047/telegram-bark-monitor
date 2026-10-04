import os
from dotenv import load_dotenv

load_dotenv()

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)

def csv_list(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [x.strip() for x in value.replace("\n", ",").split(",") if x.strip()]

TG_API_ID = env_int("TG_API_ID", 0)
TG_API_HASH = os.getenv("TG_API_HASH", "").strip()
TG_PHONE = os.getenv("TG_PHONE", "").strip()

BARK_URL = os.getenv("BARK_URL", "https://api.day.app").rstrip("/")
BARK_KEY = os.getenv("BARK_KEY", "").strip()
BARK_SOUND = os.getenv("BARK_SOUND", "").strip()
BARK_GROUP = os.getenv("BARK_GROUP", "").strip()
BARK_LEVEL = os.getenv("BARK_LEVEL", "active").strip()

CHANNELS = csv_list("CHANNELS")
FILTER_MODE = os.getenv("FILTER_MODE", "keyword").strip().lower()
KEYWORDS = csv_list("KEYWORDS")
KEYWORD_CASE_INSENSITIVE = env_bool("KEYWORD_CASE_INSENSITIVE", True)

DEDUP_ENABLED = env_bool("DEDUP_ENABLED", True)
DEDUP_TTL_SECONDS = env_int("DEDUP_TTL_SECONDS", 604800)
DB_PATH = os.getenv("DB_PATH", "/app/data/monitor.db")

TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
