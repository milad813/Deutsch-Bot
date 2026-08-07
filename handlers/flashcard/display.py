"""Flashcard display and rendering."""

import logging
from typing import TYPE_CHECKING, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from telegram import Update, CallbackQuery
    from telegram.ext import CallbackContext

from models import Word
from ui import esc, render
from constants import (
    BTN_SHOW_MEANING, BTN_SKIP, BTN_TTS, BTN_BACK,
    BTN_AGAIN, BTN_HARD, BTN_GOOD, BTN_EASY,
)

logger = logging.getLogger(__name__)


class FlashcardDisplay:
    """Handles flashcard UI rendering and keyboard generation."""
    
    @staticmethod
    def create_front_keyboard(word: Word) -> InlineKeyboardMarkup:
        """Create keyboard for front of flashcard."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(BTN_TTS, callback_data="speak_current:front")],
            [InlineKeyboardButton(BTN_SHOW_MEANING, callback_data=f"flip_card:{word.id}")],
            [InlineKeyboardButton(BTN_SKIP, callback_data=f"skip_flashcard:{word.id}")],
            [InlineKeyboardButton(BTN_BACK, callback_data="back_to_main_menu")],
        ])
        
    @staticmethod
    def create_back_keyboard(word: Word) -> InlineKeyboardMarkup:
        """Create keyboard for back of flashcard with rating buttons."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(BTN_TTS, callback_data="speak_current:back")],
            [InlineKeyboardButton(BTN_AGAIN, callback_data=f"rate_card:{word.id}:1")],
            [InlineKeyboardButton(BTN_HARD, callback_data=f"rate_card:{word.id}:2")],
            [InlineKeyboardButton(BTN_GOOD, callback_data=f"rate_card:{word.id}:3")],
            [InlineKeyboardButton(BTN_EASY, callback_data=f"rate_card:{word.id}:4")],
        ])
        
    @staticmethod
    def format_front_text(word: Word, article: str = "") -> str:
        """Format text for front of flashcard."""
        article_display = f"{article} " if article else ""
        return f"<b>{article_display}{esc(word.german)}</b>"
        
    @staticmethod
    def format_back_text(word: Word, show_details: bool = True) -> str:
        """Format text for back of flashcard with meaning and details."""
        lines = [
            f"<b>{word.article or ''} {word.german}</b>",
            f"<i>معنی:</i> {esc(word.persian)}",
        ]
        
        if show_details:
            if word.english_meaning:
                lines.append(f"<i>English:</i> {esc(word.english_meaning)}")
            if word.word_type:
                lines.append(f"<i>نوع کلمه:</i> {esc(word.word_type)}")
            if word.example_de and word.example_fa:
                lines.append(f"\n<i>مثال:</i>")
                lines.append(f"  {esc(word.example_de)}")
                lines.append(f"  {esc(word.example_fa)}")
                
        return "\n".join(lines)
        
    async def show_front(
        self,
        query: Optional["CallbackQuery"],
        update: "Update",
        word: Word,
    ) -> None:
        """Display front of flashcard."""
        text = self.format_front_text(word, word.article)
        keyboard = self.create_front_keyboard(word)
        await render(query or update, text, reply_markup=keyboard)
        
    async def show_back(
        self,
        query: Optional["CallbackQuery"],
        update: "Update",
        word: Word,
    ) -> None:
        """Display back of flashcard with meaning."""
        text = self.format_back_text(word)
        keyboard = self.create_back_keyboard(word)
        await render(query or update, text, reply_markup=keyboard)


# Global instance
flashcard_display = FlashcardDisplay()
