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
GROQ_MAX_TOKENS = _get_int("GROQ_MAX_TOKENS", 1024)
GROQ_TEMPERATURE = _get_float("GROQ_TEMPERATURE", 0.7)
USER_INTERESTS = get_env("USER_INTERESTS", "")
_BOT_MODE_STR = get_env("BOT_MODE", "hybrid").lower()
try:
    BOT_MODE = BotMode(_BOT_MODE_STR)
except ValueError:
    BOT_MODE = BotMode.HYBRID

QUIZ_AUTO_NEXT_ON_CORRECT = _get_bool("QUIZ_AUTO_NEXT_ON_CORRECT", False)
QUIZ_LLM_GENERATION = _get_bool("QUIZ_LLM_GENERATION", False)
QUIZ_LLM_TIMEOUT_SECONDS = _get_float("QUIZ_LLM_TIMEOUT_SECONDS", 2.5)
QUIZ_LLM_EXPLAIN_MISTAKE = _get_bool("QUIZ_LLM_EXPLAIN_MISTAKE", False)
LLM_TIMEOUT_SECONDS = _get_int("LLM_TIMEOUT_SECONDS", 8)
LLM_USE_REASONING_PARAMS = _get_bool("LLM_USE_REASONING_PARAMS", False)
MAX_QUIZ_ALL_COUNT = _get_int("MAX_QUIZ_ALL_COUNT", 100)
FLASHCARD_QUEUE_LIMIT = _get_int("FLASHCARD_QUEUE_LIMIT", 20)
FLASHCARD_NEW_LIMIT = _get_int("FLASHCARD_NEW_LIMIT", 5)
FLASHCARD_QUICK_RATE = _get_bool("FLASHCARD_QUICK_RATE", True)
TTS_AUTO_DELETE_SECONDS = _get_int("TTS_AUTO_DELETE_SECONDS", 60)
TTS_SEND_AS_DOCUMENT = _get_bool("TTS_SEND_AS_DOCUMENT", False)
# Daily reminder local time
DAILY_REMINDER_HOUR_LOCAL = _get_int("DAILY_REMINDER_HOUR_LOCAL", 9)
DAILY_REMINDER_MINUTE_LOCAL = _get_int("DAILY_REMINDER_MINUTE_LOCAL", 0)

# Daily reminder flood control (Phase 1, item 5)
# The ``daily_reminder`` job walks the opt-in recipient list in fixed-
# size chunks.  The DB work for each chunk is 4 GROUP BY queries
# regardless of chunk size; the per-chunk pause is what keeps the
# message-send rate inside Telegram's per-second flood window.
#
#  * ``REMINDER_BATCH_SIZE`` -- number of users processed before
#    ``REMINDER_SLEEP_SECONDS`` is slept.  Default 50 matches the
#    conservative 30 msgs/sec global limit with comfortable headroom
#    for unrelated traffic.  Set lower if you have many parallel
#    handlers running.
#  * ``REMINDER_SLEEP_SECONDS`` -- pause between batches.  Default 1.0
#    gives ~1 batch/sec, which combined with the 50-user batch is
#    well below the 30 msgs/sec global flood limit.  Set higher for
#    very large opt-in lists; set lower only if you really know you
#    have headroom.
REMINDER_BATCH_SIZE = _get_int("REMINDER_BATCH_SIZE", 50)
REMINDER_SLEEP_SECONDS = _get_float("REMINDER_SLEEP_SECONDS", 1.0)

# Backup retention
BACKUP_KEEP_DAYS = _get_int("BACKUP_KEEP_DAYS", 14)
BACKUP_KEEP_MAX = _get_int("BACKUP_KEEP_MAX", 30)

# Rate limiter (sliding window, per-user). The middleware reads these at
# import time; change them via the .env file and restart the bot.
RATE_LIMIT_MAX_REQUESTS = _get_int("RATE_LIMIT_MAX_REQUESTS", 80)
RATE_LIMIT_WINDOW_SECONDS = _get_int("RATE_LIMIT_WINDOW_SECONDS", 60)

