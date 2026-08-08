"""Constants and configuration values for the Deutsch-Bot."""

import logging
from enum import Enum
from typing import Final

# =============================================================================
# Bot Configuration
# =============================================================================


class BotMode(Enum):
    """Bot operation modes."""

    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"


# =============================================================================
# SRS/FSRS Configuration
# =============================================================================

FLASHCARD_QUEUE_LIMIT: Final[int] = 20
FLASHCARD_NEW_LIMIT: Final[int] = 5
MAX_QUIZ_ALL_COUNT: Final[int] = 100
QUIZ_AUTO_NEXT_ON_CORRECT: Final[bool] = True


# =============================================================================
# TTS Configuration
# =============================================================================

TTS_AUTO_DELETE_SECONDS: Final[int] = 60
TTS_SEND_AS_DOCUMENT: Final[bool] = False


# =============================================================================
# UI Constants
# =============================================================================

PROGRESS_BAR_WIDTH: Final[int] = 10
EMOJI_PROGRESS: Final[str] = "🟢"
EMOJI_EMPTY: Final[str] = "⚪️"


# =============================================================================
# Quiz Configuration
# =============================================================================


class QuizType(Enum):
    """Types of quiz questions."""

    ARTICLE = "article"
    MEANING = "meaning"
    REVERSE = "reverse"
    CLOZE = "cloze"


MIN_QUIZ_OPTIONS: Final[int] = 3
MAX_QUIZ_OPTIONS: Final[int] = 4


# =============================================================================
# Learning Session States
# =============================================================================


class FlashcardState(Enum):
    """States for flashcard learning session."""

    FRONT = "front"
    BACK = "back"


class LTRStage(Enum):
    """Stages for Look-Test-Review learning method."""

    LOOK = "look"
    TEST = "test"
    REVIEW = "review"


# =============================================================================
# Database Defaults
# =============================================================================

DEFAULT_USER_LEVEL: Final[str] = "A1"
DEFAULT_OWNER_ID: Final[int] = 1
DEFAULT_EASE_FACTOR: Final[float] = 2.5


# =============================================================================
# LLM Configuration
# =============================================================================

DEFAULT_LLM_MODEL: Final[str] = "llama-3.3-70b-versatile"
DEFAULT_LLM_MAX_TOKENS: Final[int] = 400
DEFAULT_LLM_TEMPERATURE: Final[float] = 0.7


# =============================================================================
# Error Messages
# =============================================================================

ERROR_GENERIC: Final[str] = "⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید یا /menu را بزنید."
ERROR_NO_WORDS: Final[str] = "😔 هیچ کلمه‌ای برای نمایش وجود ندارد."
ERROR_NO_DUE_WORDS: Final[str] = "🎉 آفرین! هیچ کلمه‌ای برای مرور نداری!"
ERROR_NO_NEW_WORDS: Final[str] = "🎉 همه کلمات جدید این درس را قبلاً دیده‌ای!"
ERROR_NO_HARD_WORDS: Final[str] = "🎉 هیچ کلمه‌ی سختِ معوقی نداری!"


# =============================================================================
# Success Messages
# =============================================================================

SUCCESS_SESSION_COMPLETE: Final[str] = "✅ جلسه یادگیری تکمیل شد!"
SUCCESS_WORD_LEARNED: Final[str] = "🎯 عالی بود! کلمه یاد گرفته شد."


# =============================================================================
# Button Labels
# =============================================================================

BTN_SHOW_MEANING: Final[str] = "👀 نشان بده معنی"
BTN_SKIP: Final[str] = "⏭️ رد شدن"
BTN_TTS: Final[str] = "🔊 تلفظ"
BTN_BACK: Final[str] = "🔙 منوی اصلی"
BTN_AGAIN: Final[str] = "😵 Again"
BTN_HARD: Final[str] = "😬 Hard"
BTN_GOOD: Final[str] = "🙂 Good"
BTN_EASY: Final[str] = "😎 Easy"


# =============================================================================
# Logging
# =============================================================================

LOG_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL_DEFAULT: Final[int] = logging.INFO
