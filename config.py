import logging
import os
from enum import Enum
from typing import Dict, Optional


class BotMode(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"


def _load_env(path: str = None) -> Dict[str, str]:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    env_vars: Dict[str, str] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")

    return env_vars


_env = _load_env()


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, _env.get(key, default))


def _get_int(key: str, default: int) -> int:
    try:
        return int(get_env(key, str(default)))
    except Exception:
        return default


def _get_bool(key: str, default: bool) -> bool:
    value = get_env(key, "1" if default else "0")
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _get_float(key: str, default: float) -> float:
    try:
        value = get_env(key)
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except Exception:
        return default


TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = _get_int("ADMIN_USER_ID", 0)
ALLOW_PUBLIC_ACCESS = _get_bool("ALLOW_PUBLIC_ACCESS", False)
DB_PATH = get_env("DB_PATH", "words.db")
AUDIO_CACHE_DIR = get_env("AUDIO_CACHE_DIR", "audio_cache")

# Timezone configuration (default: Iran timezone +3:30)
USER_TIMEZONE_OFFSET_HOURS = _get_int("USER_TIMEZONE_OFFSET_HOURS", 3)
USER_TIMEZONE_OFFSET_MINUTES = _get_int("USER_TIMEZONE_OFFSET_MINUTES", 30)

GROQ_API_KEY = get_env("GROQ_API_KEY")


def _get_list(key: str, default=None):
    value = get_env(key)
    if not value:
        return default or []
    return [v.strip() for v in value.split(",") if v.strip()]


# کلیدهای چندگانه Groq (با کاما جدا کن). سازگار با کلید تکی قدیمی.
GROQ_API_KEYS = _get_list("GROQ_API_KEYS")
if not GROQ_API_KEYS and GROQ_API_KEY:
    GROQ_API_KEYS = [GROQ_API_KEY]
GROQ_MODEL = get_env("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MAX_TOKENS = _get_int("GROQ_MAX_TOKENS", 400)
GROQ_TEMPERATURE = _get_float("GROQ_TEMPERATURE", 0.7)
USER_INTERESTS = get_env("USER_INTERESTS", "")
_BOT_MODE_STR = get_env("BOT_MODE", "hybrid").lower()
try:
    BOT_MODE = BotMode(_BOT_MODE_STR)
except ValueError:
    BOT_MODE = BotMode.HYBRID

QUIZ_AUTO_NEXT_ON_CORRECT = _get_bool("QUIZ_AUTO_NEXT_ON_CORRECT", False)
MAX_QUIZ_ALL_COUNT = _get_int("MAX_QUIZ_ALL_COUNT", 100)
FLASHCARD_QUEUE_LIMIT = _get_int("FLASHCARD_QUEUE_LIMIT", 20)
FLASHCARD_NEW_LIMIT = _get_int("FLASHCARD_NEW_LIMIT", 5)
TTS_AUTO_DELETE_SECONDS = _get_int("TTS_AUTO_DELETE_SECONDS", 60)
TTS_SEND_AS_DOCUMENT = _get_bool("TTS_SEND_AS_DOCUMENT", False)
# Daily reminder local time
DAILY_REMINDER_HOUR_LOCAL = _get_int("DAILY_REMINDER_HOUR_LOCAL", 9)
DAILY_REMINDER_MINUTE_LOCAL = _get_int("DAILY_REMINDER_MINUTE_LOCAL", 0)

# Backup retention
BACKUP_KEEP_DAYS = _get_int("BACKUP_KEEP_DAYS", 14)
BACKUP_KEEP_MAX = _get_int("BACKUP_KEEP_MAX", 30)


def is_authorized_user(user_id: int) -> bool:
    # ✅ اگر دسترسی عمومی فعال باشد، همه اجازه استفاده دارند
    if ALLOW_PUBLIC_ACCESS:
        return True
    if ADMIN_USER_ID == 0:
        return False
    return user_id == ADMIN_USER_ID

def is_llm_available() -> bool:
    if BOT_MODE == BotMode.OFFLINE:
        return False
    return bool(GROQ_API_KEYS)


def validate_config() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if ADMIN_USER_ID == 0 and not ALLOW_PUBLIC_ACCESS:
        missing.append(
            "ADMIN_USER_ID (یا اگر واقعاً می‌خواهی ربات عمومی باشد: ALLOW_PUBLIC_ACCESS=1)"
        )
    if BOT_MODE == BotMode.ONLINE and not GROQ_API_KEYS:
        missing.append("GROQ_API_KEY یا GROQ_API_KEYS")

    if missing:
        raise RuntimeError("این متغیرها تنظیم نشده‌اند: " + ", ".join(missing))

    if not GROQ_API_KEYS:
        logging.warning("GROQ_API_KEYS تنظیم نشده. قابلیت LLM غیرفعال است.")


def setup_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("groq").setLevel(logging.WARNING)
