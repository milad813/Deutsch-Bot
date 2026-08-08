"""Quiz session management."""

import logging
from typing import Optional, Dict, Any, List, Iterable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QuizQuestion:
    """Represents a single quiz question."""

    question_type: str
    question_text: str
    correct_answer: str
    options: List[str]
    word_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuizSessionState:
    """Holds the state of a quiz session."""

    user_id: int
    total_questions: int
    current_question: int = 0
    correct_answers: int = 0
    wrong_answers: int = 0
    question_history: List[Dict[str, Any]] = field(default_factory=list)
    is_finished: bool = False

    @property
    def accuracy(self) -> float:
        """Calculate accuracy percentage."""
        total = self.correct_answers + self.wrong_answers
        if total == 0:
            return 0.0
        return (self.correct_answers / total) * 100

    @property
    def progress_percentage(self) -> int:
        """Calculate progress percentage."""
        if self.total_questions == 0:
            return 0
        return int((self.current_question / self.total_questions) * 100)


class QuizSessionManager:
    """Manages quiz sessions for users."""

    def __init__(self):
        self.sessions: Dict[int, QuizSessionState] = {}

    def create_session(
        self,
        user_id: int,
        total_questions: int = 10,
    ) -> QuizSessionState:
        """Create a new quiz session for a user."""
        # End any existing session first
        if user_id in self.sessions:
            self.end_session(user_id)

        session = QuizSessionState(
            user_id=user_id,
            total_questions=total_questions,
        )
        self.sessions[user_id] = session

        logger.info(
            "Created quiz session for user %d with %d questions",
            user_id,
            total_questions,
        )

        return session

    def get_session(self, user_id: int) -> Optional[QuizSessionState]:
        """Get session for a user."""
        return self.sessions.get(user_id)

    def advance_question(self, user_id: int, is_correct: bool) -> QuizSessionState:
        """Advance to next question and record result."""
        session = self.sessions.get(user_id)
        if not session:
            raise ValueError(f"No active session for user {user_id}")

        session.current_question += 1
        if is_correct:
            session.correct_answers += 1
        else:
            session.wrong_answers += 1

        # Check if session is complete
        if session.current_question >= session.total_questions:
            session.is_finished = True

        return session

    def record_question(
        self,
        user_id: int,
        question_type: str,
        word_id: Optional[int] = None,
        is_correct: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record question details in history."""
        session = self.sessions.get(user_id)
        if not session:
            return

        session.question_history.append(
            {
                "question_type": question_type,
                "word_id": word_id,
                "is_correct": is_correct,
                "metadata": metadata or {},
            }
        )

    def end_session(self, user_id: int) -> Optional[QuizSessionState]:
        """End and return the session."""
        session = self.sessions.pop(user_id, None)
        if session:
            logger.info(
                "Ended quiz session for user %d: %d/%d correct (%.1f%%)",
                user_id,
                session.correct_answers,
                session.current_question,
                session.accuracy,
            )
        return session

    def get_summary(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get session summary statistics."""
        session = self.sessions.get(user_id)
        if not session:
            return None

        return {
            "total_questions": session.total_questions,
            "answered": session.current_question,
            "correct": session.correct_answers,
            "wrong": session.wrong_answers,
            "accuracy": session.accuracy,
            "progress_percentage": session.progress_percentage,
            "is_finished": session.is_finished,
        }


# Global instance
quiz_session_manager = QuizSessionManager()


__all__ = [
    "QuizQuestion",
    "QuizSessionState",
    "QuizSessionManager",
    "quiz_session_manager",
]
