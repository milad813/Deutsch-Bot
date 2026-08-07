# 🚀 Quick Start Refactoring Guide
## Practical First Steps for Deutsch-Bot

This guide provides concrete, actionable refactoring steps you can implement immediately.

---

## Step 1: Add Type Hints to Database Methods (High Impact)

### File: `database.py`

Add these imports at the top:
```python
from typing import Any, Dict, List, Optional, Tuple, Iterable
```

### Example Refactoring - Before:
```python
def get_word_by_id(self, word_id):
    with self._cursor() as c:
        c.execute(f"SELECT {self._word_columns()} FROM words WHERE id = ?", (word_id,))
        row = c.fetchone()
        return self._row_to_word(row) if row else None
```

### After:
```python
def get_word_by_id(self, word_id: int) -> Optional[Word]:
    """Retrieve a word by its ID.
    
    Args:
        word_id: The unique identifier of the word
        
    Returns:
        Word object if found, None otherwise
    """
    with self._cursor() as c:
        c.execute(f"SELECT {self._word_columns()} FROM words WHERE id = ?", (word_id,))
        row = c.fetchone()
        return self._row_to_word(row) if row else None
```

### Methods to Prioritize:
1. `get_word_by_id` - Used frequently
2. `get_words_by_lesson_full` - Complex return type
3. `get_word_stats_full` - Returns dict, needs typing
4. `upsert_word` - Multiple parameters need types
5. `update_word_stats_fsrs` - Many parameters

---

## Step 2: Improve Error Handling in TTS Service

### File: `tts_service.py`

### Before:
```python
try:
    await communicate.save(tmp_path)
except Exception as e:
    logger.error("خطا در تولید صدا برای '%s': %s", text, e)
    return None
```

### After:
```python
try:
    await communicate.save(tmp_path)
except FileNotFoundError as e:
    logger.error("Cache directory not found: %s", e)
    raise
except PermissionError as e:
    logger.error("Permission denied writing audio file: %s", e)
    return None
except Exception as e:
    logger.exception("Unexpected error generating audio for '%s'", text[:50])
    return None
```

---

## Step 3: Extract Constants

### Create: `constants.py`

```python
"""Centralized constants for the Deutsch-Bot application."""
from enum import IntEnum, StrEnum
from typing import Final


class Limits(IntEnum):
    """Application limits and thresholds."""
    FLASHCARD_QUEUE_LIMIT = 20
    FLASHCARD_NEW_LIMIT = 5
    MAX_QUIZ_ALL_COUNT = 100
    ITEMS_PER_PAGE = 5
    TTS_AUTO_DELETE_SECONDS = 60
    MAX_MESSAGE_LENGTH = 4096
    CALLBACK_DATA_MAX_LENGTH = 64


class Grades(IntEnum):
    """FSRS grade values."""
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class WordPhase(StrEnum):
    """Word learning phases."""
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    MASTERED = "mastered"


class QuizType(StrEnum):
    """Types of quiz questions."""
    ARTICLE = "article"
    MEANING = "meaning"
    REVERSE = "reverse"
    CLOZE = "cloze"


# Emoji mappings
WORD_TYPE_EMOJI: Final[Dict[str, str]] = {
    "Noun": "🏷️",
    "Verb": "🏃",
    "Adjective": "🎨",
    "Adverb": "➡️",
    "Preposition": "📍",
    "Pronoun": "👤",
    "Conjunction": "🔗",
    "Phrase": "💬",
}

DEFAULT_WORD_TYPE: Final[str] = "سایر"
DEFAULT_WORD_TYPE_EMOJI: Final[str] = "📌"
```

### Usage in other files:
```python
# In handlers/learning_handlers.py
from constants import Limits, WORD_TYPE_EMOJI, DEFAULT_WORD_TYPE_EMOJI

# Instead of: if len(words) > 20:
if len(words) > Limits.FLASHCARD_QUEUE_LIMIT:
    words = words[:Limits.FLASHCARD_QUEUE_LIMIT]

# Instead of: emoji = type_emoji.get(wtype, "📌")
emoji = WORD_TYPE_EMOJI.get(wtype, DEFAULT_WORD_TYPE_EMOJI)
```

