"""LTR (Learn-Test-Repeat) session management."""

import logging
import random
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models import Word
from services import db, fsrs
from ui import _short_label, progress_bar

logger = logging.getLogger(__name__)


class LTRSessionManager:
    """Manages LTR learning session state and progression."""

    def __init__(self, context):
        self.context = context
        self.user_data = context.user_data

    def initialize(
        self,
        user_id: int,
        lesson_id: int,
        weak_words: List[Word],
        new_words: List[Word],
    ) -> bool:
        """Initialize LTR session with words.

        Returns True if session started, False if no words available.
        """
        all_words = weak_words + new_words

        if not all_words:
            return False

        weak_count = len(weak_words)
        new_count = len(new_words)

        # Clear old keys from previous versions
        self.user_data.pop("ltr_index", None)
        self.user_data.pop("ltr_delayed_1", None)
        self.user_data.pop("ltr_delayed_2", None)

        # Initialize session state
        self.user_data["ltr_user_id"] = user_id  # Store user_id for finalize_word
        self.user_data["ltr_words"] = [w.id for w in all_words]
        self.user_data["ltr_main_index"] = 0
        self.user_data["ltr_main_progress"] = 0
        self.user_data["ltr_delayed_tasks"] = []
        self.user_data["ltr_retry_stage"] = None
        self.user_data["ltr_lesson_id"] = lesson_id
        self.user_data["ltr_wrong_in_session"] = []
        self.user_data["ltr_word_results"] = {}
        self.user_data["ltr_round"] = 1
        self.user_data.pop("ltr_round2_started", None)

        logger.info(
            "Initialized LTR session for lesson %d: %d weak + %d new words",
            lesson_id,
            weak_count,
            new_count,
        )

        return True

    def get_current_word(self) -> Optional[Word]:
        """Get current word in the session."""
        word_ids = self.user_data.get("ltr_words", [])
        index = self.user_data.get("ltr_main_index", 0)

        if not word_ids or index >= len(word_ids):
            return None

        word_id = word_ids[index]
        return db.get_word_by_id(word_id)

    def get_word_by_id(self, word_id: int) -> Optional[Word]:
        """Get word by ID."""
        return db.get_word_by_id(word_id)

    def advance_to_next_word(self) -> bool:
        """Advance to next word. Returns True if more words remain."""
        word_ids = self.user_data.get("ltr_words", [])
        index = self.user_data.get("ltr_main_index", 0)

        next_index = index + 1
        self.user_data["ltr_main_index"] = next_index
        self.user_data["ltr_main_progress"] = (
            self.user_data.get("ltr_main_progress", 0) + 1
        )

        return next_index < len(word_ids)

    def get_progress_info(self) -> Dict[str, Any]:
        """Get session progress information."""
        word_ids = self.user_data.get("ltr_words", [])
        total = len(word_ids) or 1
        pos = self.user_data.get("ltr_main_index", 0) + 1
        bar = progress_bar(pos, total)

        return {
            "position": pos,
            "total": total,
            "progress_bar": bar,
            "percentage": int((pos / total) * 100),
        }

    def schedule_delayed_task(
        self,
        word_id: int,
        stage: str,
        delay_main: int,
    ) -> None:
        """Schedule a delayed task for a word."""
        tasks = self.user_data.setdefault("ltr_delayed_tasks", [])
        if not isinstance(tasks, list):
            tasks = []
            self.user_data["ltr_delayed_tasks"] = tasks

        # Remove existing task for same word/stage
        tasks[:] = [
            t
            for t in tasks
            if not (
                isinstance(t, dict)
                and t.get("word_id") == word_id
                and t.get("stage") == stage
            )
        ]

        progress = self.user_data.get("ltr_main_progress", 0)
        tasks.append(
            {
                "word_id": word_id,
                "stage": stage,
                "due_after": progress + delay_main,
            }
        )

    def get_due_delayed_task(self) -> Optional[Dict[str, Any]]:
        """Get next due delayed task."""
        tasks = self.user_data.get("ltr_delayed_tasks", [])
        if not isinstance(tasks, list):
            tasks = []
            self.user_data["ltr_delayed_tasks"] = tasks

        progress = self.user_data.get("ltr_main_progress", 0)
        tasks.sort(key=lambda t: t.get("due_after", 0) if isinstance(t, dict) else 0)

        for i, task in enumerate(tasks):
            if isinstance(task, dict) and task.get("due_after", 0) <= progress:
                return tasks.pop(i)

        return None

    def record_word_result(self, word_id: int, is_correct: bool) -> None:
        """Record result for a word."""
        results = self.user_data.setdefault("ltr_word_results", {}).setdefault(
            word_id, []
        )
        results.append(is_correct)

    def finalize_word(self, word_id: int) -> Dict[str, Any]:
        """Finalize word processing and return stats."""
        # Get user_id from context.user_data (set by caller with query.from_user.id)
        user_id = self.user_data.get("ltr_user_id")

        results = self.user_data.get("ltr_word_results", {}).get(word_id, [])

        # Update SRS
        if user_id:
            fsrs.review_ltr(user_id, word_id, results)

        # Calculate stats
        correct_count = sum(1 for r in results if r) if results else 0
        all_correct = all(results) if results else False

        # Record activity
        if user_id:
            if results and all_correct:
                db.record_activity(user_id, 20)
            elif results:
                db.record_activity(user_id, 5 * correct_count)

        # Track wrong answers
        if any(not r for r in results):
            wrong_list = self.user_data.setdefault("ltr_wrong_in_session", [])
            if word_id not in wrong_list:
                wrong_list.append(word_id)

        return {
            "correct_count": correct_count,
            "total_attempts": len(results),
            "all_correct": all_correct,
        }

    def get_session_summary(self) -> Dict[str, Any]:
        """Get session summary statistics."""
        word_ids = self.user_data.get("ltr_words", [])
        wrong_list = self.user_data.get("ltr_wrong_in_session", [])

        total = len(word_ids)
        wrong_count = len(wrong_list)
        correct_count = total - wrong_count

        return {
            "total_words": total,
            "correct_words": correct_count,
            "wrong_words": wrong_count,
            "accuracy": int((correct_count / total * 100) if total > 0 else 0),
            "wrong_word_ids": wrong_list,
        }

    def clear_session(self) -> None:
        """Clear all LTR session data."""
        keys_to_clear = [
            "ltr_words",
            "ltr_main_index",
            "ltr_main_progress",
            "ltr_delayed_tasks",
            "ltr_retry_stage",
            "ltr_lesson_id",
            "ltr_wrong_in_session",
            "ltr_word_results",
            "ltr_round",
            "ltr_round2_started",
            "ltr_index",
            "ltr_delayed_1",
            "ltr_delayed_2",
            "ltr_user_id",
            "ltr_current_options",
            "ltr_current_correct_index",
            "ltr_current_correct_text",
        ]
        for key in keys_to_clear:
            self.user_data.pop(key, None)


