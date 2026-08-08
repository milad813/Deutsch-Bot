"""Flashcard session management."""

import logging
from collections import deque
from typing import TYPE_CHECKING, List, Optional, Set

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import CallbackContext

import config
from models import Word
from services import db, fsrs

logger = logging.getLogger(__name__)


class FlashcardSessionManager:
    """Manages flashcard learning sessions including queue and state."""

    def __init__(self):
        self.sessions: dict[int, dict] = {}

    def create_session(
        self,
        user_id: int,
        lesson_id: Optional[int] = None,
        only_new: bool = False,
        only_due: bool = False,
        hard_only: bool = False,
    ) -> List[Word]:
        """Create a new flashcard session for a user."""
        # Get words based on session type
        if hard_only:
            words = db.get_hard_due_word_objects(
                user_id, limit=config.FLASHCARD_QUEUE_LIMIT
            )
        elif only_due:
            words = db.get_due_word_objects(
                user_id,
                limit=config.FLASHCARD_QUEUE_LIMIT,
                lesson_id=lesson_id,
            )
        else:
            words = fsrs.get_review_cards(
                user_id,
                limit=config.FLASHCARD_QUEUE_LIMIT,
                lesson_id=lesson_id,
                include_new=True,
                new_limit=config.FLASHCARD_NEW_LIMIT,
                only_new=only_new,
            )

        # Store session state
        self.sessions[user_id] = {
            "lesson_id": lesson_id,
            "only_new": only_new,
            "only_due": only_due,
            "hard_only": hard_only,
            "queue": deque(words),
            "skipped_ids": set(),
            "completed_count": 0,
        }

        logger.info(
            "Created flashcard session for user %d with %d words", user_id, len(words)
        )

        return words

    def get_session(self, user_id: int) -> Optional[dict]:
        """Get session data for a user."""
        return self.sessions.get(user_id)

    def get_next_word(self, user_id: int) -> Optional[Word]:
        """Get the next word in the queue."""
        session = self.sessions.get(user_id)
        if not session or not session["queue"]:
            return None
        return session["queue"].popleft()

    def skip_word(self, user_id: int, word: Word) -> None:
        """Skip a word and add it to skipped set."""
        session = self.sessions.get(user_id)
        if session:
            session["skipped_ids"].add(word.id)
            session["queue"].append(word)

    def complete_word(self, user_id: int) -> None:
        """Mark a word as completed."""
        session = self.sessions.get(user_id)
        if session:
            session["completed_count"] += 1

    def is_session_complete(self, user_id: int) -> bool:
        """Check if session is complete."""
        session = self.sessions.get(user_id)
        return not session or not session["queue"]

    def end_session(self, user_id: int) -> None:
        """End the current session."""
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info("Ended flashcard session for user %d", user_id)


# Global instance
flashcard_session_manager = FlashcardSessionManager()
