"""Application container — the single construction point for shared services.

``bot.main()`` builds one :class:`AppContext` via :func:`build_app` (through
the lazy ``services.get_app()``) and stores it in
``application.bot_data["app"]``. The ``services`` package exposes the same
context through late-binding proxies during the migration period, so
existing ``from services import db`` call sites keep working while handlers
gradually switch to ``context.bot_data["app"]``. Construction is deferred
to first use — importing anything never opens the database.

Nothing below this layer may construct Database/LLM/TTS objects on its own.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import config
from database import Database
from services.llm import LLMService
from services.quiz import QuizService
from services.srs import FSRSService
from services.tts import TTSService

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Aggregates every long-lived service the bot needs."""

    db: Database
    llm: LLMService
    quiz: QuizService
    fsrs: FSRSService
    tts: TTSService

    def close(self) -> None:
        """Release resources (idempotent)."""
        self.db.close()


def build_app(
    db_path: Optional[str] = None,
    backup_keep_days: Optional[int] = None,
    backup_keep_max: Optional[int] = None,
) -> AppContext:
    """Construct all services once, wired together."""
    db = Database(
        db_path or config.DB_PATH,
        backup_keep_days=(
            config.BACKUP_KEEP_DAYS if backup_keep_days is None else backup_keep_days
        ),
        backup_keep_max=(config.BACKUP_KEEP_MAX if backup_keep_max is None else backup_keep_max),
    )
    app = AppContext(
        db=db,
        llm=LLMService(db=db),
        quiz=QuizService(),
        fsrs=FSRSService(db),
        tts=TTSService(),
    )
    logger.debug("AppContext built (db=%s)", db_path or config.DB_PATH)
    return app
