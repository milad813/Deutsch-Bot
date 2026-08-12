"""Story viewing and display functions."""

import logging
from typing import List, Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services import db, tts
from ui import back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


def _safe_json_list(raw):
    try:
        data = __import__('json').loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _safe_id_list(raw):
    result = []
    for item in _safe_json_list(raw):
        try:
            result.append(int(item))
        except Exception:
            continue
    return result


async def show_story(query, context, story_id: int):
    """Display a story with options."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    context.user_data["current_story_id"] = story_id
    context.user_data["story_hint_level"] = 0

    title = story.get("title_de") or story.get("title_fa") or "داستان"

    target_ids = _safe_id_list(story.get("target_word_ids"))
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []

    msg = f"📖 <b>{esc(title)}</b>\n{esc(story['text_de'])}"

    if words:
        msg += "\n\n🎯 <b>کلمات این داستان:</b>\n"
        user_id = query.from_user.id
        for w in words[:12]:
            stats = db.get_word_stats_full(user_id, w.id)
            if not stats:
                status = "🆕"
            elif stats.get("phase") == "learning" or stats.get("wrong", 0) > stats.get("correct", 0):
                status = "⚠️"
            else:
                status = "✅"
            msg += f"{status} {esc(w.display_german)}\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊+📖 همزمان بخوان و بشنو", callback_data=f"story_listen_read:{story_id}")],
        [InlineKeyboardButton("🎧 فقط بشنو (بدون متن)", callback_data=f"story_listen_only:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("💡 کمک", callback_data=f"story_hint:{story_id}")],
        [InlineKeyboardButton("🧩 کلمات", callback_data=f"story_words:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{story['lesson_id']}")],
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{story['lesson_id']}")],
    ])
    await render(query, msg, reply_markup=kb)


async def show_story_hint(query, context, story_id: int):
    """Show progressive hints for the story."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    hint_level = context.user_data.get("story_hint_level", 0)
    user_id = query.from_user.id

    if hint_level == 0:
        target_ids = _safe_id_list(story.get("target_word_ids"))
        words = db.get_word_objects_by_ids(target_ids) if target_ids else []

        weak_in_story = []
        for w in words:
            stats = db.get_word_stats_full(user_id, w.id)
            if not stats:
                weak_in_story.append(w)
            elif stats.get("wrong", 0) > stats.get("correct", 0):
                weak_in_story.append(w)

        if not weak_in_story:
            weak_in_story = words[:3]

        msg = "💡 <b>راهنمایی سطح ۱: کلمات کلیدی</b>\n\n"
        for w in weak_in_story[:3]:
            msg += f"🔹 <b>{esc(w.display_german)}</b> = {esc(w.persian)}\n"
        msg += "\n📖 حالا دوباره داستان را بخوان."

        context.user_data["story_hint_level"] = 1

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
            [InlineKeyboardButton("💡 کمک بیشتر", callback_data=f"story_hint:{story_id}")],
        ])
        await render(query, msg, reply_markup=kb)

    elif hint_level == 1:
        title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
        text_fa = story.get("text_fa") or ""

        sentences = text_fa.split(".")
        summary = ". ".join(sentences[:3]) + "." if len(sentences) > 3 else text_fa

        msg = (
            f"💡 <b>راهنمایی سطح ۲: خلاصه‌ی فارسی</b>\n\n"
            f"📌 {esc(title_fa)}\n"
            f"{esc(summary)}\n\n"
            f"📖 حالا سعی کن متن آلمانی را دوباره بخوانی."
        )

        context.user_data["story_hint_level"] = 2

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
            [InlineKeyboardButton("💡 ترجمه کامل", callback_data=f"story_hint:{story_id}")],
        ])
        await render(query, msg, reply_markup=kb)

    else:
        title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
        text_fa = story.get("text_fa") or "ترجمه در دسترس نیست."

        msg = (
            f"💡 <b>راهنمایی سطح ۳: ترجمه کامل</b>\n\n"
            f"📌 {esc(title_fa)}\n\n"
            f"{esc(text_fa)}"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
        ])
        await render(query, msg, reply_markup=kb)


async def show_story_translation(query, context, story_id: int):
    """Show full Persian translation of the story."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
    text_fa = story.get("text_fa") or "ترجمه در دسترس نیست."

    msg = f"🇮🇷 <b>{esc(title_fa)}</b>\n\n{esc(text_fa)}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
    ])
    await render(query, msg, reply_markup=kb)


async def play_story_listen_read(query, context, story_id: int):
    """Play audio while showing text (listen and read)."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    context.user_data["current_tts_text"] = story["text_de"]
    
    # Show story first
    await show_story(query, context, story_id)
    
    # Then play audio
    from handlers.tts_handlers import send_ephemeral_audio
    await send_ephemeral_audio(query, context, story["text_de"])


async def play_story_listen_only(query, context, story_id: int):
    """Play audio without showing text (listening only)."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    title = story.get("title_de") or story.get("title_fa") or "داستان"
    msg = f"🎧 <b>فقط گوش کن: {esc(title)}</b>\n\nبه داستان گوش بده و سعی کن بفهمی."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 تکرار", callback_data=f"story_replay:{story_id}")],
        [InlineKeyboardButton("📖 نمایش متن", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"lesson_{story['lesson_id']}")],
    ])
    
    await render(query, msg, reply_markup=kb)
    
    # Play audio
    from handlers.callback_router import send_ephemeral_audio
    await send_ephemeral_audio(query, context, story["text_de"])


async def play_story_audio(query, context, story_id: int):
    """Send story as audio message."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    from handlers.callback_router import send_ephemeral_audio
    await send_ephemeral_audio(query, context, story["text_de"])


async def show_story_words(query, context, story_id: int):
    """Show vocabulary from the story."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    target_ids = _safe_id_list(story.get("target_word_ids"))
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []

    if not words:
        await render(query, "❌ کلمه‌ای یافت نشد.", reply_markup=back_inline_keyboard())
        return

    user_id = query.from_user.id
    msg = f"🧩 <b>کلمات داستان</b>\n\n"
    
    for w in words:
        stats = db.get_word_stats_full(user_id, w.id)
        if not stats:
            status = "🆕 جدید"
        elif stats.get("phase") == "learning":
            status = "⚠️ در حال یادگیری"
        elif stats.get("wrong", 0) > stats.get("correct", 0):
            status = "🔴 ضعیف"
        else:
            status = "✅ مسلط"
        
        msg += f"{status} • <b>{esc(w.display_german)}</b>\n"
        msg += f"  → {esc(w.persian)}\n"
        if w.extra_forms_line:
            msg += f"  → {esc(w.extra_forms_line)}\n"
        if w.collocation_line:
            msg += f"  → {esc(w.collocation_line)}\n"
        msg += "\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{story['lesson_id']}")],
    ])
    await render(query, msg, reply_markup=kb)


async def replay_story(query, context, story_id: int):
    """Replay story audio."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    from handlers.callback_router import send_ephemeral_audio
    await send_ephemeral_audio(query, context, story["text_de"])
