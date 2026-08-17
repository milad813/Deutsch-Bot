import re
from html import escape, unescape
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import BadRequest


def esc(text) -> str:
    return escape(str(text if text is not None else ""))


def _short_label(text: str, max_len: int = 64) -> str:
    text = str(text or "")
    if len(text) <= max_len:
        return text
    return text[:max_len - 3].rstrip() + "..."


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or ""))


ALLOWED_HTML_TAGS = {"b", "i", "u", "s", "code", "pre"}


def strip_html(text: str) -> str:
    """حذف کامل تگ‌های HTML و تبدیل entityها به متن ساده."""
    return unescape(_strip_html(text))


def sanitize_html(text: str) -> str:
    """
    امن‌سازی HTML برای Telegram.
    فقط تگ‌های ساده مجاز را نگه می‌دارد.
    """
    if text is None:
        return ""

    text = str(text)

    # حذف کامل script/style
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    escaped = escape(text)

    # برگرداندن فقط تگ‌های مجاز ساده
    for tag in ALLOWED_HTML_TAGS:
        escaped = re.sub(
            rf"&lt;{tag}&gt;",
            f"<{tag}>",
            escaped,
            flags=re.IGNORECASE,
        )
        escaped = re.sub(
            rf"&lt;/{tag}&gt;",
            f"</{tag}>",
            escaped,
            flags=re.IGNORECASE,
        )

    return escaped

def _chunk_html_text(text: str, max_len: int = 3900) -> List[str]:
    """شکستن متن HTML به تکه‌های کوچکتر با حفظ تگ‌ها."""
    if len(text.encode("utf-8")) <= max_len:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        candidate = current + ("\n" if current else "") + line
        if len(candidate.encode("utf-8")) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line

    # اگر یک خط به‌تنهایی خیلی طولانی است
    while current and len(current.encode("utf-8")) > max_len:
        # پیدا کردن آخرین فضای خالی قبل از محدودیت
        encoded = current.encode("utf-8")
        cut_point = max_len
        while cut_point > 0 and encoded[cut_point - 1 : cut_point] != b" ":
            cut_point -= 1
        if cut_point == 0:
            cut_point = max_len
        part = encoded[:cut_point].decode("utf-8", errors="ignore")
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
    """بولد کردن تمام رخدادهای یک کلمه در جمله."""
    if not sentence or not word:
        return esc(sentence or "")

    # پشتیبانی از پسوندهای صرف (مثل schlechten برای schlecht)
    pattern = re.compile(r"\b(" + re.escape(word) + r"[a-zäöüß]*)\b", re.IGNORECASE)

    result = []
    last_end = 0
    for match in pattern.finditer(sentence):
        result.append(esc(sentence[last_end : match.start()]))
        result.append(f"<b>{esc(match.group())}</b>")
        last_end = match.end()
    result.append(esc(sentence[last_end:]))

    return "".join(result)


def main_menu_keyboard(
    due_count: int = 0, streak: int = 0, hard_count: int = 0, is_admin: bool = False
) -> ReplyKeyboardMarkup:
    keyboard = []

    # ─── ردیف اول: اقدام فوری (مهم‌ترین) ───
    if hard_count > 0:
        keyboard.append([f"🔥 مرور کلمات سخت ({hard_count})"])
    elif due_count > 0:
        keyboard.append([f"📅 مرور امروز ({due_count} کلمه)"])

    # ─── ردیف یادگیری ───
    keyboard.append(["📚 کتاب و درس‌ها", "🎴 فلش‌کارت"])

    # ─── ردیف تمرین و آمار ───
    keyboard.append(["🤖 کوییز", "📊 داشبورد"])

    # ─── ردیف تنظیمات و مدیریت ───
    if is_admin:
        keyboard.append(["⚙️ تنظیمات", "🛡️ پنل مدیریت"])
    else:
        keyboard.append(["⚙️ تنظیمات"])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def back_inline_keyboard(
    text: str = "🏠 منوی اصلی",
    callback_data: str = "back_to_main_menu",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=callback_data)]]
    )


def quiz_answer_keyboard(options: List[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for i, opt in enumerate(options or []):
        keyboard.append(
            [
                InlineKeyboardButton(
                    _short_label(opt, 64),
                    callback_data=f"quiz_ans:{i}"
                )
            ]
        )
    return InlineKeyboardMarkup(keyboard)


# در تابع render، جایگزین کردن _chunk_plain_text با _chunk_html_text
async def render(update, text: str, reply_markup=None):
    query = getattr(update, "callback_query", None)
    if query is None and hasattr(update, "edit_message_text"):
        query = update

    async def reply_chunks(target, original_text: str, with_markup: bool = True):
        chunks = _chunk_html_text(original_text, 3900)
        if not chunks:
            chunks = ["..."]

        for i, chunk in enumerate(chunks):
            markup = reply_markup if (with_markup and i == 0) else None
            await target.reply_text(chunk, reply_markup=markup)

    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            msg = str(e).lower()

            if "message is not modified" in msg:
                return

            if "too long" in msg:
                chunks = _chunk_html_text(text, 3900)
                if not chunks:
                    chunks = ["..."]

                if getattr(query, "message", None):
                    try:
                        await query.edit_message_text(
                            chunks[0],
                            reply_markup=reply_markup,
                        )
                    except Exception:
                        await query.message.reply_text(
                            chunks[0],
                            reply_markup=reply_markup,
                        )

                    for chunk in chunks[1:]:
                        await query.message.reply_text(chunk)
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