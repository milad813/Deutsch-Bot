"""Configuration management using pydantic-settings."""

import logging
from enum import Enum
from typing import List, Optional
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class BotMode(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # Telegram
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    admin_user_id: int = Field(default=0, env="ADMIN_USER_ID")
    allow_public_access: bool = Field(default=False, env="ALLOW_PUBLIC_ACCESS")

    # Database
    db_path: str = Field(default="words.db", env="DB_PATH")

    # Audio
    audio_cache_dir: str = Field(default="audio_cache", env="AUDIO_CACHE_DIR")

    # Groq LLM
    groq_api_key: Optional[str] = Field(default=None, env="GROQ_API_KEY")
    groq_api_keys: List[str] = Field(default_factory=list, env="GROQ_API_KEYS")
    groq_model: str = Field(default="llama-3.3-70b-versatile", env="GROQ_MODEL")
    groq_max_tokens: int = Field(default=400, env="GROQ_MAX_TOKENS")
    groq_temperature: float = Field(default=0.7, env="GROQ_TEMPERATURE")

    # User preferences
    user_interests: str = Field(default="", env="USER_INTERESTS")

    # Bot mode
    bot_mode: BotMode = Field(default=BotMode.HYBRID, env="BOT_MODE")

    # Quiz settings
    quiz_auto_next_on_correct: bool = Field(default=True, env="QUIZ_AUTO_NEXT_ON_CORRECT")
    max_quiz_all_count: int = Field(default=100, env="MAX_QUIZ_ALL_COUNT")

    # Flashcard settings
    flashcard_queue_limit: int = Field(default=20, env="FLASHCARD_QUEUE_LIMIT")
    flashcard_new_limit: int = Field(default=5, env="FLASHCARD_NEW_LIMIT")

    # TTS settings
    tts_auto_delete_seconds: int = Field(default=60, env="TTS_AUTO_DELETE_SECONDS")
    tts_send_as_document: bool = Field(default=False, env="TTS_SEND_AS_DOCUMENT")

    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: str = Field(default="bot.log", env="LOG_FILE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @field_validator("groq_api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v):
        """Parse comma-separated API keys into a list."""
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v or []

    @property
    def effective_api_keys(self) -> List[str]:
        """Get combined API keys (list takes precedence over single key)."""
        if self.groq_api_keys:
            return self.groq_api_keys
        if self.groq_api_key:
            return [self.groq_api_key]
        return []

    @property
    def is_llm_available(self) -> bool:
        """Check if LLM is available based on mode and API keys."""
        if self.bot_mode == BotMode.OFFLINE:
            return False
        return bool(self.effective_api_keys)

    def is_authorized_user(self, user_id: int) -> bool:
        """Check if a user is authorized to use the bot."""
        if self.admin_user_id == 0:
            return self.allow_public_access
        return user_id == self.admin_user_id


# Global settings instance
settings = Settings()


def validate_config() -> None:
    """Validate critical configuration values."""
    missing = []
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if settings.admin_user_id == 0 and not settings.allow_public_access:
        missing.append("ADMIN_USER_ID (یا ALLOW_PUBLIC_ACCESS=1)")
    if settings.bot_mode == BotMode.ONLINE and not settings.groq_api_key and not settings.groq_api_keys:
        missing.append("GROQ_API_KEY")

    if missing:
        raise RuntimeError("متغیرهای زیر تنظیم نشده‌اند: " + ", ".join(missing))

    if not settings.effective_api_keys:
        logging.warning("GROQ_API_KEYS تنظیم نشده. قابلیت LLM غیرفعال است.")


def setup_logging() -> None:
    """Setup logging with file rotation and proper formatting."""
    from logging.handlers import RotatingFileHandler

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_path = Path(settings.log_file)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("groq").setLevel(logging.WARNING)