---

## Step 4: Create Session Manager Class

### Create: `session/session_manager.py`

```python
"""Centralized session state management."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime


@dataclass
class QuizSession:
    """State for an active quiz session."""
    quiz_type: str = "meaning"
    current_quiz: Optional[Dict[str, Any]] = None
    question_count: int = 0
    correct_count: int = 0
    wrong_word_ids: List[int] = field(default_factory=list)
    fixed_word_ids: List[int] = field(default_factory=list)
    lesson_id: Optional[int] = None
    source_filter: Optional[str] = None
    quiz_flash: bool = False


@dataclass
class FlashcardSession:
    """State for an active flashcard session."""
    current_card: Optional[Dict[str, Any]] = field(default_factory=dict)
    queue: List[Dict[str, Any]] = field(default_factory=list)
    skipped_ids: List[int] = field(default_factory=list)
    only_new: bool = False
    only_due: bool = False
    hard_only: bool = False
    rate_lock: bool = False


@dataclass
class LTRSession:
    """State for Look-Test-Review sessions."""
    words: List[Dict[str, Any]] = field(default_factory=list)
    index: int = 0
    lesson_id: Optional[int] = None
    word_results: Dict[int, List[bool]] = field(default_factory=dict)
    current_word_id: Optional[int] = None
    state: str = "initial"
    correct_answer: Optional[str] = None
    correct_index: int = 0
    delayed_1: Optional[datetime] = None
    delayed_2: Optional[datetime] = None
    round_num: int = 1
    main_index: int = 0
    main_progress: Dict[str, Any] = field(default_factory=dict)
    delayed_tasks: List[str] = field(default_factory=list)
    retry_stage: Optional[str] = None
    current_word_pos: Optional[int] = None
    round2_started: bool = False
    answer_lock: bool = False


@dataclass 
class UserSession:
    """Complete user session state."""
    # Quiz
    quiz: Optional[QuizSession] = None
    
    # Flashcard
    flashcard: Optional[FlashcardSession] = None
    
    # LTR (Look-Test-Review)
    ltr: Optional[LTRSession] = None
    
    # Study session
    study_words: List[Dict[str, Any]] = field(default_factory=list)
    study_index: int = 0
    study_lesson_id: Optional[int] = None
    
    # TTS
    tts_message: Optional[Tuple[int, int]] = None  # (chat_id, message_id)
    tts_delete_job: Optional[Any] = None
    current_tts_text: Optional[str] = None
    
    # General
    awaiting_input: Optional[str] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    fsrs_guide_shown: bool = False
    grammar_current: Optional[Dict[str, Any]] = None


class SessionManager:
    """Manages user session state with automatic cleanup."""
    
    def __init__(self, context):
        self.context = context
    
    @property
    def session(self) -> UserSession:
        """Get or create session object."""
        if "_session" not in self.context.user_data:
            self.context.user_data["_session"] = UserSession()
        return self.context.user_data["_session"]
    
    def reset(self) -> None:
        """Reset all session state except TTS cleanup."""
        old_job = self.context.user_data.pop("tts_delete_job", None)
        if old_job:
            try:
                old_job.schedule_removal()
            except Exception:
                pass
        
        self.context.user_data.pop("tts_message", None)
        self.context.user_data["_session"] = UserSession()
    
    def clear_tts(self) -> None:
        """Clear TTS-related state."""
        job = self.context.user_data.pop("tts_delete_job", None)
        if job:
            try:
                job.schedule_removal()
            except Exception:
                pass
        
        info = self.context.user_data.pop("tts_message", None)
        if info and self.context.bot:
            try:
                # Would need async context to actually delete
                pass
            except Exception:
                pass
    
    def get_or_create_quiz_session(self) -> QuizSession:
        """Get existing quiz session or create new one."""
        if self.session.quiz is None:
            self.session.quiz = QuizSession()
        return self.session.quiz
    
    def get_or_create_flashcard_session(self) -> FlashcardSession:
        """Get existing flashcard session or create new one."""
        if self.session.flashcard is None:
            self.session.flashcard = FlashcardSession()
        return self.session.flashcard
```

