"""Flashcard queue and session state."""

from collections.abc import Iterable
from typing import Any, List, Optional
import config
from models import Word
from core.answer_tokens import new_answer_token
from services import db, fsrs, run_db


def _coerce_to_list(value: Any) -> list:
    """Return ``value`` as a list.

    Used to normalize session state that may have been persisted as a
    ``deque`` or ``set`` by older code paths (or by PicklePersistence
    carrying legacy shapes).  New code stores plain lists so that
    ``context.user_data`` stays JSON-serializable.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, Iterable):
        return list(value)
    return []


class FlashcardSessionManager:
    """Manages flashcard session state and queue."""

    def __init__(self, context):
        self.context = context
        self.user_data = context.user_data

    def initialize(
        self,
        lesson_id: Optional[int] = None,
        only_new: bool = False,
        only_due: bool = False,
        hard_only: bool = False,
    ) -> None:
        """Initialize flashcard session with settings."""
        self.clear_session()
        self.user_data["active_lesson_id"] = lesson_id
        self.user_data["flashcard_only_new"] = only_new
        self.user_data["flashcard_only_due"] = only_due
        self.user_data["flashcard_hard_only"] = hard_only
        self.user_data["flashcard_skipped_ids"] = []
        self.user_data["flashcard_again_counts"] = {}

    async def load_words(
        self,
        user_id: int,
        limit: int = config.FLASHCARD_QUEUE_LIMIT,
    ) -> list[Word]:
        """Load words based on session settings."""
        hard_only = self.user_data.get("flashcard_hard_only", False)
        only_due = self.user_data.get("flashcard_only_due", False)
        only_new = self.user_data.get("flashcard_only_new", False)
        lesson_id = self.user_data.get("active_lesson_id")

        if hard_only:
            return await run_db(
                db.words.get_hard_due,
                user_id,
                limit=limit,
            )
        elif only_due:
            return await run_db(
                db.words.get_due,
                user_id,
                limit=limit,
                lesson_id=lesson_id,
            )
        else:
            return await run_db(
                fsrs.get_review_cards,
                user_id,
                limit=limit,
                lesson_id=lesson_id,
                include_new=True,
                new_limit=config.FLASHCARD_NEW_LIMIT,
                only_new=only_new,
            )

    def set_queue(self, words: list[Word]) -> None:
        """Set the flashcard queue from word list.

        Stores a plain ``list[int]`` so that ``context.user_data`` stays
        JSON-serializable.  The current word (``words[0]``) is rendered
        immediately by the caller; the rest are queued for subsequent
        cards.
        """
        self.user_data["flashcard_queue"] = [w.id for w in words[1:]]

    def get_current_word_id(self) -> Optional[int]:
        """Get current flashcard word ID."""
        fc_data = self.user_data.get("current_flashcard", {})
        return fc_data.get("word_id") if fc_data else None

    def set_current_word(self, word_id: int) -> None:
        """Set current flashcard word."""
        self.user_data["current_flashcard"] = {
            "word_id": word_id,
            "answer_token": new_answer_token(),
        }

    def add_to_skipped(self, word_id: int) -> None:
        """Add word to the skipped list (idempotent)."""
        skipped = self.user_data.get("flashcard_skipped_ids")
        if not isinstance(skipped, list):
            # Coerce legacy values (e.g. ``set`` from older sessions)
            # into the new list shape and write them back.
            skipped = _coerce_to_list(skipped)
            self.user_data["flashcard_skipped_ids"] = skipped
        if word_id not in skipped:
            skipped.append(word_id)

    def get_skipped_ids(self) -> List[int]:
        """Return the list of skipped word IDs.

        Returned as a list rather than a ``set`` so that
        ``context.user_data`` stays JSON-serializable.  Callers needing
        set semantics should wrap the result in ``set(...)``.
        """
        value = self.user_data.get("flashcard_skipped_ids")
        if isinstance(value, list):
            return value
        # Coerce legacy ``set``/``tuple``/etc. values from older sessions
        # back into the new list shape and write them back.
        coerced = _coerce_to_list(value)
        self.user_data["flashcard_skipped_ids"] = coerced
        return coerced

    def pop_queue(self) -> Optional[int]:
        """Pop next word ID from queue.

        Returns the front element and removes it.  The list is bounded by
        ``config.FLASHCARD_QUEUE_LIMIT`` (≤ 20), so ``list.pop(0)`` is
        cheap enough.
        """
        queue = self.user_data.get("flashcard_queue")
        if not isinstance(queue, list):
            queue = _coerce_to_list(queue)
            self.user_data["flashcard_queue"] = queue

        if not queue:
            return None
        return queue.pop(0)

    def get_remaining_count(self) -> int:
        """Get remaining cards count (including the one currently shown)."""
        queue = self.user_data.get("flashcard_queue")
        if isinstance(queue, list):
            return len(queue) + 1
        return 1

    def clear_session(self) -> None:
        """Clear all flashcard session data."""
        keys_to_clear = [
            "current_flashcard",
            "flashcard_queue",
            "current_tts_text",
            "flashcard_skipped_ids",
            "flashcard_hard_only",
            "flashcard_only_new",
            "flashcard_only_due",
            "active_lesson_id",
            "fsrs_guide_shown",
            "flashcard_again_counts",
        ]
        for key in keys_to_clear:
            self.user_data.pop(key, None)
