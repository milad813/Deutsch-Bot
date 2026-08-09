import re
from html import escape
from typing import List

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup)
from telegram.error import BadRequest


def esc(text) -> str:
    return escape(str(text if text is not None else ""))


def _short_label(text: str, max_len: int = 64) -> str:
    text = str(text or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_len:
        return text
    suffix = "..."
    suffix_bytes = len(suffix.encode("utf-8"))
    if max_len <= suffix_bytes:
        return suffix[:max_len]
    target = max_len - suffix_bytes
    while text and len(text.encode("utf-8")) > target:
        text = text[:-1]
    return text + suffix


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or ""))


def _truncate_by_bytes(text: str, max_bytes: int) -> str:
    while text and len(text.encode("utf-8")) > max_bytes:
        text = text[:-1]
    return text


def _chunk_plain_text(text: str, max_len: int = 3900) -> List[str]:
    plain = _strip_html(text)
    if len(plain.encode("utf-8")) <= max_len:
        return [plain]
    chunks = []
    current = ""
    for line in plain.split("\n"):
        candidate = current + ("\n" if current else "") + line
        if len(candidate.encode("utf-8")) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line
    while len(current.encode("utf-8")) > max_len:
        part = _truncate_by_bytes(current, max_len - 1)
        if not part:
            part = current[:1]
        chunks.append(part)
        current = current[len(part) :]
    if current:
        chunks.append(current)
    return chunks


def progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(ratio * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _bold_word_in_sentence(sentence: str, word: str) -> str:
    if not sentence or not word:
        return esc(sentence or "")
    pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    match = pattern.search(sentence)
    if not match:
        return esc(sentence)
    before = sentence[: match.start()]
    matched = sentence[match.start() : match.end()]
    after = sentence[match.end() :]
    return f"{esc(before)}<b>{esc(matched)}</b>{esc(after)}"

def main_menu_keyboard(
    due_count: int = 0, streak: int = 0, hard_count: int = 0, is_admin: bool = False
) -> ReplyKeyboardMarkup:
    keyboard = []
    if hard_count > 0:
        keyboard.append([f"🔥 مرور کلمات سخت ({hard_count})"])
    if due_count > 0:
        keyboard.append([f"📅 مرور امروز ({due_count} کلمه)"])
    keyboard.append(["📚 کتاب و درس‌ها", "🎴 فلش‌کارت"])
    keyboard.append(["🤖 کوییز", "📊 داشبورد"])
    if is_admin:
        keyboard.append(["🛡️ پنل مدیریت"])
    keyboard.append(["⚙️ تنظیمات"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def back_inline_keyboard(
    text: str = "🔙 منوی اصلی", callback_data: str = "back_to_main_menu"
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=callback_data)]]
    )


def quiz_answer_keyboard(options: List[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for i, opt in enumerate(options or []):
        label = f"{chr(65 + i)}) {opt}"
        keyboard.append(
            [
                InlineKeyboardButton(
                    _short_label(label, 64), callback_data=f"quiz_ans:{i}"
                )
            ]
        )
    return InlineKeyboardMarkup(keyboard)


async def render(update, text: str, reply_markup=None):
    query = getattr(update, "callback_query", None)
    if query is None and hasattr(update, "edit_message_text"):
        query = update

    async def reply_chunks(target, original_text: str, with_markup: bool = True):
        chunks = _chunk_plain_text(original_text, 3900)
        if not chunks:
            chunks = ["..."]
        for i, chunk in enumerate(chunks):
            markup = reply_markup if (with_markup and i == 0) else None
            await target.reply_text(chunk, reply_markup=markup, parse_mode=None)

    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            msg = str(e).lower()
            if "message is not modified" in msg:
                return
            if "too long" in msg:
                chunks = _chunk_plain_text(text, 3900)
                if not chunks:
                    chunks = ["..."]
                if getattr(query, "message", None):
                    try:
                        await query.edit_message_text(
                            chunks[0], reply_markup=reply_markup, parse_mode=None
                        )
                    except Exception:
                        await query.message.reply_text(
                            chunks[0], reply_markup=reply_markup, parse_mode=None
                        )
                    for chunk in chunks[1:]:
                        await query.message.reply_text(chunk, parse_mode=None)
                return
            if getattr(query, "message", None):
                try:
                    await query.message.reply_text(text, reply_markup=reply_markup)
                except BadRequest as e2:
                    if "too long" in str(e2).lower():
                        await reply_chunks(query.message, text)
                    else:
                        raise
            else:
                raise
        return

    message = getattr(update, "effective_message", None) or getattr(
        update, "message", None
    )
    if message is None and hasattr(update, "reply_text"):
        message = update

    if message:
        try:
            await message.reply_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            if "too long" in str(e).lower():
                await reply_chunks(message, text)
            else:
                raise
