"""Services layer — lazy, injectable access to the shared AppContext.

Phase R2: the :class:`~services.container.AppContext` is **no longer built
at import time**. Importing this module (and therefore ``handlers`` or
``bot``) is side-effect free; the context is constructed on first use by
:func:`get_app`, exactly once, from :func:`services.container.build_app`.

``bot.main()`` calls ``get_app()`` explicitly and stores the returned
instance in ``application.bot_data["app"]`` — that instance is the
canonical one for production code. New handler code should prefer::

    app = context.bot_data["app"]
    await run_db(app.db.words.get_due_count, user_id)

Legacy call sites keep working through late-binding proxies::

    from services import db          # binds a proxy, builds nothing
    stats = await run_db(db.words.get_due_count, user_id)

The proxy forwards attribute access to the current AppContext on every
use, so ``monkeypatch.setattr(services.db.words, "get_count", ...)`` in
tests continues to patch the very object handlers resolve to (identity is
preserved). Tests can replace the whole context with
:func:`set_app` / :func:`reset_app`.

Nothing below this layer may construct Database/LLM/TTS objects on its own.
"""

import asyncio  # noqa: F401  (re-exported for legacy call sites)
import threading
from typing import TYPE_CHECKING, Any, Optional

import config  # noqa: F401  (re-exported for legacy call sites)
from core.async_utils import run_db  # noqa: F401
from core.sessions import SESSION_KEYS, reset_session  # noqa: F401
from services.container import AppContext, build_app
from ui import main_menu_keyboard

if TYPE_CHECKING:
    from telegram import ReplyKeyboardMarkup

# ── single construction point (lazy) ─────────────────────────────────
_app: Optional[AppContext] = None
_app_lock = threading.RLock()


def get_app() -> AppContext:
    """Return the shared AppContext, building it on first call."""
    global _app
    with _app_lock:
        if _app is None:
            _app = build_app()
        return _app


def set_app(app_ctx: AppContext) -> None:
    """Replace the shared AppContext (used by tests and tooling)."""
    global _app
    with _app_lock:
        _app = app_ctx


def reset_app() -> None:
    """Drop the cached AppContext; the next access rebuilds it."""
    global _app
    with _app_lock:
        _app = None


def is_app_built() -> bool:
    """True once :func:`get_app` has been called at least once."""
    return _app is not None


class _ServiceProxy:
    """Late-binding forwarder for one AppContext attribute.

    ``db.words.get_count`` resolves ``db → get_app().db`` on *every*
    access, so the name can be imported at module import time without
    constructing the AppContext, while still always hitting the current
    context (including one swapped in by ``set_app``).
    """

    __slots__ = ("_attr",)

    def __init__(self, attr: str) -> None:
        self._attr = attr

    def __getattr__(self, name: str) -> Any:
        target = get_app()
        if self._attr != "app":
            target = getattr(target, self._attr)
        return getattr(target, name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<_ServiceProxy services.{self._attr}>"


app = _ServiceProxy("app")  # type: ignore[assignment]
db = _ServiceProxy("db")  # type: ignore[assignment]
llm = _ServiceProxy("llm")  # type: ignore[assignment]
quiz_service = _ServiceProxy("quiz")  # type: ignore[assignment]
fsrs = _ServiceProxy("fsrs")  # type: ignore[assignment]
tts = _ServiceProxy("tts")  # type: ignore[assignment]


def get_main_menu_keyboard(
    due_count: int = 0,
    streak: int = 0,
    hard_count: int = 0,
    is_admin: bool = False,
) -> "ReplyKeyboardMarkup":
    return main_menu_keyboard(due_count, streak, hard_count, is_admin=is_admin)


__all__ = [
    "get_app",
    "set_app",
    "reset_app",
    "is_app_built",
    "build_app",
    "AppContext",
    "app",
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
