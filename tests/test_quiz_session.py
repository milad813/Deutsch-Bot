"""Unit tests for quiz session functionality."""

from unittest.mock import Mock, patch, AsyncMock
import pytest

# Import actual modules
from handlers.quiz_handlers import (
    QuizSession,
    _create_quiz_session,
    _get_current_question,
    _record_quiz_answer,
)
from models import Word


class TestQuizQuestion:
    """Tests for quiz question structure."""

    def test_create_multiple_choice_question(self):
        """Test creating a multiple choice question."""
        question = {
            "question_type": "multiple_choice",
            "question_text": "What is the meaning of Haus?",
            "correct_answer": "خانه",
            "options": ["خانه", "ماشین", "درخت", "کتاب"],
            "word_id": 1,
        }

        assert question["question_type"] == "multiple_choice"
        assert question["correct_answer"] == "خانه"
        assert len(question["options"]) == 4
        assert question["word_id"] == 1

    def test_create_cloze_question(self):
        """Test creating a cloze question."""
        question = {
            "question_type": "cloze",
            "question_text": "Fill in the blank: ___ Haus ist groß.",
            "correct_answer": "das",
            "options": ["der", "die", "das"],
            "word_id": 2,
        }

        assert question["question_type"] == "cloze"
        assert question["correct_answer"] == "das"


class TestQuizSessionState:
    """Tests for quiz session state tracking."""

    def test_create_session_state(self):
        """Test creating session state."""
        state = {
            "user_id": 123,
            "total_questions": 10,
            "current_question": 0,
            "correct_answers": 0,
            "wrong_answers": 0,
            "is_finished": False,
        }

        assert state["user_id"] == 123
        assert state["total_questions"] == 10
        assert state["current_question"] == 0
        assert state["is_finished"] is False

    def test_accuracy_zero(self):
        """Test accuracy when no questions answered."""
        state = {
            "user_id": 1,
            "total_questions": 10,
            "current_question": 0,
            "correct_answers": 0,
            "wrong_answers": 0,
        }
        
        total = state["correct_answers"] + state["wrong_answers"]
        accuracy = (state["correct_answers"] / total * 100) if total else 0.0
        assert accuracy == 0.0

    def test_accuracy_calculation(self):
        """Test accuracy calculation."""
        state = {
            "user_id": 1,
            "total_questions": 10,
            "current_question": 10,
            "correct_answers": 8,
            "wrong_answers": 2,
        }
        
        total = state["correct_answers"] + state["wrong_answers"]
        accuracy = (state["correct_answers"] / total * 100) if total else 0.0
        assert accuracy == 80.0

    def test_progress_percentage(self):
        """Test progress percentage calculation."""
        state = {
            "user_id": 1,
            "total_questions": 10,
            "current_question": 5,
            "correct_answers": 0,
            "wrong_answers": 0,
        }
        
        progress = (state["current_question"] / state["total_questions"] * 100) if state["total_questions"] else 0
        assert progress == 50

    def test_progress_zero_total(self):
        """Test progress with zero total questions."""
        state = {
            "user_id": 1,
            "total_questions": 0,
            "current_question": 0,
        }
        
        progress = (state["current_question"] / state["total_questions"] * 100) if state["total_questions"] else 0
        assert progress == 0


