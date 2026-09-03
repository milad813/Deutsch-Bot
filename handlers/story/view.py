"""Story viewing and display functions."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core.callbacks import cb_safe
from models import CallbackPrefix
from services import db, run_db
from ui import back_inline_keyboard, esc, render, sanitize_html
from utils import safe_json_list

logger = logging.getLogger(__name__)


def _safe_id_list(raw):
    result = []
    for item in safe_json_list(raw):
        try:
            result.append(int(item))
        except Exception:
            continue
    return result


async def _build_story_view(story, target_words, user_id: int):
    """Build the (message, keyboard) pair for a story view.

    Shared between :func:`show_story` (called from a callback handler
    that has a ``callback_query`` object) and
    :func:`handlers.story.jobs.render_story_message` (called from a
    job-queue callback that only has a ``(chat_id, message_id)`` pair).
    Returns a 2-tuple ``(msg, kb)`` so the caller can decide whether
    to send, edit, or otherwise dispatch the rendered view.

    Layout is byte-identical to the pre-refactor ``show_story`` body
    (story text, target-word list, and 7 buttons) so end users see
    exactly the same output.
    """
    title = story.get("title_de") or story.get("title_fa") or "داستان"
    msg = f"📖 <b>{esc(title)}</b>\n{sanitize_html(story['text_de'])}"

    if target_words:
        msg += "\n🎯 <b>کلمات این داستان:</b>\n"
        for w in target_words[:12]:
            stats = await run_db(db.words.get_stats_full, user_id, w.id)
            if not stats:
                status = "🆕"
            elif stats.get("phase") == "learning" or stats.get("wrong", 0) > stats.get(
                "correct", 0
            ):
                status = "⚠️"
            else:
                status = "✅"
            msg += f"{status} {esc(w.display_german)}\n"

    # ✅ گروه‌بندی: اصلی / ثانویه / ناوبری
    kb = InlineKeyboardMarkup(
        [
            # ردیف ۱: اصلی‌ترین اکشن
            [
                InlineKeyboardButton(
                    "🔊+📖 بخوان و بشنو", callback_data=cb_safe(CallbackPrefix.STORY_LISTEN_READ, story_id)
                )
            ],
            # ردیف ۲: تمرین
            [
                InlineKeyboardButton(
                    "❓ سوالات", callback_data=cb_safe(CallbackPrefix.STORY_QUIZ, story_id)
                ),
                InlineKeyboardButton(
                    "🧩 کلمات", callback_data=cb_safe(CallbackPrefix.STORY_WORDS, story_id)
                ),
            ],
            # ردیف ۳: کمک و گوش دادن
            [
                InlineKeyboardButton("💡 کمک", callback_data=cb_safe(CallbackPrefix.STORY_HINT, story_id)),
                InlineKeyboardButton(
                    "🎧 فقط بشنو", callback_data=cb_safe(CallbackPrefix.STORY_LISTEN_ONLY, story_id)
                ),
            ],
            # ردیف ۴: ناوبری
            [
                InlineKeyboardButton(
                    "📖 داستان بعدی", callback_data=cb_safe(CallbackPrefix.STORY_NEXT, story['lesson_id'])
                ),
                InlineKeyboardButton(
                    "🔙 بازگشت", callback_data=cb_safe(CallbackPrefix.LESSON, story['lesson_id'])
                ),
            ],
        ]
    )
    return msg, kb


async def show_story(query, context, story_id: int):
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    context.user_data["current_story_id"] = story_id
    context.user_data["story_hint_level"] = 0

    target_ids = _safe_id_list(story.get("target_word_ids"))
    target_words = (await run_db(db.words.get_by_ids, target_ids)) if target_ids else []

    msg, kb = await _build_story_view(story, target_words, query.from_user.id)
    await render(query, msg, reply_markup=kb)


async def show_story_hint(query, context, story_id: int):
    """Show progressive hints for the story."""
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    hint_level = context.user_data.get("story_hint_level", 0)
    user_id = query.from_user.id

    if hint_level == 0:
        target_ids = _safe_id_list(story.get("target_word_ids"))
        words = (await run_db(db.words.get_by_ids, target_ids)) if target_ids else []

        weak_in_story = []
        for w in words:
            stats = await run_db(db.words.get_stats_full, user_id, w.id)
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

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📖 بازگشت به داستان", callback_data=cb_safe(CallbackPrefix.STORY_VIEW, story_id)
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💡 کمک بیشتر", callback_data=cb_safe(CallbackPrefix.STORY_HINT, story_id)
                    )
                ],
            ]
        )
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

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📖 بازگشت به داستان", callback_data=cb_safe(CallbackPrefix.STORY_VIEW, story_id)
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💡 ترجمه کامل", callback_data=cb_safe(CallbackPrefix.STORY_HINT, story_id)
                    )
                ],
            ]
        )
        await render(query, msg, reply_markup=kb)

    else:
        title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
        text_fa = story.get("text_fa") or "ترجمه در دسترس نیست."

        msg = (
            f"💡 <b>راهنمایی سطح ۳: ترجمه کامل</b>\n\n"
            f"📌 {esc(title_fa)}\n\n"
            f"{esc(text_fa)}"
        )

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📖 بازگشت به داستان", callback_data=cb_safe(CallbackPrefix.STORY_VIEW, story_id)
                    )
                ],
            ]
        )
        await render(query, msg, reply_markup=kb)


async def show_story_translation(query, context, story_id: int):
    """Show full Persian translation of the story."""
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
    text_fa = story.get("text_fa") or "ترجمه در دسترس نیست."

    msg = f"🇮🇷 <b>{esc(title_fa)}</b>\n\n{esc(text_fa)}"

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📖 بازگشت به داستان", callback_data=cb_safe(CallbackPrefix.STORY_VIEW, story_id)
                )
            ],
        ]
    )
    await render(query, msg, reply_markup=kb)


async def play_story_listen_read(query, context, story_id: int):
    """Play audio while showing text (listen and read)."""
    story = await run_db(db.stories.get_by_id, story_id)
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
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    title = story.get("title_de") or story.get("title_fa") or "داستان"
    msg = f"🎧 <b>فقط گوش کن: {esc(title)}</b>\n\nبه داستان گوش بده و سعی کن بفهمی."

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔁 تکرار", callback_data=cb_safe(CallbackPrefix.STORY_REPLAY, story_id)
                )
            ],
            [
                InlineKeyboardButton(
                    "📖 نمایش متن", callback_data=cb_safe(CallbackPrefix.STORY_VIEW, story_id)
                )
            ],
            [InlineKeyboardButton("❓ سوالات", callback_data=cb_safe(CallbackPrefix.STORY_QUIZ, story_id))],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت", callback_data=cb_safe(CallbackPrefix.LESSON, story['lesson_id'])
                )
            ],
        ]
    )

    await render(query, msg, reply_markup=kb)

    # Play audio
    from handlers.tts_handlers import send_ephemeral_audio

    await send_ephemeral_audio(query, context, story["text_de"])


async def play_story_audio(query, context, story_id: int):
    """Send story as audio message."""
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    from handlers.tts_handlers import send_ephemeral_audio

    await send_ephemeral_audio(query, context, story["text_de"])


async def show_story_words(query, context, story_id: int):
    """Show vocabulary from the story."""
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    target_ids = _safe_id_list(story.get("target_word_ids"))
    words = (await run_db(db.words.get_by_ids, target_ids)) if target_ids else []

    if not words:
        await render(query, "❌ کلمه‌ای یافت نشد.", reply_markup=back_inline_keyboard())
        return

    user_id = query.from_user.id
    msg = f"🧩 <b>کلمات داستان</b>\n\n"

    for w in words:
        stats = await run_db(db.words.get_stats_full, user_id, w.id)
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

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📖 بازگشت به داستان", callback_data=cb_safe(CallbackPrefix.STORY_VIEW, story_id)
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت به درس", callback_data=cb_safe(CallbackPrefix.LESSON, story['lesson_id'])
                )
            ],
        ]
    )
    await render(query, msg, reply_markup=kb)


async def replay_story(query, context, story_id: int):
    """Replay story audio."""
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    from handlers.tts_handlers import send_ephemeral_audio

    await send_ephemeral_audio(query, context, story["text_de"])
