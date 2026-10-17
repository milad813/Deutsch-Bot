"""Bounded LTR sessions; spacing counts intervening learning activities."""

from typing import Any, Dict, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.callbacks import cb_safe
from core.answer_tokens import new_answer_token
from core.sessions import reset_feature
from models import CallbackPrefix, Word
from services import db, fsrs, run_db
from ui import _short_label, progress_bar

WORDS_PER_BATCH = 5
DELAY_AFTER_LEARN = 2
RETRY_DELAY = 2
SUCCESS_DELAY = 3
MAX_RETRIES = 2
MIN_SUCCESS_TYPES = 2
MAX_ATTEMPTS_PER_WORD = 5


class LTRSessionManager:
    def __init__(self, context):
        self.context = context
        self.user_data = context.user_data

    def initialize(
        self, user_id: int, lesson_id: Optional[int], weak_words: List[Word], new_words: List[Word]
    ) -> bool:
        words = list({w.id: w for w in weak_words + new_words}.values())
        if not words:
            return False
        self.clear_session()
        self.user_data.update(
            {
                "ltr_session_id": new_answer_token(),
                "ltr_user_id": user_id,
                "ltr_lesson_id": lesson_id,
                "ltr_words": [w.id for w in words],
                "ltr_learn_index": 0,
                "ltr_phase": "learn",
                "ltr_activity": 0,
                "ltr_delayed_tasks": [],
                "ltr_word_results": {},
                "ltr_word_retry_count": {},
                "ltr_word_success_types": {},
                "ltr_words_learned": [],
                "ltr_words_tested": [],
                "ltr_words_passed": [],
                "ltr_words_failed": [],
                "ltr_words_deferred": [],
                "ltr_finalized": [],
                "ltr_review_times": {},
                "ltr_current_question": None,
                "ltr_first_answers": {},
                "ltr_attempt_log": [],
            }
        )
        return True

    @property
    def activity(self):
        return self.user_data.get("ltr_activity", 0)

    async def get_next_word_to_learn(self) -> Optional[Word]:
        ids = self.user_data.get("ltr_words", [])
        index = self.user_data.get("ltr_learn_index", 0)
        while index < len(ids):
            word = await run_db(db.words.get_by_id, ids[index])
            if word:
                return word
            index += 1
            self.user_data["ltr_learn_index"] = index
        return None

    def mark_word_learned(self, word_id: int):
        learned = self.user_data.setdefault("ltr_words_learned", [])
        if word_id in learned:
            return
        learned.append(word_id)
        self.user_data["ltr_learn_index"] = self.user_data.get("ltr_learn_index", 0) + 1
        self.user_data["ltr_activity"] = self.activity + 1
        self._schedule_test(word_id, self.activity + DELAY_AFTER_LEARN)

    def _schedule_test(self, word_id: int, due_after_progress: int, is_retry: bool = False):
        tasks = self.user_data.setdefault("ltr_delayed_tasks", [])
        tasks[:] = [t for t in tasks if t["word_id"] != word_id]
        tasks.append({"word_id": word_id, "due_after": due_after_progress, "is_retry": is_retry})
        tasks.sort(key=lambda t: t["due_after"])

    def get_due_test_peek(self) -> Optional[Dict]:
        return next(
            (
                t
                for t in self.user_data.get("ltr_delayed_tasks", [])
                if t["due_after"] <= self.activity
            ),
            None,
        )

    def get_due_test(self) -> Optional[Dict]:
        task = self.get_due_test_peek()
        if task:
            self.user_data["ltr_delayed_tasks"].remove(task)
        return task

    async def get_current_question_word(self) -> Optional[Word]:
        word_id = self.user_data.get("ltr_current_question")
        return await run_db(db.words.get_by_id, word_id) if word_id else None

    def defer_word(self, word_id: int):
        deferred = self.user_data.setdefault("ltr_words_deferred", [])
        if word_id not in deferred:
            deferred.append(word_id)
        tasks = self.user_data.setdefault("ltr_delayed_tasks", [])
        tasks[:] = [t for t in tasks if t["word_id"] != word_id]
        self.user_data["ltr_current_question"] = None

    def defer_pending(self):
        for task in list(self.user_data.get("ltr_delayed_tasks", [])):
            self.defer_word(task["word_id"])

    def record_test_result(
        self, word_id: int, is_correct: bool, q_type: str = "meaning", independent: bool = True
    ):
        results = self.user_data.setdefault("ltr_word_results", {}).setdefault(word_id, [])
        results.append(is_correct)
        self.user_data.setdefault("ltr_first_answers", {}).setdefault(word_id, is_correct)
        tested = self.user_data.setdefault("ltr_words_tested", [])
        if word_id not in tested:
            tested.append(word_id)
        self.user_data["ltr_activity"] = self.activity + 1
        success = self.user_data.setdefault("ltr_word_success_types", {}).setdefault(word_id, [])
        if is_correct and independent and q_type not in success:
            success.append(q_type)
        passed = self.user_data.setdefault("ltr_words_passed", [])
        failed = self.user_data.setdefault("ltr_words_failed", [])
        retries = self.user_data.setdefault("ltr_word_retry_count", {})
        if not is_correct:
            retries[word_id] = retries.get(word_id, 0) + 1
        if len(success) >= MIN_SUCCESS_TYPES and "recall" in success:
            if word_id not in passed:
                passed.append(word_id)
            if word_id in failed:
                failed.remove(word_id)
            self.user_data["ltr_delayed_tasks"] = [
                t for t in self.user_data.get("ltr_delayed_tasks", []) if t["word_id"] != word_id
            ]
        elif retries.get(word_id, 0) > MAX_RETRIES or len(results) >= MAX_ATTEMPTS_PER_WORD:
            if word_id not in failed:
                failed.append(word_id)
            self.defer_word(word_id)
        else:
            delay = SUCCESS_DELAY if is_correct else RETRY_DELAY
            self._schedule_test(word_id, self.activity + delay, is_retry=not is_correct)
        self.user_data["ltr_current_question"] = None

    async def get_next_action(self) -> str:
        if self.get_due_test_peek():
            return "test"
        if await self.get_next_word_to_learn():
            return "learn"
        self.defer_pending()
        return "done"

    async def finalize_word(self, word_id: int, user_id: int = None):
        uid = user_id or self.user_data.get("ltr_user_id")
        finalized = self.user_data.setdefault("ltr_finalized", [])
        if not uid or word_id in finalized:
            return
        results = self.user_data.get("ltr_word_results", {}).get(word_id, [])
        incomplete = word_id not in self.user_data.get("ltr_words_passed", [])
        session_id = self.user_data.setdefault("ltr_session_id", new_answer_token())

        def save():
            with db.transaction():
                previous = db.learning.get_ltr_finalization(session_id, uid, word_id)
                if previous:
                    return previous
                if results:
                    state, _ = fsrs.review_ltr(uid, word_id, results)
                    next_review = (
                        db.learning.defer_ltr_review(uid, word_id)
                        if incomplete
                        else state.next_review.strftime("%Y-%m-%d %H:%M:%S")
                    )
                    db.users.record_activity(uid, 5 * sum(results))
                else:
                    next_review = db.learning.defer_ltr_review(uid, word_id)
                db.learning.save_ltr_finalization(session_id, uid, word_id, next_review)
                return next_review

        next_review = await run_db(save)
        self.user_data.setdefault("ltr_review_times", {})[word_id] = next_review
        finalized.append(word_id)

    async def finalize_all_passed_words(self):
        for word_id in self.user_data.get("ltr_words_learned", []):
            await self.finalize_word(word_id)

    async def finalize_partial_session(self):
        await self.finalize_all_passed_words()

    def get_progress_info(self) -> Dict[str, Any]:
        total = len(self.user_data.get("ltr_words", []))
        learned = len(self.user_data.get("ltr_words_learned", []))
        attempts = sum(len(r) for r in self.user_data.get("ltr_word_results", {}).values())
        return {
            "total": total,
            "learned": learned,
            "tested": len(self.user_data.get("ltr_words_tested", [])),
            "attempts": attempts,
            "attempt_limit": total * MAX_ATTEMPTS_PER_WORD,
            "progress_bar": progress_bar(learned, max(1, total)),
            "percentage": int(learned / max(1, total) * 100),
        }

    def get_session_summary(self) -> Dict[str, Any]:
        words = self.user_data.get("ltr_words", [])
        passed = self.user_data.get("ltr_words_passed", [])
        learned = self.user_data.get("ltr_words_learned", [])
        pending = [wid for wid in learned if wid not in passed]
        results = self.user_data.get("ltr_word_results", {})
        attempts = [r for values in results.values() for r in values]
        first = list(self.user_data.get("ltr_first_answers", {}).values())
        return {
            "total_words": len(words),
            "passed_words": len(passed),
            "failed_words": len(pending),
            "failed_ids": pending,
            "passed_ids": passed,
            "not_tested": len([w for w in words if not results.get(w)]),
            "attempts": len(attempts),
            "accuracy": int(100 * sum(attempts) / len(attempts)) if attempts else 0,
            "first_accuracy": int(100 * sum(first) / len(first)) if first else 0,
            "first_count": len(first),
        }

    def clear_session(self) -> None:
        reset_feature(self.context, "ltr")


def _ltr_learn_keyboard(word_id: int = None, token: str = "") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")],
        [InlineKeyboardButton("📖 جزئیات بیشتر", callback_data=f"ltr_details:{token}")],
        [InlineKeyboardButton("✅ آمادهٔ تمرینم", callback_data=f"ltr_learned:{token}")],
        [InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")],
    ]
    return InlineKeyboardMarkup(rows)


def _ltr_answer_keyboard(options: list, token: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                _short_label(opt, 64),
                callback_data=cb_safe(CallbackPrefix.LTR_ANS, f"{token}:{i}" if token else i),
            )
        ]
        for i, opt in enumerate(options)
    ]
    rows.append([InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")])
    return InlineKeyboardMarkup(rows)


def _ltr_intro_keyboard() -> InlineKeyboardMarkup:
    return _ltr_learn_keyboard()


__all__ = [
    "LTRSessionManager",
    "_ltr_learn_keyboard",
    "_ltr_intro_keyboard",
    "_ltr_answer_keyboard",
]