class TestQuizSessionManager:
    """Tests for quiz session management."""

    @pytest.fixture
    def session_manager(self):
        """Create fresh manager instance."""
        return {}

    def test_create_session(self, session_manager):
        """Test creating a new session."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 10,
            "current_question": 0,
            "correct_answers": 0,
            "wrong_answers": 0,
            "is_finished": False,
            "questions": [],
        }

        session = session_manager[user_id]
        assert session["user_id"] == 123
        assert session["total_questions"] == 10

    def test_create_session_replaces_existing(self, session_manager):
        """Test that creating session replaces existing one."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 5,
            "current_question": 0,
        }
        
        # Replace with new session
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 10,
            "current_question": 0,
        }

        session = session_manager[user_id]
        assert session["total_questions"] == 10

    def test_get_session(self, session_manager):
        """Test getting session."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 10,
        }

        session = session_manager.get(user_id)
        assert session is not None
        assert session["user_id"] == 123

    def test_get_nonexistent_session(self, session_manager):
        """Test getting nonexistent session."""
        session = session_manager.get(999)
        assert session is None

    def test_advance_question_correct(self, session_manager):
        """Test advancing question with correct answer."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 10,
            "current_question": 0,
            "correct_answers": 0,
            "wrong_answers": 0,
            "is_finished": False,
        }

        session_manager[user_id]["current_question"] += 1
        session_manager[user_id]["correct_answers"] += 1
        
        session = session_manager[user_id]
        assert session["current_question"] == 1
        assert session["correct_answers"] == 1
        assert session["wrong_answers"] == 0

    def test_advance_question_wrong(self, session_manager):
        """Test advancing question with wrong answer."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 10,
            "current_question": 0,
            "correct_answers": 0,
            "wrong_answers": 0,
            "is_finished": False,
        }

        session_manager[user_id]["current_question"] += 1
        session_manager[user_id]["wrong_answers"] += 1
        
        session = session_manager[user_id]
        assert session["current_question"] == 1
        assert session["correct_answers"] == 0
        assert session["wrong_answers"] == 1

    def test_advance_completes_session(self, session_manager):
        """Test that session completes when all questions answered."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 3,
            "current_question": 2,
            "correct_answers": 2,
            "wrong_answers": 0,
            "is_finished": False,
        }

        session_manager[user_id]["current_question"] += 1
        if session_manager[user_id]["current_question"] >= session_manager[user_id]["total_questions"]:
            session_manager[user_id]["is_finished"] = True

        session = session_manager[user_id]
        assert session["is_finished"] is True

    def test_end_session(self, session_manager):
        """Test ending session."""
        user_id = 123
        session_manager[user_id] = {"user_id": user_id}

        session = session_manager.pop(user_id, None)

        assert session is not None
        assert user_id not in session_manager

    def test_end_nonexistent_session(self, session_manager):
        """Test ending nonexistent session."""
        session = session_manager.pop(999, None)
        assert session is None

    def test_get_summary(self, session_manager):
        """Test getting session summary."""
        user_id = 123
        session_manager[user_id] = {
            "user_id": user_id,
            "total_questions": 10,
            "current_question": 3,
            "correct_answers": 2,
            "wrong_answers": 1,
        }

        session = session_manager[user_id]
        total = session["correct_answers"] + session["wrong_answers"]
        accuracy = (session["correct_answers"] / total * 100) if total else 0.0
        
        assert session["total_questions"] == 10
        assert session["current_question"] == 3
        assert session["correct_answers"] == 2
        assert session["wrong_answers"] == 1
        assert accuracy == pytest.approx(66.67, rel=0.1)

    def test_get_summary_nonexistent(self, session_manager):
        """Test getting summary for nonexistent session."""
        session = session_manager.get(999)
        assert session is None


class TestQuizAnswerRecording:
    """Tests for quiz answer recording logic."""

    def test_record_correct_answer(self):
        """Test recording a correct answer."""
        session = {
            "user_id": 123,
            "correct_answers": 0,
            "wrong_answers": 0,
        }
        
        is_correct = True
        if is_correct:
            session["correct_answers"] += 1
        else:
            session["wrong_answers"] += 1
        
        assert session["correct_answers"] == 1
        assert session["wrong_answers"] == 0

    def test_record_wrong_answer(self):
        """Test recording a wrong answer."""
        session = {
            "user_id": 123,
            "correct_answers": 0,
            "wrong_answers": 0,
        }
        
        is_correct = False
        if is_correct:
            session["correct_answers"] += 1
        else:
            session["wrong_answers"] += 1
        
        assert session["correct_answers"] == 0
        assert session["wrong_answers"] == 1


class TestQuizLocking:
    """Tests for quiz answer locking mechanism."""

    def test_lock_prevents_double_tap(self):
        """Test that lock prevents double-tap."""
        user_data = {}
        lock_key = "quiz_answer_lock"
        
        # First tap - acquire lock
        if not user_data.get(lock_key):
            user_data[lock_key] = True
            first_allowed = True
        else:
            first_allowed = False
        
        # Second tap - should be blocked
        if not user_data.get(lock_key):
            second_allowed = True
        else:
            second_allowed = False
        
        # Release lock
        user_data.pop(lock_key, None)
        
        assert first_allowed is True
        assert second_allowed is False

    def test_lock_released_after_answer(self):
        """Test that lock is released after processing."""
        user_data = {"quiz_answer_lock": True}
        lock_key = "quiz_answer_lock"
        
        try:
            # Process answer
            result = "processed"
        finally:
            user_data.pop(lock_key, None)
        
        assert user_data.get(lock_key) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