# Daily LLM usage quotas (per user, local-day window). Each user can
# generate at most this many LLM stories / examples per calendar day
# (in the configured user-local timezone). Enforced by the bot before
# every LLM call and tracked in the ``user_llm_usage`` table.
LLM_DAILY_STORY_LIMIT = _get_int("LLM_DAILY_STORY_LIMIT", 20)
LLM_DAILY_EXAMPLE_LIMIT = _get_int("LLM_DAILY_EXAMPLE_LIMIT", 200)


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


# Logging configuration (Phase 1, item 7).
# ``LOG_FORMAT=text`` keeps the historical human-readable format;
# ``LOG_FORMAT=json`` switches the root handler to a single-line
# JSON formatter suitable for log shippers (Loki, ELK, ...).
# ``LOG_LEVEL`` accepts the standard names (case-insensitive);
# unknown values fall back to INFO with a warning.
LOG_FORMAT = (get_env("LOG_FORMAT", "text") or "text").strip().lower()
LOG_LEVEL = (get_env("LOG_LEVEL", "INFO") or "INFO").strip().upper()

_LEVELS_BY_NAME = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}


def setup_logging() -> None:
    """Install the root-logger handler and quiet noisy libraries.

    Respects ``LOG_LEVEL`` (case-insensitive; unknown values
    fall back to ``INFO`` with a warning) and ``LOG_FORMAT``:

    * ``text`` (default) -- the historical
      ``"%(asctime)s - %(name)s - %(levelname)s - %(message)s"``
      format, plus a ``key=value`` suffix when the record was
      emitted via :func:`core.logging_utils.log_event`.
    * ``json`` -- a single-line JSON object per record with
      ``timestamp`` / ``level`` / ``logger`` / ``message`` plus
      every ``extra=`` field.  Secret-looking fields are
      redacted; full LLM prompts are truncated.

    Idempotent: calling it twice (e.g. tests) is safe; we only
    touch the root handler if it has no formatter yet, so user
    configuration in production is preserved.
    """
    level = _LEVELS_BY_NAME.get(LOG_LEVEL)
    if level is None:
        logging.warning(
            "Unknown LOG_LEVEL=%r; falling back to INFO.", LOG_LEVEL
        )
        level = logging.INFO

    use_json = LOG_FORMAT == "json"
    if use_json:
        # Imported lazily so unit tests that only need
        # ``is_authorized_user`` / constants don't pay the import
        # cost of the formatter module.
        from core.logging_utils import JsonFormatter

        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        from core.logging_utils import TextWithExtrasFormatter

        handler = logging.StreamHandler()
        handler.setFormatter(TextWithExtrasFormatter())

    root = logging.getLogger()
    # Idempotency: if a previous call already installed a
    # handler, only reconfigure it when the caller asked for a
    # different format.  This lets tests re-call freely.
    existing = root.handlers
    if existing and getattr(existing[0], "_deutsch_bot_logging", False):
        # Already ours -- just refresh the level / format.
        existing[0].setLevel(level)
        # Always recreate the formatter so a LOG_FORMAT flip
        # between text and json takes effect.
        if use_json:
            from core.logging_utils import JsonFormatter

            existing[0].setFormatter(JsonFormatter())
        else:
            from core.logging_utils import TextWithExtrasFormatter

            existing[0].setFormatter(TextWithExtrasFormatter())
        # Also refresh the root level so the test that flips
        # LOG_LEVEL between calls sees the new threshold.
        root.setLevel(level)
    else:
        # First install -- clear any basicConfig defaults that
        # other modules may have registered, then attach ours.
        for h in list(existing):
            root.removeHandler(h)
        handler.setLevel(level)
        handler._deutsch_bot_logging = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        root.setLevel(level)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("groq").setLevel(logging.WARNING)
