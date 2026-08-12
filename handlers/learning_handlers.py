"""Learning handlers - backward compatibility re-exports only."""
from handlers.learning import (
    FlashcardSessionManager,
    start_flashcard_session,
    handle_next_flashcard,
    handle_flip_card,
    handle_rate_card,
    handle_skip_flashcard,
)
from handlers.learning.ltr_handlers import (
    handle_study_lesson,
    handle_ltr_ready,
    handle_ltr_summary,
    handle_ltr_exit,
    handle_ltr_answer,
)
from handlers.learning.ltr_session import LTRSessionManager

__all__ = [
    "FlashcardSessionManager",
    "LTRSessionManager",
    "start_flashcard_session",
    "handle_next_flashcard",
    "handle_flip_card",
    "handle_rate_card",
    "handle_skip_flashcard",
    "handle_study_lesson",
    "handle_ltr_ready",
    "handle_ltr_summary",
    "handle_ltr_exit",
    "handle_ltr_answer",
]