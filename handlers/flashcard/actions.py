"""Flashcard action handlers (rate, skip, flip)."""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from telegram import Update, CallbackQuery
    from telegram.ext import CallbackContext

from handlers.flashcard.display import flashcard_display
from handlers.flashcard.session import flashcard_session_manager
from models import Word
from services import db, fsrs

logger = logging.getLogger(__name__)


class FlashcardActionsHandler:
    """Handles flashcard user actions."""

    async def handle_flip(
        self,
        query: "CallbackQuery",
        update: "Update",
        context: "CallbackContext",
        word_id: int,
    ) -> None:
        """Flip card to show meaning."""
        user_id = query.from_user.id
        word = db.get_word_by_id(word_id)

        if not word:
            await query.answer("کلمه یافت نشد!", show_alert=True)
            return

        await flashcard_display.show_back(query, update, word)

    async def handle_skip(
        self,
        query: "CallbackQuery",
        update: "Update",
        context: "CallbackContext",
        word_id: int,
    ) -> None:
        """Skip current word."""
        user_id = query.from_user.id
        word = db.get_word_by_id(word_id)

        if not word:
            await query.answer("کلمه یافت نشد!", show_alert=True)
            return

        flashcard_session_manager.skip_word(user_id, word)
        await query.answer("رد شد ⏭️")

        # Show next word
        await self._show_next_or_end(query, update, context, user_id)

    async def handle_rate(
        self,
        query: "CallbackQuery",
        update: "Update",
        context: "CallbackContext",
        word_id: int,
        rating: int,
    ) -> None:
        """Rate a word and process SRS update."""
        user_id = query.from_user.id
        word = db.get_word_by_id(word_id)

        if not word:
            await query.answer("کلمه یافت نشد!", show_alert=True)
            return

        # Update SRS
        try:
            fsrs.update_card(user_id, word_id, rating)
            flashcard_session_manager.complete_word(user_id)
            await query.answer("✅ ثبت شد")
        except Exception as e:
            logger.error("Error updating SRS: %s", e)
            await query.answer("⚠️ خطا در ثبت", show_alert=True)
            return

        # Show next word
        await self._show_next_or_end(query, update, context, user_id)

    async def _show_next_or_end(
        self,
        query: "CallbackQuery",
        update: "Update",
        context: "CallbackContext",
        user_id: int,
    ) -> None:
        """Show next word or end session."""
        if flashcard_session_manager.is_session_complete(user_id):
            flashcard_session_manager.end_session(user_id)
            await query.edit_message_text(
                "✅ جلسه فلش‌کارت تکمیل شد!\n\n" "برای شروع مجدد، از منو انتخاب کنید."
            )
            return

        next_word = flashcard_session_manager.get_next_word(user_id)
        if next_word:
            await flashcard_display.show_front(query, update, next_word)


# Global instance
flashcard_actions_handler = FlashcardActionsHandler()