### Update `services.py`:
```python
# Remove SESSION_KEYS list - no longer needed!
# from session.session_manager import SessionManager

def reset_session(context):
    """Legacy function - migrate to SessionManager."""
    manager = SessionManager(context)
    manager.reset()
```

---

## Step 5: Create Callback Data Classes

### Create: `callbacks/__init__.py`

```python
"""Structured callback data for Telegram inline keyboards."""
from abc import ABC, abstractmethod
from typing import ClassVar, Type
from pydantic import BaseModel, ValidationError


class CallbackData(BaseModel, ABC):
    """Base class for all callback data."""
    
    prefix: ClassVar[str]
    
    @abstractmethod
    def pack(self) -> str:
        """Pack callback data into string format."""
        pass
    
    @classmethod
    @abstractmethod
    def unpack(cls, data: str) -> "CallbackData":
        """Unpack string data into callback object."""
        pass


class QuizAnswerCallback(CallbackData):
    """Callback for quiz answer selection."""
    prefix: ClassVar[str] = "quiz_ans"
    answer_index: int
    
    def pack(self) -> str:
        return f"{self.prefix}:{self.answer_index}"
    
    @classmethod
    def unpack(cls, data: str) -> "QuizAnswerCallback":
        prefix, index = data.split(":", 1)
        if prefix != cls.prefix:
            raise ValueError(f"Invalid prefix: expected {cls.prefix}, got {prefix}")
        return cls(answer_index=int(index))


class FlashcardRateCallback(CallbackData):
    """Callback for flashcard rating."""
    prefix: ClassVar[str] = "rate_card"
    rating: int  # 1-4
    word_id: int
    
    def pack(self) -> str:
        return f"{self.prefix}:{self.rating}_{self.word_id}"
    
    @classmethod
    def unpack(cls, data: str) -> "FlashcardRateCallback":
        prefix, payload = data.split(":", 1)
        if prefix != cls.prefix:
            raise ValueError(f"Invalid prefix: {prefix}")
        rating_str, word_id_str = payload.split("_", 1)
        return cls(rating=int(rating_str), word_id=int(word_id_str))


class LessonCallback(CallbackData):
    """Generic callback for lesson-based actions."""
    prefix: ClassVar[str]
    lesson_id: int
    
    def pack(self) -> str:
        return f"{self.prefix}:{self.lesson_id}"
    
    @classmethod
    def unpack(cls, data: str) -> "LessonCallback":
        prefix, lesson_id = data.split(":", 1)
        if prefix != cls.prefix:
            raise ValueError(f"Invalid prefix: {prefix}")
        return cls(lesson_id=int(lesson_id))


# Registry for easy lookup
CALLBACK_TYPES: dict[str, Type[CallbackData]] = {
    "quiz_ans": QuizAnswerCallback,
    "rate_card": FlashcardRateCallback,
    # Add more as you refactor
}


def parse_callback(data: str) -> CallbackData:
    """Parse callback data string into appropriate object."""
    prefix = data.split(":", 1)[0]
    callback_class = CALLBACK_TYPES.get(prefix)
    
    if not callback_class:
        raise ValueError(f"Unknown callback prefix: {prefix}")
    
    return callback_class.unpack(data)
```

### Update `handlers/callback_router.py`:
```python
from callbacks import parse_callback, CallbackData
from pydantic import ValidationError

async def inline_handler(update, context):
    query = update.callback_query
    data = query.data
    
    # ... authorization check ...
    
    # Try to parse as structured callback
    try:
        callback = parse_callback(data)
        await handle_structured_callback(query, context, callback)
        return
    except ValidationError as e:
        logger.error("Invalid callback data structure: %s", e)
        await query.answer("⚠️ خطای داخلی", show_alert=True)
        return
    except ValueError:
        # Fall back to legacy string-based routing
        pass
    
    # ... existing routing logic ...
```

---

## Step 6: Add Basic Unit Tests

### Create: `tests/conftest.py`

```python
"""Pytest configuration and shared fixtures."""
import pytest
import tempfile
from pathlib import Path

from database import Database
from srs_service import FSRSService
from quiz_service import QuizService


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    
    db = Database(str(db_path))
    yield db
    db.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def fsrs_service(temp_db):
    """Create FSRS service with test database."""
    return FSRSService(temp_db)


@pytest.fixture
def quiz_service():
    """Create quiz service (no DB dependency)."""
    return QuizService()
```