def _sample_unique_ltr(primary: list, secondary: list, count: int) -> list:
    """Sample unique items from primary and secondary lists."""
    random.shuffle(primary)
    random.shuffle(secondary)

    result = []
    for item in primary + secondary:
        item = str(item or "").strip()
        if item and item not in result:
            result.append(item)
        if len(result) == count:
            break

    return result


def _make_ltr_options(
    correct: str, wrongs: list, total: int = 4, min_options: int = 1
) -> Optional[list]:
    """Create multiple choice options with correct answer and distractors."""
    correct = str(correct or "").strip()
    if not correct:
        return None

    options = [correct]
    for wrong in wrongs or []:
        wrong = str(wrong or "").strip()
        if not wrong or wrong in options:
            continue
        options.append(wrong)
        if len(options) == total:
            break

    if len(options) < min_options:
        return None

    random.shuffle(options)
    return options


def _ltr_wrong_display_german_options(word: Word, count: int = 3) -> list:
    """Get wrong German display options for a word."""
    same_type_words = (
        db.get_words_by_type(word.word_type, exclude_id=word.id, limit=50)
        if word.word_type
        else []
    )
    other_words = db.get_words_by_type(None, exclude_id=word.id, limit=50)

    same_type = [
        w.display_german
        for w in same_type_words
        if w.display_german and w.display_german != word.display_german
    ]
    other = [
        w.display_german
        for w in other_words
        if w.display_german
        and w.display_german != word.display_german
        and (not word.word_type or w.word_type != word.word_type)
    ]

    return _sample_unique_ltr(same_type, other, count)


def _ltr_answer_keyboard(options: list, with_tts: bool = False) -> InlineKeyboardMarkup:
    """Create answer keyboard for LTR questions."""
    rows = []

    for i, opt in enumerate(options):
        label = f"{chr(65 + i)}) {opt}"
        rows.append(
            [
                InlineKeyboardButton(
                    _short_label(label, 64), callback_data=f"ltr_ans:{i}"
                )
            ]
        )

    if with_tts:
        rows.append(
            [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")]
        )

    rows.append([InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")])

    return InlineKeyboardMarkup(rows)


def _ltr_intro_keyboard() -> InlineKeyboardMarkup:
    """Create intro keyboard for LTR session."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")],
            [InlineKeyboardButton("✅ فهمیدم، بریم!", callback_data="ltr_ready")],
            [InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")],
        ]
    )


__all__ = [
    "LTRSessionManager",
    "_sample_unique_ltr",
    "_make_ltr_options",
    "_ltr_wrong_display_german_options",
    "_ltr_answer_keyboard",
    "_ltr_intro_keyboard",
]
