"""Unit tests for flashcard functionality."""

from unittest.mock import MagicMock, Mock, patch, AsyncMock
import pytest
from collections import deque

# Import the actual modules
from handlers.learning.flashcard_session import (
    FlashcardSessionManager,
    _pending_examples,
    _render_flashcard_front,
    _handle_flashcard_rating,
)
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

    def test_create_session_empty(self, manager):
        """Test creating a new flashcard session with empty queue."""
        with patch("services.db") as mock_db:
            mock_db.get_due_word_objects.return_value = []
            mock_db.get_new_word_objects.return_value = []

            words = manager.create_session(user_id=123, hard_only=False)

            assert len(words) == 0
            assert 123 in manager.sessions
            assert manager.sessions[123]["queue"] == deque()

    def test_create_session_with_words(self, manager, sample_word):
        """Test creating a session with words."""
        with patch("services.db") as mock_db:
            mock_db.get_due_word_objects.return_value = [sample_word]

            words = manager.create_session(user_id=123, hard_only=False)

            assert len(words) == 1
            assert words[0].id == 1
            assert 123 in manager.sessions
            assert len(manager.sessions[123]["queue"]) == 1

    def test_create_hard_only_session(self, manager, sample_word):
        """Test creating a hard-only session."""
        with patch("services.db") as mock_db:
            mock_db.get_hard_due_word_objects.return_value = [sample_word]

            words = manager.create_session(user_id=123, hard_only=True)

            assert len(words) == 1
            assert manager.sessions[123]["hard_only"] is True

    def test_get_next_word(self, manager, sample_word):
        """Test getting next word from queue."""
        manager.sessions[123] = {
            "queue": deque([sample_word]),
            "skipped_ids": set(),
            "completed_count": 0,
            "current_word": None,
        }

        word = manager.get_next_word(123)
        assert word.id == 1
        assert len(manager.sessions[123]["queue"]) == 0
        assert manager.sessions[123]["current_word"].id == 1

    def test_get_next_word_empty_queue(self, manager):
        """Test getting next word from empty queue."""
        manager.sessions[123] = {
            "queue": deque(),
            "skipped_ids": set(),
            "completed_count": 0,
            "current_word": None,
        }

        word = manager.get_next_word(123)
        assert word is None

    def test_skip_word(self, manager, sample_word):
        """Test skipping a word."""
        manager.sessions[123] = {
            "queue": deque(),
            "skipped_ids": set(),
            "completed_count": 0,
            "current_word": sample_word,
        }

        manager.skip_word(123, sample_word)
        assert sample_word.id in manager.sessions[123]["skipped_ids"]
        assert manager.sessions[123]["current_word"] is None

    def test_complete_word(self, manager):
        """Test completing a word."""
        manager.sessions[123] = {
            "queue": deque(),
            "skipped_ids": set(),
            "completed_count": 0,
            "current_word": None,
        }

        manager.complete_word(123)
        assert manager.sessions[123]["completed_count"] == 1

    def test_is_session_complete_no_session(self, manager):
        """Test session completion when no session exists."""
        assert manager.is_session_complete(123) is True

    def test_is_session_complete_empty_queue(self, manager):
        """Test session completion with empty queue."""
        manager.sessions[123] = {
            "queue": deque(),
            "skipped_ids": set(),
            "completed_count": 0,
            "current_word": None,
        }
        assert manager.is_session_complete(123) is True

    def test_is_session_complete_with_words(self, manager, sample_word):
        """Test session completion with words remaining."""
        manager.sessions[123] = {
            "queue": deque([sample_word]),
            "skipped_ids": set(),
            "completed_count": 0,
            "current_word": None,
        }
        assert manager.is_session_complete(123) is False

    def test_end_session(self, manager):
        """Test ending a session."""
        manager.sessions[123] = {"queue": deque()}
        manager.end_session(123)
        assert 123 not in manager.sessions

    def test_end_nonexistent_session(self, manager):
        """Test ending nonexistent session."""
        # Should not raise
        manager.end_session(999)
        assert 999 not in manager.sessions


class TestFlashcardDisplay:
    """Tests for flashcard display formatting."""

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

    def test_format_front_text_basic(self, sample_word):
        """Test formatting front of card."""
        from handlers.learning.flashcard_session import _format_front_text
        
        text = _format_front_text(sample_word)
        assert "<b>" in text
        assert "Haus" in text

    def test_format_front_text_with_article(self, sample_word):
        """Test formatting front with article."""
        from handlers.learning.flashcard_session import _format_front_text
        
        text = _format_front_text(sample_word, show_article="das")
        assert "das Haus" in text

    def test_format_back_text(self, sample_word):
        """Test formatting back of card."""
        from handlers.learning.flashcard_session import _format_back_text
        
        text = _format_back_text(sample_word)
        assert "خانه" in text
        assert "English:" in text or "house" in text

    def test_pending_examples_cleanup(self):
        """Test that old pending examples are cleaned up."""
        import time
        from handlers.learning.flashcard_session import _pending_examples
        
        # Add old entry
        old_key = (999, "A1")
        _pending_examples[old_key] = time.time() - 400  # 6+ minutes ago
        
        # Add recent entry
        recent_key = (888, "A1")
        _pending_examples[recent_key] = time.time()
        
        # Cleanup should remove old entries
        now = time.time()
        for key in list(_pending_examples.keys()):
            if now - _pending_examples[key] > 300:
                del _pending_examples[key]
        
        assert old_key not in _pending_examples
        assert recent_key in _pending_examples


class TestFlashcardIntegration:
    """Integration tests for flashcard flow."""

    @pytest.mark.asyncio
    async def test_full_flashcard_flow(self):
        """Test complete flashcard session flow."""
        from handlers.learning.flashcard_session import FlashcardSessionManager
        
        manager = FlashcardSessionManager()
        word = Word(id=1, german="Haus", persian="خانه", article="das", word_type="noun")
        
        # Create session
        with patch("services.db") as mock_db:
            mock_db.get_due_word_objects.return_value = [word]
            words = manager.create_session(user_id=123)
            assert len(words) == 1
        
        # Get next word
        next_word = manager.get_next_word(123)
        assert next_word.id == 1
        
        # Complete word
        manager.complete_word(123)
        assert manager.sessions[123]["completed_count"] == 1
        
        # End session
        manager.end_session(123)
        assert 123 not in manager.sessions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