### Create: `tests/unit/test_srs_service.py`

```python
"""Tests for the FSRS spaced repetition service."""
import pytest
from datetime import datetime, timezone, timedelta

from srs_service import FSRSState


def test_initial_review_good(fsrs_service):
    """Test that a good first review puts word in review phase."""
    user_id = 1
    word_id = 1
    
    state, interval = fsrs_service.review(user_id, word_id, grade=3)
    
    assert state.reps == 1
    assert state.lapses == 0
    assert state.phase == "review"
    assert interval >= 1
    assert state.stability > 0


def test_failed_review_goes_to_learning(fsrs_service):
    """Test that failing a review puts word in learning phase."""
    user_id = 1
    word_id = 1
    
    # First successful review
    fsrs_service.review(user_id, word_id, grade=3)
    
    # Second review - failed
    state, interval = fsrs_service.review(user_id, word_id, grade=1)
    
    assert state.phase == "learning"
    assert interval == 0  # Immediate review
    assert state.lapses == 1


def test_mastered_phase_after_success(fsrs_service):
    """Test word reaches mastered phase after sufficient success."""
    user_id = 1
    word_id = 1
    
    # Multiple successful reviews
    for _ in range(5):
        state, _ = fsrs_service.review(user_id, word_id, grade=4)
    
    assert state.phase == "mastered"
    assert state.reps >= 3


def test_invalid_grade_defaults_to_good(fsrs_service, caplog):
    """Test that invalid grades default to 3 (good)."""
    user_id = 1
    word_id = 1
    
    state, interval = fsrs_service.review(user_id, word_id, grade=99)
    
    assert "Grade نامعتبر" in caplog.text
    assert state.reps == 1  # Still processes as valid


def test_grade_from_correctness(fsrs_service):
    """Test helper method for converting boolean to grade."""
    assert fsrs_service.grade_from_correctness(True) == 3
    assert fsrs_service.grade_from_correctness(False) == 1
```

### Create: `tests/unit/test_quiz_service.py`

```python
"""Tests for the quiz generation service."""
import pytest

from quiz_service import QuizService


def test_extract_article_and_noun():
    """Test article extraction from German nouns."""
    article, noun = QuizService.extract_article_and_noun("der Tisch")
    assert article == "der"
    assert noun == "Tisch"
    
    article, noun = QuizService.extract_article_and_noun("Haus")
    assert article is None
    assert noun == "Haus"


def test_create_article_quiz(quiz_service):
    """Test article quiz creation."""
    quiz = quiz_service.create_article_quiz(
        article="der",
        german_word="der Tisch",
        persian_meaning="میز"
    )
    
    assert quiz is not None
    assert quiz["type"] == "article"
    assert quiz["correct_answer"] == "der"
    assert len(quiz["options"]) == 3
    assert "der" in quiz["options"]


def test_create_meaning_quiz_with_unique_options(quiz_service):
    """Test meaning quiz ensures unique options."""
    wrong_options = ["صندلی", "میز", "در", "پنجره"]  # Note: duplicate meaning
    
    quiz = quiz_service.create_meaning_quiz(
        german_word="Tisch",
        persian_meaning="میز",
        wrong_options=wrong_options
    )
    
    assert quiz is not None
    assert len(set(quiz["options"])) == len(quiz["options"])  # All unique


def test_cloze_quiz_finds_word_in_sentence(quiz_service):
    """Test cloze quiz correctly identifies word to remove."""
    quiz = quiz_service.create_cloze_quiz(
        german_word="geht",
        persian_meaning="می‌رود",
        example_german="Er geht zur Schule."
    )
    
    assert quiz is not None
    assert "______" in quiz["question"]
    assert quiz["correct_answer"] == "geht"


def test_invalid_cloze_returns_none(quiz_service):
    """Test cloze quiz returns None when word not in sentence."""
    quiz = quiz_service.create_cloze_quiz(
        german_word="läuft",
        persian_meaning="می‌دود",
        example_german="Er geht zur Schule."
    )
    
    assert quiz is None
```

