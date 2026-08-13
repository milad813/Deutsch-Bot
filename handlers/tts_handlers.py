"""TTS audio sending and cleanup handlers."""
import logging
from typing import Dict
import config
from services import db, tts
from ui import strip_html

logger = logging.getLogger(__name__)

_tts_jobs: Dict[int, object] = {}


async def cleanup_tts(context, user_id: int):
    job = _tts_jobs.pop(user_id, None)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass
    info = context.user_data.pop("tts_message", None)
    if info:
        try:
            await context.bot.delete_message(chat_id=info[0], message_id=info[1])
        except Exception:
            pass


async def _auto_delete_tts(context):
    chat_id, message_id = context.job.data
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def send_ephemeral_audio(query, context, text: str):
    if not query or not query.message:
        return
    text = strip_html(text or "").strip()
    if not text:
        await query.message.reply_text("❌ متنی برای خواندن وجود ندارد.")
        return
    user_id = query.from_user.id
    await cleanup_tts(context, user_id)
    audio_path = await tts.get_audio_path(text)
    if not audio_path:
        await query.message.reply_text("❌ قابلیت تلفظ در دسترس نیست.")
        return
    chat_id = query.message.chat_id
    title = text if len(text) <= 80 else text[:77] + "..."
    try:
        with open(audio_path, "rb") as f:
            if config.TTS_SEND_AS_DOCUMENT:
                sent = await context.bot.send_document(
                    chat_id=chat_id, document=f, caption=f"🔊 {title}",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                    disable_content_type_detection=True,
                )
            else:
                sent = await context.bot.send_audio(
                    chat_id=chat_id, audio=f, title=title, performer="German Bot",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                )
    except Exception as e:
        logger.error("Failed to send audio: %s", e)
        await query.message.reply_text("❌ خطا در پخش صدا")
        return
    context.user_data["tts_message"] = (chat_id, sent.message_id)
    if config.TTS_AUTO_DELETE_SECONDS > 0 and context.job_queue:
        job = context.job_queue.run_once(
            _auto_delete_tts, config.TTS_AUTO_DELETE_SECONDS,
            data=(chat_id, sent.message_id), chat_id=chat_id, user_id=user_id,
        )
        _tts_jobs[user_id] = job


async def handle_speak_current(query, context, suffix: str):
    text = context.user_data.get("current_tts_text")
    if not text:
        fc = context.user_data.get("current_flashcard") or {}
        word_id = fc.get("word_id")
        word = db.get_word_by_id(word_id) if word_id else None
        text = word.display_german if word else None
    if not text:
        try:
            await query.answer("❌ متن تلفظ موجود نیست.", show_alert=True)
        except Exception:
            pass
        return
    await send_ephemeral_audio(query, context, text)