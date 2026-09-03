"""Background job for story generation.

Phase 1, item 4: pull the (potentially multi-second) LLM story
generation out of the inline callback handler and run it in a
``context.job_queue`` callback instead.

Payload contract (``context.job.data``) is a plain ``dict``::

    {
        "user_id":             int,
        "chat_id":             int,
        "lesson_id":           int,
        "progress_message_id": int,
        "exclude_ids":         list[int],
        "user_data":           dict,
        "job_name":            str,
    }
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest

from services import db, llm, run_db
from utils import safe_id_list
from core.logging_utils import log_event

logger = logging.getLogger(__name__)


_REQUIRED_KEYS: tuple = (
    "user_id",
    "chat_id",
    "lesson_id",
    "progress_message_id",
)


_active_story_jobs: Dict[int, str] = {}


def _story_job_name(user_id: int) -> str:
    return f"story_gen:{int(user_id)}"


def register_active_story_job(user_id: int, job_name: str) -> None:
    _active_story_jobs[int(user_id)] = job_name


def clear_active_story_job(user_id: int, job_name: Optional[str] = None) -> None:
    uid = int(user_id)
    stored = _active_story_jobs.get(uid)
    if job_name is None or stored == job_name:
        _active_story_jobs.pop(uid, None)


def has_active_story_job(user_id: int) -> bool:
    return int(user_id) in _active_story_jobs


def _validate_payload(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return f"payload is not a dict: {type(data).__name__}"
    missing: List[str] = []
    for key in _REQUIRED_KEYS:
        if key not in data:
            missing.append(key)
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    for key in _REQUIRED_KEYS:
        value = data[key]
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{key!r} must be int, got {type(value).__name__}"
    exclude_ids = data.get("exclude_ids")
    if exclude_ids is not None and not isinstance(exclude_ids, list):
        return f"'exclude_ids' must be list[int], got {type(exclude_ids).__name__}"
    user_data = data.get("user_data")
    if user_data is not None and not isinstance(user_data, dict):
        return f"'user_data' must be dict, got {type(user_data).__name__}"
    return None


async def _edit_progress(
    context,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    bot = getattr(context, "bot", None)
    if bot is None:
        return
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except BadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return
        if any(kw in msg for kw in ("parse", "entities", "unsupported")):
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=None,
                )
            except Exception:
                logger.warning("story progress: plain-text retry failed", exc_info=True)
        else:
            logger.warning("story progress: edit failed (%s)", e)


async def generate_story_job(context) -> None:
    data = context.job.data if getattr(context, "job", None) else None
    err = _validate_payload(data)
    if err:
        logger.error("story job: %s", err)
        return
    user_id: int = data["user_id"]
    chat_id: int = data["chat_id"]
    lesson_id: int = data["lesson_id"]
    progress_mid: int = data["progress_message_id"]
    job_name: str = data.get("job_name") or _story_job_name(user_id)
    user_data: dict = data.get("user_data")
    if not isinstance(user_data, dict):
        user_data = {}
    exclude_ids = set(int(i) for i in (data.get("exclude_ids") or []))
    try:
        if not llm.is_available():
            await _edit_progress(
                context, chat_id, progress_mid,
                "\u274c \u0642\u0627\u0628\u0644\u06cc\u062a LLM \u062f\u0631 \u062d\u0627\u0644 \u062d\u0627\u0636\u0631 \u0641\u0639\u0627\u0644 \u0646\u06cc\u0633\u062a.",
            )
            return
        story = await _generate_story_for_lesson(user_id, lesson_id, exclude_ids)
        if not story:
            await _edit_progress(
                context, chat_id, progress_mid,
                "\u274c \u0633\u0627\u062e\u062a \u062f\u0627\u0633\u062a\u0627\u0646 \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062f. \u062f\u0648\u0628\u0627\u0631\u0647 \u062a\u0644\u0627\u0634 \u06a9\u0646.",
            )
            return
        target_ids = safe_id_list(story.get("target_word_ids"))
        if target_ids:
            session = list(user_data.get("story_session_word_ids") or [])
            for tid in target_ids:
                if tid not in session:
                    session.append(tid)
            user_data["story_session_word_ids"] = session
        user_data["current_story_id"] = story["id"]
        user_data["story_hint_level"] = 0
        log_event(
            logger,
            logging.INFO,
            "story_generation_succeeded",
            user_id=int(user_id),
            lesson_id=int(lesson_id),
            story_id=int(story["id"]),
        )
        await render_story_message(
            context, chat_id, progress_mid, story["id"], user_id,
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "story_generation_failed",
            user_id=int(user_id),
            lesson_id=int(lesson_id),
            stage="job_execution",
            error_type=type(exc).__name__,
        )
        logger.exception("story job failed for user %s: %s", user_id, exc)
        try:
            await _edit_progress(
                context, chat_id, progress_mid,
                "\u274c \u062e\u0637\u0627 \u062f\u0631 \u0633\u0627\u062e\u062a \u062f\u0627\u0633\u062a\u0627\u0646. \u0644\u0637\u0641\u0627\u064b \u062f\u0648\u0628\u0627\u0631\u0647 \u062a\u0644\u0627\u0634 \u06a9\u0646.",
            )
        except Exception:
            logger.exception("story job: error-editing the error message also failed")
    finally:
        clear_active_story_job(user_id, job_name)
        try:
            user_data.pop("story_generating", None)
            user_data.pop("story_active_job_name", None)
        except Exception:
            pass


async def render_story_message(
    context,
    chat_id: int,
    message_id: int,
    story_id: int,
    user_id: int,
) -> None:
    from handlers.story.view import _build_story_view
    story = await run_db(db.stories.get_by_id, story_id)
    if not story:
        await _edit_progress(
            context, chat_id, message_id,
            "\u274c \u062f\u0627\u0633\u062a\u0627\u0646 \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f.",
        )
        return
    target_ids = safe_id_list(story.get("target_word_ids"))
    target_words = (
        await run_db(db.words.get_by_ids, target_ids) if target_ids else []
    )
    msg, kb = await _build_story_view(story, target_words, user_id)
    await _edit_progress(context, chat_id, message_id, msg, reply_markup=kb)


async def _generate_story_for_lesson(user_id: int, lesson_id: int, exclude_ids):
    from handlers.story.core import _generate_story_for_lesson as _gen
    return await _gen(user_id, lesson_id, exclude_ids)
