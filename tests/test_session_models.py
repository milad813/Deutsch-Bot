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


class TestFlashcardSession:
    """Test FlashcardSession dataclass."""

    def test_create_flashcard_session(self):
        """Test creating a flashcard session."""
        session = FlashcardSession()

        assert session.words == []
        assert session.current_index == 0
        assert session.skipped_ids == []
        assert session.only_new is False
        assert session.only_due is False
        assert session.hard_only is False
        assert session.lesson_id is None

    def test_flashcard_session_with_words(self):
        """Test creating a flashcard session with words."""
        words = [{"id": 1}, {"id": 2}, {"id": 3}]
        session = FlashcardSession(words=words, only_due=True, lesson_id=5)

        assert session.words == words
        assert session.current_index == 0
        assert session.only_due is True
        assert session.lesson_id == 5


class TestLTRSession:
    """Test LTRSession dataclass."""

    def test_create_ltr_session(self):
        """Test creating an LTR session."""
        session = LTRSession(lesson_id=1)

        assert session.lesson_id == 1
        assert session.weak_words == []
        assert session.new_words == []
        assert session.main_index == 0
        assert session.state == "intro"
        assert session.round2_started is False


class TestUserSession:
    """Test UserSession dataclass."""

    def test_create_empty_session(self):
        """Test creating an empty user session."""
        session = UserSession()

        assert session.quiz is None
        assert session.flashcard is None
        assert session.ltr is None
        assert session.story is None
        assert session.grammar is None
        assert session.listening is None
        assert session.writing is None
        assert session.conversation_history == []

    def test_user_session_clear(self):
        """Test clearing user session."""
        session = UserSession()
        session.quiz = QuizSession(quiz_type="article", total_questions=10)
        session.conversation_history = ["msg1", "msg2"]

        session.clear()

        assert session.quiz is None
        assert session.conversation_history == []

    def test_user_session_with_nested_sessions(self):
        """Test user session with nested session objects."""
        session = UserSession(
            quiz=QuizSession(quiz_type="meaning", total_questions=5),
            flashcard=FlashcardSession(only_due=True),
            active_lesson_id=10,
        )

        assert session.quiz is not None
        assert session.quiz.quiz_type == "meaning"
        assert session.flashcard is not None
        assert session.flashcard.only_due is True
        assert session.active_lesson_id == 10


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

    def test_flashcard_workflow(self):
        """Test a typical flashcard workflow."""
        session = FlashcardSession(words=[{"id": i} for i in range(10)], only_due=True)

        # Simulate going through cards
        session.current_index = 5
        session.skipped_ids = [2, 4]

        assert session.current_index == 5
        assert len(session.skipped_ids) == 2
        assert session.only_due is True
