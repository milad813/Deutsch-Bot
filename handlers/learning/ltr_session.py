"""LTR (Learn-Test-Review) session management - CORRECT implementation."""

import logging
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models import Word
from services import db, fsrs
from ui import _short_label, progress_bar

logger = logging.getLogger(__name__)

# ─── تنظیمات LTR ───────────────────────────────────────────────────
WORDS_PER_BATCH = 5  # هر بار چند کلمه یاد بده قبل از تست
DELAY_AFTER_LEARN = 5  # چند کلمه بعد، سوال بپرس
MAX_RETRIES = 3  # اگه اشتباه زد، چند بار دوباره بپرس
RETRY_DELAY = 2  # تأخیر برای retry


class LTRSessionManager:
    """Manages LTR learning session with proper Learn → Test → Review flow."""

    def __init__(self, context):
        self.context = context
        self.user_data = context.user_data

    def initialize(
        self,
        user_id: int,
        lesson_id: Optional[int],  # ← Optional شد
        weak_words: List[Word],
        new_words: List[Word],
    ) -> bool:
        """Initialize LTR session."""
        all_words = weak_words + new_words
        if not all_words:
            return False

        # Clean old state
        self.clear_session()

        # Initialize
        self.user_data["ltr_user_id"] = user_id
        self.user_data["ltr_lesson_id"] = lesson_id
        self.user_data["ltr_words"] = [w.id for w in all_words]
        self.user_data["ltr_learn_index"] = 0  # کلمه‌ای که الان یاد میدیم
        self.user_data["ltr_phase"] = "learn"  # learn | test | review | done
        self.user_data["ltr_delayed_tasks"] = []  # تسک‌های تست تأخیری
        self.user_data["ltr_word_results"] = {}  # word_id → [True/False, ...]
        self.user_data["ltr_word_retry_count"] = {}  # word_id → تعداد retry
        self.user_data["ltr_words_learned"] = []  # کلماتی که یاد داده شدن
        self.user_data["ltr_words_tested"] = []  # کلماتی که تست شدن
        self.user_data["ltr_words_passed"] = []  # کلماتی که قبول شدن
        self.user_data["ltr_words_failed"] = []  # کلماتی که رد شدن
        self.user_data["ltr_current_question"] = (
            None  # کلمه‌ای که الان ازش سوال می‌پرسیم
        )

        logger.info(
            "LTR session initialized: lesson=%s, %d weak + %d new = %d words",
            lesson_id,
            len(weak_words),
            len(new_words),
            len(all_words),
        )
        return True

    # ─── Learn Phase ─────────────────────────────────────────────────

    def get_next_word_to_learn(self) -> Optional[Word]:
        """Get next word that hasn't been taught yet."""
        word_ids = self.user_data.get("ltr_words", [])
        learned = set(self.user_data.get("ltr_words_learned", []))
        learn_index = self.user_data.get("ltr_learn_index", 0)

        if learn_index >= len(word_ids):
            return None

        word_id = word_ids[learn_index]
        if word_id in learned:
            # Skip already learned (shouldn't happen but safety)
            self.user_data["ltr_learn_index"] = learn_index + 1
            return self.get_next_word_to_learn()

        return db.words.get_by_id(word_id)

    def mark_word_learned(self, word_id: int):
        """Mark a word as learned and schedule delayed test."""
        learned = self.user_data.setdefault("ltr_words_learned", [])
        if word_id not in learned:
            learned.append(word_id)

        # Schedule delayed test: after DELAY_AFTER_LEARN more words are learned
        progress = len(learned)
        self.user_data["ltr_learn_index"] = self.user_data.get("ltr_learn_index", 0) + 1

        self._schedule_test(word_id, due_after_progress=progress + DELAY_AFTER_LEARN)

    # ─── Test Phase ──────────────────────────────────────────────────

    def _schedule_test(
        self, word_id: int, due_after_progress: int, is_retry: bool = False
    ):
        """Schedule a test question for a word."""
        tasks = self.user_data.setdefault("ltr_delayed_tasks", [])

        # Remove existing task for same word (replace)
        tasks[:] = [t for t in tasks if t.get("word_id") != word_id]

        tasks.append(
            {
                "word_id": word_id,
                "due_after": due_after_progress,
                "is_retry": is_retry,
            }
        )
        # Sort by due time
        tasks.sort(key=lambda t: t.get("due_after", 0))

    def get_due_test(self) -> Optional[Dict]:
        """Get next test question that's due."""
        tasks = self.user_data.get("ltr_delayed_tasks", [])
        learned_count = len(self.user_data.get("ltr_words_learned", []))

        for i, task in enumerate(tasks):
            if task.get("due_after", 0) <= learned_count:
                return tasks.pop(i)

        return None

    def get_current_question_word(self) -> Optional[Word]:
        """Get the word currently being quizzed."""
        word_id = self.user_data.get("ltr_current_question")
        if word_id:
            return db.words.get_by_id(word_id)
        return None

    def record_test_result(self, word_id: int, is_correct: bool, q_type: str = "meaning"):
        """Record test result and decide next action.
        
        NEW: Requires at least MIN_SUCCESS_TYPES different question types
        to be answered correctly before marking word as passed.
        """
        results = self.user_data.setdefault("ltr_word_results", {})
        if word_id not in results:
            results[word_id] = []
        results[word_id].append(is_correct)

        tested = self.user_data.setdefault("ltr_words_tested", [])
        if word_id not in tested:
            tested.append(word_id)

        if is_correct:
            # ✅ Record successful question type
            success_types = self.user_data.setdefault("ltr_word_success_types", {})
            if word_id not in success_types:
                success_types[word_id] = set()
            success_types[word_id].add(q_type)

            # Check if we have enough different successful types
            if len(success_types[word_id]) >= MIN_SUCCESS_TYPES:
                # ✅ Passed - enough variety of correct answers
                passed = self.user_data.setdefault("ltr_words_passed", [])
                if word_id not in passed:
                    passed.append(word_id)
                # Remove from failed if was there
                failed = self.user_data.get("ltr_words_failed", [])
                if word_id in failed:
                    failed.remove(word_id)
            else:
                # ⏳ Need another test with a DIFFERENT question type
                learned_count = len(self.user_data.get("ltr_words_learned", []))
                self._schedule_test(
                    word_id,
                    due_after_progress=learned_count + RETRY_DELAY,
                    is_retry=False,
                )
        else:
            # ❌ Failed - schedule retry if allowed
            retry_count = self.user_data.get("ltr_word_retry_count", {}).get(word_id, 0)
            if retry_count < MAX_RETRIES:
                self.user_data.setdefault("ltr_word_retry_count", {})[word_id] = (
                    retry_count + 1
                )
                learned_count = len(self.user_data.get("ltr_words_learned", []))
                self._schedule_test(
                    word_id,
                    due_after_progress=learned_count + RETRY_DELAY,
                    is_retry=True,
                )
            else:
                # Max retries reached - mark as failed
                failed = self.user_data.setdefault("ltr_words_failed", [])
                if word_id not in failed:
                    failed.append(word_id)

        self.user_data["ltr_current_question"] = None

    # ─── Session Flow Control ────────────────────────────────────────

    def get_next_action(self) -> str:
        """Determine what to do next.
        Returns: 'learn' | 'test' | 'done'
        """
        # 1. Check if there's a due test
        if self.get_due_test_peek():
            return "test"

        # 2. Check if there are words left to learn
        if self.get_next_word_to_learn():
            return "learn"

        # 3. Check if there are pending tests (not yet due but no more to learn)
        tasks = self.user_data.get("ltr_delayed_tasks", [])
        if tasks:
            # Force remaining tests
            return "test"

        return "done"

    def get_due_test_peek(self) -> Optional[Dict]:
        """Check if any test is due without removing it."""
        tasks = self.user_data.get("ltr_delayed_tasks", [])
        learned_count = len(self.user_data.get("ltr_words_learned", []))

        for task in tasks:
            if task.get("due_after", 0) <= learned_count:
                return task
        return None

    def is_session_complete(self) -> bool:
        """Check if all words learned and all tests done."""
        word_ids = self.user_data.get("ltr_words", [])
        learned = self.user_data.get("ltr_words_learned", [])
        tasks = self.user_data.get("ltr_delayed_tasks", [])

        return len(learned) >= len(word_ids) and len(tasks) == 0

    # ─── SRS & Stats ─────────────────────────────────────────────────

    def finalize_word(self, word_id: int, user_id: int = None):
        """Finalize word after all tests are done. Update SRS."""
        uid = user_id or self.user_data.get("ltr_user_id")
        if not uid:
            return

        results = self.user_data.get("ltr_word_results", {}).get(word_id, [])
        if not results:
            return

        # Update SRS based on all results
        fsrs.review_ltr(uid, word_id, results)

        # Record activity
        correct_count = sum(1 for r in results if r)
        if all(results):
            db.users.record_activity(uid, 20)
        else:
            db.users.record_activity(uid, 5 * correct_count)

    def finalize_all_passed_words(self):
        """Finalize all words that passed."""
        uid = self.user_data.get("ltr_user_id")
        passed = self.user_data.get("ltr_words_passed", [])
        failed = self.user_data.get("ltr_words_failed", [])

        for word_id in passed + failed:
            self.finalize_word(word_id, user_id=uid)

    def finalize_partial_session(self):
        """Finalize words that have at least one recorded result.

        This is used when the user exits before the session is fully complete.
        """
        uid = self.user_data.get("ltr_user_id")
        results = self.user_data.get("ltr_word_results", {})

        for word_id, word_results in results.items():
            if word_results:
                self.finalize_word(word_id, user_id=uid)

    # ─── Summary & Progress ──────────────────────────────────────────

    def get_progress_info(self) -> Dict[str, Any]:
        """Get session progress."""
        word_ids = self.user_data.get("ltr_words", [])
        total = len(word_ids) or 1
        learned = len(self.user_data.get("ltr_words_learned", []))
        tested = len(self.user_data.get("ltr_words_tested", []))

        bar = progress_bar(learned, total)
        return {
            "total": total,
            "learned": learned,
            "tested": tested,
            "progress_bar": bar,
            "percentage": int((learned / total) * 100),
        }

    def get_session_summary(self) -> Dict[str, Any]:
        """Get final session summary."""
        word_ids = self.user_data.get("ltr_words", [])
        passed = self.user_data.get("ltr_words_passed", [])
        failed = self.user_data.get("ltr_words_failed", [])
        total = len(word_ids)

        return {
            "total_words": total,
            "passed_words": len(passed),
            "failed_words": len(failed),
            "not_tested": total - len(passed) - len(failed),
            "accuracy": int((len(passed) / total * 100) if total > 0 else 0),
            "passed_ids": passed,
            "failed_ids": failed,
        }


    def clear_session(self) -> None:
        keys_to_clear = [
            "ltr_user_id",
            "ltr_lesson_id",
            "ltr_words",
            "ltr_learn_index",
            "ltr_phase",
            "ltr_delayed_tasks",
            "ltr_word_results",
            "ltr_word_retry_count",
            "ltr_word_success_types",
            "ltr_words_learned",
            "ltr_words_tested",
            "ltr_words_passed",
            "ltr_words_failed",
            "ltr_current_question",
            "ltr_current_options",
            "ltr_current_correct_index",
            "ltr_current_correct_text",
            "ltr_question_type",
            # Legacy keys
            "ltr_index",
            "ltr_main_index",
            "ltr_main_progress",
            "ltr_retry_stage",
            "ltr_wrong_in_session",
            "ltr_round",
            "ltr_round2_started",
            "ltr_delayed_1",
            "ltr_delayed_2",
        ]
        for key in keys_to_clear:
            self.user_data.pop(key, None)


# ─── Helper Functions ────────────────────────────────────────────────


def _ltr_learn_keyboard(word_id: int = None) -> InlineKeyboardMarkup:
    """Keyboard for learn phase."""
    rows = [
        [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")],
        [InlineKeyboardButton("✅ یاد گرفتم، بعدی!", callback_data="ltr_learned")],
        [InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")],
    ]
    return InlineKeyboardMarkup(rows)


def _ltr_answer_keyboard(options: list) -> InlineKeyboardMarkup:
    """Keyboard for test/quiz phase."""
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
    rows.append([InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")])
    return InlineKeyboardMarkup(rows)


def _ltr_intro_keyboard() -> InlineKeyboardMarkup:
    """Alias for backward compatibility - same as _ltr_learn_keyboard."""
    return _ltr_learn_keyboard()


__all__ = [
    "LTRSessionManager",
    "_ltr_learn_keyboard",
    "_ltr_intro_keyboard",
    "_ltr_answer_keyboard",
]
