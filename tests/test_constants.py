"""Unit tests for constants module."""

import pytest

from constants import (
    BTN_SHOW_MEANING,
    ERROR_GENERIC,
    FLASHCARD_NEW_LIMIT,
    FLASHCARD_QUEUE_LIMIT,
    BotMode,
    FlashcardState,
    LTRStage,
    QuizType,
)


class TestBotMode:
    """Tests for BotMode enum."""

    def test_bot_mode_values(self):
        """Test BotMode enum values."""
        assert BotMode.ONLINE.value == "online"
        assert BotMode.OFFLINE.value == "offline"
        assert BotMode.HYBRID.value == "hybrid"

    def test_bot_mode_from_string(self):
        """Test creating BotMode from string."""
        assert BotMode("online") == BotMode.ONLINE
        assert BotMode("offline") == BotMode.OFFLINE


class TestQuizType:
    """Tests for QuizType enum."""

    def test_quiz_type_values(self):
        """Test QuizType enum values."""
        assert QuizType.ARTICLE.value == "article"
        assert QuizType.MEANING.value == "meaning"
        assert QuizType.REVERSE.value == "reverse"
        assert QuizType.CLOZE.value == "cloze"


class TestConfigurationConstants:
    """Tests for configuration constants."""

    def test_flashcard_limits(self):
        """Test flashcard limit constants."""
        assert FLASHCARD_QUEUE_LIMIT == 20
        assert FLASHCARD_NEW_LIMIT == 5
        assert FLASHCARD_QUEUE_LIMIT > FLASHCARD_NEW_LIMIT

    def test_limits_are_positive(self):
        """Test that limits are positive integers."""
        assert FLASHCARD_QUEUE_LIMIT > 0
        assert FLASHCARD_NEW_LIMIT > 0


class TestErrorMessages:
    """Tests for error message constants."""

    def test_error_messages_not_empty(self):
        """Test that error messages are not empty."""
        assert ERROR_GENERIC
        assert len(ERROR_GENERIC) > 0

    def test_error_messages_contain_emoji(self):
        """Test that error messages contain emoji indicators."""
        assert "⚠️" in ERROR_GENERIC


class TestButtonLabels:
    """Tests for button label constants."""

    def test_button_labels_not_empty(self):
        """Test that button labels are not empty."""
        assert BTN_SHOW_MEANING
        assert len(BTN_SHOW_MEANING) > 0

    def test_button_labels_contain_emoji(self):
        """Test that button labels contain emoji."""
        assert "👀" in BTN_SHOW_MEANING