### Run tests:
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

---

## Step 7: Update README.md

### Replace content of `README.md` with:

```markdown
# Deutsch-Bot 🇩🇪

A comprehensive Telegram bot for learning German using spaced repetition, AI-powered content generation, and interactive lessons.

## ✨ Features

- 📚 **Vocabulary Learning**: Organized by books and lessons
- 🎴 **Smart Flashcards**: FSRS algorithm for optimal review timing
- 🤖 **Multiple Quiz Types**: Article, meaning, reverse, and cloze tests
- 📖 **Story-Based Learning**: Contextual learning through stories
- 📐 **Grammar Lessons**: Interactive grammar explanations and exercises
- 🔊 **Text-to-Speech**: Pronunciation practice with native German voice
- 🤖 **AI-Powered**: Dynamic examples and explanations via Groq API

## 🚀 Quick Start

### Prerequisites

- Python 3.9 or higher
- Telegram Bot Token ([get from @BotFather](https://t.me/BotFather))
- Groq API Key (optional, for AI features)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd deutsch-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   
   Create a `.env` file in the root directory:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your credentials:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ADMIN_USER_ID=your_telegram_user_id
   GROQ_API_KEY=your_groq_api_key  # Optional
   BOT_MODE=hybrid  # online, offline, or hybrid
   ```

4. **Run the bot**
   ```bash
   python bot.py
   ```

## ⚙️ Configuration

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token | - | ✅ |
| `ADMIN_USER_ID` | Admin Telegram user ID | `0` | ✅* |
| `ALLOW_PUBLIC_ACCESS` | Allow any user to use bot | `false` | ❌ |
| `GROQ_API_KEY` | Groq API key for LLM features | - | ❌ |
| `BOT_MODE` | `online`, `offline`, or `hybrid` | `hybrid` | ❌ |
| `DB_PATH` | SQLite database path | `words.db` | ❌ |
| `FLASHCARD_QUEUE_LIMIT` | Max cards per session | `20` | ❌ |
| `TTS_AUTO_DELETE_SECONDS` | Auto-delete TTS messages | `60` | ❌ |

\* Required unless `ALLOW_PUBLIC_ACCESS=true`

## 📖 Usage

Once running, interact with your bot on Telegram:

1. Send `/start` to begin
2. Use `/menu` to access the main menu
3. Choose from:
   - 📚 Books & Lessons
   - 🎴 Flashcards
   - 🤖 Quizzes
   - 📊 Dashboard
   - ⚙️ Settings

## 🧪 Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/unit/test_srs_service.py -v
```

### Code Quality

```bash
# Format code
black .
isort .

# Lint
flake8 .

# Type checking
mypy .
```

### Project Structure

```
deutsch-bot/
├── bot.py              # Main entry point
├── config.py           # Configuration management
├── database.py         # Database layer
├── models.py           # Data models
├── services.py         # Service initialization
├── llm_service.py      # LLM integration
├── quiz_service.py     # Quiz logic
├── srs_service.py      # Spaced repetition
├── tts_service.py      # Text-to-speech
├── ui.py               # UI helpers
├── handlers/           # Telegram handlers
│   ├── callback_router.py
│   ├── learning_handlers.py
│   ├── quiz_handlers.py
│   └── ...
├── tests/              # Test suite
└── requirements.txt    # Dependencies
```

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Code Style Guidelines

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write docstrings for public methods
- Include tests for new features
- Use meaningful variable names

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [FSRS](https://github.com/open-spaced-repetition/fsrs) for the spaced repetition algorithm
- [Groq](https://groq.com/) for fast LLM inference
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) for the Telegram API wrapper
- [edge-tts](https://github.com/rany2/edge-tts) for text-to-speech functionality

## 📞 Support

For issues and questions:
- Open an issue on GitHub
- Contact the maintainer

---

**Happy Learning! 🎉**
```

---

## Next Steps

After completing these 7 steps:

1. ✅ Run the bot to ensure everything works
2. ✅ Run the test suite: `pytest tests/ -v`
3. ✅ Continue with medium-priority refactoring tasks from the main report

Remember: **Refactor incrementally**. Make small changes, test thoroughly, then commit.
