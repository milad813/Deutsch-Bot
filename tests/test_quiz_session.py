"""Unit tests for quiz session functionality."""

import pytest
from unittest.mock import Mock, patch
from handlers.quiz.session import (
    QuizQuestion,
    QuizSessionState,
    QuizSessionManager,
    quiz_session_manager,
)


class TestQuizQuestion:
    """Tests for QuizQuestion dataclass."""

    def test_create_question(self):
        """Test creating a quiz question."""
        question = QuizQuestion(
            question_type="multiple_choice",
            question_text="What is the meaning of Haus?",
            correct_answer="house",
            options=["house", "car", "tree", "book"],
            word_id=1,
        )

        assert question.question_type == "multiple_choice"
        assert question.correct_answer == "house"
        assert len(question.options) == 4
        assert question.word_id == 1

    def test_question_with_metadata(self):
        """Test question with metadata."""
        question = QuizQuestion(
            question_type="cloze",
            question_text="Fill in the blank",
            correct_answer="der",
            options=["der", "die", "das"],
            metadata={"difficulty": "hard"},
        )

        assert question.metadata["difficulty"] == "hard"


class TestQuizSessionState:
    """Tests for QuizSessionState dataclass."""

    def test_create_session_state(self):
        """Test creating session state."""
        state = QuizSessionState(
            user_id=123,
            total_questions=10,
        )

        assert state.user_id == 123
        assert state.total_questions == 10
        assert state.current_question == 0
        assert state.correct_answers == 0
        assert state.wrong_answers == 0
        assert state.is_finished is False

    def test_accuracy_zero(self):
        """Test accuracy when no questions answered."""
        state = QuizSessionState(user_id=1, total_questions=10)
        assert state.accuracy == 0.0

    def test_accuracy_calculation(self):
        """Test accuracy calculation."""
        state = QuizSessionState(
            user_id=1,
            total_questions=10,
            correct_answers=8,
            wrong_answers=2,
        )

        assert state.accuracy == 80.0

    def test_progress_percentage(self):
        """Test progress percentage calculation."""
        state = QuizSessionState(
            user_id=1,
            total_questions=10,
            current_question=5,
        )

        assert state.progress_percentage == 50

    def test_progress_zero_total(self):
        """Test progress with zero total questions."""
        state = QuizSessionState(user_id=1, total_questions=0)
        assert state.progress_percentage == 0


class TestQuizSessionManager:
    """Tests for QuizSessionManager class."""

    @pytest.fixture
    def manager(self):
        """Create fresh manager instance."""
        return QuizSessionManager()

    def test_create_session(self, manager):
        """Test creating a new session."""
        session = manager.create_session(user_id=123, total_questions=10)

        assert session.user_id == 123
        assert session.total_questions == 10
        assert 123 in manager.sessions

    def test_create_session_replaces_existing(self, manager):
        """Test that creating session replaces existing one."""
        manager.create_session(user_id=123, total_questions=5)
        manager.create_session(user_id=123, total_questions=10)

        session = manager.get_session(123)
        assert session.total_questions == 10

    def test_get_session(self, manager):
        """Test getting session."""
        manager.create_session(user_id=123, total_questions=10)

        session = manager.get_session(123)
        assert session is not None
        assert session.user_id == 123

    def test_get_nonexistent_session(self, manager):
        """Test getting nonexistent session."""
        session = manager.get_session(999)
        assert session is None

    def test_advance_question_correct(self, manager):
        """Test advancing question with correct answer."""
        manager.create_session(user_id=123, total_questions=10)

        session = manager.advance_question(123, is_correct=True)

        assert session.current_question == 1
        assert session.correct_answers == 1
        assert session.wrong_answers == 0

    def test_advance_question_wrong(self, manager):
        """Test advancing question with wrong answer."""
        manager.create_session(user_id=123, total_questions=10)

        session = manager.advance_question(123, is_correct=False)

        assert session.current_question == 1
        assert session.correct_answers == 0
        assert session.wrong_answers == 1

    def test_advance_completes_session(self, manager):
        """Test that session completes when all questions answered."""
        manager.create_session(user_id=123, total_questions=3)

        manager.advance_question(123, True)
        manager.advance_question(123, True)
        session = manager.advance_question(123, True)

        assert session.is_finished is True

    def test_record_question(self, manager):
        """Test recording question details."""
        manager.create_session(user_id=123, total_questions=10)

        manager.record_question(
            user_id=123,
            question_type="multiple_choice",
            word_id=1,
            is_correct=True,
            metadata={"difficulty": "easy"},
        )

        session = manager.get_session(123)
        assert len(session.question_history) == 1
        assert session.question_history[0]["question_type"] == "multiple_choice"
        assert session.question_history[0]["word_id"] == 1

    def test_end_session(self, manager):
        """Test ending session."""
        manager.create_session(user_id=123, total_questions=10)

        session = manager.end_session(123)

        assert session is not None
        assert 123 not in manager.sessions

    def test_end_nonexistent_session(self, manager):
        """Test ending nonexistent session."""
        session = manager.end_session(999)
        assert session is None

    def test_get_summary(self, manager):
        """Test getting session summary."""
        manager.create_session(user_id=123, total_questions=10)
        manager.advance_question(123, True)
        manager.advance_question(123, False)
        manager.advance_question(123, True)

        summary = manager.get_summary(123)

        assert summary["total_questions"] == 10
        assert summary["answered"] == 3
        assert summary["correct"] == 2
        assert summary["wrong"] == 1
        assert summary["accuracy"] == pytest.approx(66.67, rel=0.1)

    def test_get_summary_nonexistent(self, manager):
        """Test getting summary for nonexistent session."""
        summary = manager.get_summary(999)
        assert summary is None


class TestGlobalInstance:
    """Tests for global quiz_session_manager instance."""

    def test_global_instance_exists(self):
        """Test that global instance exists."""
        from handlers.quiz.session import quiz_session_manager

        assert quiz_session_manager is not None
        assert isinstance(quiz_session_manager, QuizSessionManager)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
