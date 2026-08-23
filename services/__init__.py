"""Services layer — thin compatibility shim over ``services.container``.

During migration this module keeps the historical module-level names
(``db``, ``llm``, ``fsrs``, ``tts``, ``quiz_service``) bound to the ONE
AppContext built here. New code should prefer::

    app = context.bot_data["app"]
    await run_db(app.db.words.get_due_count, user_id)
"""

import asyncio  # noqa: F401  (re-exported for legacy call sites)

import config
from core.async_utils import run_db  # noqa: F401
from core.sessions import SESSION_KEYS, reset_session  # noqa: F401
from services.container import AppContext, build_app
from ui import main_menu_keyboard

# ── single construction point ────────────────────────────────────────
app = build_app()

db = app.db
llm = app.llm
quiz_service = app.quiz
fsrs = app.fsrs
tts = app.tts


def get_main_menu_keyboard(
    due_count: int = 0,
    streak: int = 0,
    hard_count: int = 0,
    is_admin: bool = False,
) -> "ReplyKeyboardMarkup":
    return main_menu_keyboard(due_count, streak, hard_count, is_admin=is_admin)


__all__ = [
    "app",
    "build_app",
    "AppContext",
    "db",
    "llm",
    "quiz_service",
    "fsrs",
    "tts",
    "run_db",
    "reset_session",
    "SESSION_KEYS",
    "get_main_menu_keyboard",
    "config",
]
