"""UI helpers and keyboard builders."""

from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Optional


def esc(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main_menu_keyboard(
    due_count: int = 0,
    streak: int = 0,
    pending: int = 0,
) -> ReplyKeyboardMarkup:
    """Build the main menu keyboard."""
    keyboard = [
        ["📚 کتاب و درس‌ها", "🎴 فلش‌کارت"],
        ["🤖 کوییز", "📊 داشبورد"],
        ["⚙️ تنظیمات"],
    ]
    
    # Add quick actions if there are due/hard words
    extra_row = []
    if due_count > 0:
        extra_row.append(f"📅 مرور امروز ({due_count})")
    if pending > 0:
        extra_row.append(f"🔥 مرور کلمات سخت ({pending})")
    
    if extra_row:
        keyboard.append(extra_row)
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def back_inline_keyboard() -> InlineKeyboardMarkup:
    """Create a simple back button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main_menu")]])


def back_inline_keyboard_custom(text: str = "🔙 بازگشت", data: str = "back_to_main_menu") -> InlineKeyboardMarkup:
    """Create a custom back button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=data)]])


def render_template(template_name: str, **kwargs) -> str:
    """Simple template rendering (can be extended)."""
    # For now, just return a placeholder
    # In production, use Jinja2 or similar
    return f"Template: {template_name} with {kwargs}"
