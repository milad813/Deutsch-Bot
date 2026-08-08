"""Unit tests for LTR session functionality."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from handlers.learning.ltr_session import (LTRSessionManager,
                                           _ltr_answer_keyboard,
                                           _make_ltr_options,
                                           _sample_unique_ltr)
from models import Word


class TestLTRSessionManager:
    """Tests for LTRSessionManager class."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock context object."""
        context = Mock()
        context.user_data = {}
        context.bot_user_id = 123
        return context

    @pytest.fixture
    def sample_words(self):
        """Create sample words for testing."""
        return [
            Word(id=1, german="Haus", persian="خانه", article="das", word_type="noun"),
            Word(id=2, german="Buch", persian="کتاب", article="das", word_type="noun"),
            Word(id=3, german="Tisch", persian="میز", article="der", word_type="noun"),
        ]

    def test_initialize_session(self, mock_context, sample_words):
        """Test initializing an LTR session."""
        manager = LTRSessionManager(mock_context)

        with patch("handlers.learning.ltr_session.db") as mock_db:
            result = manager.initialize(
                user_id=123,
                lesson_id=1,
                weak_words=sample_words[:1],
                new_words=sample_words[1:],
            )

            assert result is True
            assert mock_context.user_data["ltr_words"] == [1, 2, 3]
            assert mock_context.user_data["ltr_lesson_id"] == 1
            assert mock_context.user_data["ltr_main_index"] == 0
            assert mock_context.user_data["ltr_user_id"] == 123

    def test_initialize_no_words(self, mock_context):
        """Test initializing with no words."""
        manager = LTRSessionManager(mock_context)

        result = manager.initialize(
            lesson_id=1,
            weak_words=[],
            new_words=[],
        )

        assert result is False

    def test_get_current_word(self, mock_context, sample_words):
        """Test getting current word."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_words"] = [1, 2, 3]
        mock_context.user_data["ltr_main_index"] = 0

        with patch("handlers.learning.ltr_session.db") as mock_db:
            mock_db.get_word_by_id.return_value = sample_words[0]

            word = manager.get_current_word()

            assert word.id == 1
            mock_db.get_word_by_id.assert_called_once_with(1)

    def test_advance_to_next_word(self, mock_context):
        """Test advancing to next word."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_words"] = [1, 2, 3]
        mock_context.user_data["ltr_main_index"] = 0
        mock_context.user_data["ltr_main_progress"] = 0

        # Advance first time
        has_more = manager.advance_to_next_word()
        assert has_more is True
        assert mock_context.user_data["ltr_main_index"] == 1

        # Advance second time
        has_more = manager.advance_to_next_word()
        assert has_more is True
        assert mock_context.user_data["ltr_main_index"] == 2

        # Advance third time (no more words)
        has_more = manager.advance_to_next_word()
        assert has_more is False

    def test_get_progress_info(self, mock_context):
        """Test getting progress information."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_words"] = [1, 2, 3, 4, 5]
        mock_context.user_data["ltr_main_index"] = 2

        progress = manager.get_progress_info()

        assert progress["position"] == 3
        assert progress["total"] == 5
        assert "progress_bar" in progress

    def test_schedule_delayed_task(self, mock_context):
        """Test scheduling delayed tasks."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_main_progress"] = 0

        manager.schedule_delayed_task(word_id=1, stage="test_delayed_1", delay_main=2)

        tasks = mock_context.user_data["ltr_delayed_tasks"]
        assert len(tasks) == 1
        assert tasks[0]["word_id"] == 1
        assert tasks[0]["stage"] == "test_delayed_1"
        assert tasks[0]["due_after"] == 2

    def test_get_due_delayed_task(self, mock_context):
        """Test getting due delayed task."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_main_progress"] = 3
        mock_context.user_data["ltr_delayed_tasks"] = [
            {"word_id": 1, "stage": "test1", "due_after": 2},
            {"word_id": 2, "stage": "test2", "due_after": 5},
        ]

        task = manager.get_due_delayed_task()

        assert task is not None
        assert task["word_id"] == 1
        assert len(mock_context.user_data["ltr_delayed_tasks"]) == 1

    def test_record_word_result(self, mock_context):
        """Test recording word results."""
        manager = LTRSessionManager(mock_context)

        manager.record_word_result(1, True)
        manager.record_word_result(1, False)
        manager.record_word_result(2, True)

        results = mock_context.user_data.get("ltr_word_results", {})
        assert len(results.get(1, [])) == 2
        assert len(results.get(2, [])) == 1

    def test_get_session_summary(self, mock_context):
        """Test getting session summary."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_words"] = [1, 2, 3, 4, 5]
        mock_context.user_data["ltr_wrong_in_session"] = [2, 4]

        summary = manager.get_session_summary()

        assert summary["total_words"] == 5
        assert summary["wrong_words"] == 2
        assert summary["correct_words"] == 3
        assert summary["accuracy"] == 60

    def test_clear_session(self, mock_context):
        """Test clearing session data."""
        manager = LTRSessionManager(mock_context)
        mock_context.user_data["ltr_words"] = [1, 2, 3]
        mock_context.user_data["ltr_lesson_id"] = 1
        mock_context.user_data["ltr_wrong_in_session"] = [2]

        manager.clear_session()

        assert "ltr_words" not in mock_context.user_data
        assert "ltr_lesson_id" not in mock_context.user_data
        assert "ltr_wrong_in_session" not in mock_context.user_data


class TestHelperFunctions:
    """Tests for LTR helper functions."""

    def test_sample_unique_ltr(self):
        """Test sampling unique items."""
        primary = ["a", "b", "c"]
        secondary = ["d", "e", "f"]

        result = _sample_unique_ltr(primary, secondary, count=4)

        assert len(result) == 4
        # All items should be from the combined lists
        assert all(item in primary + secondary for item in result)

    def test_sample_unique_ltr_duplicates(self):
        """Test sampling handles duplicates."""
        primary = ["a", "a", "b"]
        secondary = ["a", "c"]

        result = _sample_unique_ltr(primary, secondary, count=10)

        # Should have no duplicates
        assert len(result) == len(set(result))

    def test_make_ltr_options(self):
        """Test creating multiple choice options."""
        correct = "correct_answer"
        wrongs = ["wrong1", "wrong2", "wrong3"]

        options = _make_ltr_options(correct, wrongs, total=4)

        assert len(options) == 4
        assert correct in options

    def test_make_ltr_options_empty_correct(self):
        """Test with empty correct answer."""
        options = _make_ltr_options("", ["wrong1"], total=4)
        assert options is None

    def test_make_ltr_options_few_wrongs(self):
        """Test with fewer wrong options than needed."""
        correct = "correct"
        wrongs = ["wrong1"]

        options = _make_ltr_options(correct, wrongs, total=4, min_options=1)

        assert len(options) >= 1
        assert correct in options

    def test_ltr_answer_keyboard(self):
        """Test creating answer keyboard."""
        options = ["option_a", "option_b", "option_c"]

        keyboard = _ltr_answer_keyboard(options)

        assert keyboard.inline_keyboard
        # Should have option buttons + exit button
        assert len(keyboard.inline_keyboard) >= 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
