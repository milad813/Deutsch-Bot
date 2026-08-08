"""Unit tests for flashcard functionality."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from handlers.flashcard.display import FlashcardDisplay
from handlers.flashcard.session import FlashcardSessionManager
from models import Word


class TestFlashcardSessionManager:
    """Tests for FlashcardSessionManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh session manager instance."""
        return FlashcardSessionManager()

    @pytest.fixture
    def sample_word(self):
        """Create a sample word for testing."""
        return Word(
            id=1, german="Haus", persian="خانه", article="das", word_type="noun"
        )

    def test_create_session(self, manager, sample_word):
        """Test creating a new flashcard session."""
        with patch("handlers.flashcard.session.db") as mock_db:
            mock_db.get_hard_due_word_objects.return_value = [sample_word]

            words = manager.create_session(user_id=123, hard_only=True)

            assert len(words) == 1
            assert words[0].id == 1
            assert manager.sessions[123]["queue"]
            assert manager.sessions[123]["hard_only"] is True

    def test_get_next_word(self, manager, sample_word):
        """Test getting next word from queue."""
        from collections import deque

        manager.sessions[123] = {
            "queue": deque([sample_word]),
            "skipped_ids": set(),
            "completed_count": 0,
        }

        word = manager.get_next_word(123)
        assert word.id == 1
        assert len(manager.sessions[123]["queue"]) == 0

    def test_skip_word(self, manager, sample_word):
        """Test skipping a word."""
        manager.sessions[123] = {
            "queue": [],
            "skipped_ids": set(),
            "completed_count": 0,
        }

        manager.skip_word(123, sample_word)
        assert sample_word.id in manager.sessions[123]["skipped_ids"]

    def test_complete_word(self, manager):
        """Test completing a word."""
        manager.sessions[123] = {
            "queue": [],
            "skipped_ids": set(),
            "completed_count": 0,
        }

        manager.complete_word(123)
        assert manager.sessions[123]["completed_count"] == 1

    def test_is_session_complete(self, manager):
        """Test checking session completion."""
        # No session exists
        assert manager.is_session_complete(123) is True

        # Session with empty queue
        manager.sessions[123] = {
            "queue": [],
            "skipped_ids": set(),
            "completed_count": 0,
        }
        assert manager.is_session_complete(123) is True

        # Session with words remaining
        manager.sessions[123]["queue"] = [Mock()]
        assert manager.is_session_complete(123) is False

    def test_end_session(self, manager):
        """Test ending a session."""
        manager.sessions[123] = {"queue": []}
        manager.end_session(123)
        assert 123 not in manager.sessions


class TestFlashcardDisplay:
    """Tests for FlashcardDisplay class."""

    @pytest.fixture
    def display(self):
        """Create display instance."""
        return FlashcardDisplay()

    @pytest.fixture
    def sample_word(self):
        """Create a sample word for testing."""
        return Word(
            id=1,
            german="Haus",
            persian="خانه",
            article="das",
            word_type="noun",
            english_meaning="house",
            example_de="Das Haus ist groß.",
            example_fa="خانه بزرگ است.",
        )

    def test_format_front_text(self, display, sample_word):
        """Test formatting front of card."""
        text = display.format_front_text(sample_word)
        assert "<b>" in text
        assert "Haus" in text

    def test_format_front_text_with_article(self, display, sample_word):
        """Test formatting front with article."""
        text = display.format_front_text(sample_word, "das")
        assert "das Haus" in text

    def test_format_back_text(self, display, sample_word):
        """Test formatting back of card."""
        text = display.format_back_text(sample_word)
        assert "خانه" in text
        assert "English:" in text
        assert "house" in text

    def test_create_front_keyboard(self, display, sample_word):
        """Test creating front keyboard."""
        keyboard = display.create_front_keyboard(sample_word)
        assert keyboard.inline_keyboard

        # Check button labels
        buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("🔊" in b for b in buttons)
        assert any("👀" in b for b in buttons)
        assert any("⏭️" in b for b in buttons)

    def test_create_back_keyboard(self, display, sample_word):
        """Test creating back keyboard with ratings."""
        keyboard = display.create_back_keyboard(sample_word)
        assert keyboard.inline_keyboard

        # Check rating buttons
        buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("Again" in b for b in buttons)
        assert any("Hard" in b for b in buttons)
        assert any("Good" in b for b in buttons)
        assert any("Easy" in b for b in buttons)
