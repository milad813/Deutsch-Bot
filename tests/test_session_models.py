"""Tests for session models."""

from models import (
    CallbackPrefix,
    FlashcardSession,
    LTRSession,
    QuizSession,
    QuizType,
    UserSession,
)


class TestQuizType:
    """Test QuizType enum."""

    def test_quiz_type_values(self):
        """Test that quiz types have correct values."""
        assert QuizType.ARTICLE.value == "article"
        assert QuizType.MEANING.value == "meaning"
        assert QuizType.PLURAL.value == "plural"
        assert QuizType.VERB.value == "verb"
        assert QuizType.ADJECTIVE.value == "adjective"
        assert QuizType.COLLOCATION.value == "collocation"

    def test_quiz_type_comparison(self):
        """Test that quiz types can be compared as strings."""
        assert QuizType.ARTICLE == "article"
        assert "meaning" == QuizType.MEANING


class TestCallbackPrefix:
    """Test CallbackPrefix enum."""

    def test_callback_prefixes_exist(self):
        """Test that common callback prefixes exist."""
        assert CallbackPrefix.QUIZ_TYPE.value == "quiz_type:"
        assert CallbackPrefix.QUIZ_ANS.value == "quiz_ans:"
        assert CallbackPrefix.FLASHCARD_LESSON.value == "flashcard_lesson:"
        assert CallbackPrefix.STORY_VIEW.value == "story_view:"


class TestQuizSession:
    """Test QuizSession dataclass."""

    def test_create_quiz_session(self):
        """Test creating a quiz session with required fields."""
        session = QuizSession(quiz_type="article", total_questions=10)

        assert session.quiz_type == "article"
        assert session.total_questions == 10
        assert session.current_index == 0
        assert session.correct_count == 0
        assert session.wrong_count == 0
        assert session.question_ids == []
        assert session.source_filter is None
        assert session.lesson_id is None

    def test_quiz_session_with_optional_fields(self):
        """Test creating a quiz session with all fields."""
        session = QuizSession(
            quiz_type="meaning",
            total_questions=20,
            current_index=5,
            correct_count=3,
            wrong_count=2,
            question_ids=[1, 2, 3, 4, 5],
            source_filter="weak",
            lesson_id=10,
        )

        assert session.quiz_type == "meaning"
        assert session.total_questions == 20
        assert session.current_index == 5
        assert session.correct_count == 3
        assert session.wrong_count == 2
        assert session.question_ids == [1, 2, 3, 4, 5]
        assert session.source_filter == "weak"
        assert session.lesson_id == 10


class TestSessionIntegration:
    """Integration tests for session models."""

    def test_quiz_workflow(self):
        """Test a typical quiz workflow."""
        # Create session
        session = QuizSession(quiz_type="article", total_questions=10)

        # Simulate answering questions
        session.current_index = 1
        session.correct_count = 1

        session.current_index = 2
        session.wrong_count = 1

        session.current_index = 3
        session.correct_count = 2

        assert session.current_index == 3
        assert session.correct_count == 2
        assert session.wrong_count == 1
        assert session.total_questions == 10
