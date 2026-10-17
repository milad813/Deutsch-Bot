"""Backwards-compatibility shim (Phase R3).

The real definitions live in ``domain.models`` (pure dataclasses) and
``core.callbacks`` (``CallbackPrefix``). New code should import from
there; this shim keeps the ~22 historical ``from models import ...``
call sites working until they migrate.
"""

from core.callbacks import CallbackPrefix
from domain.models import QuizSession, QuizType, Word

__all__ = ["CallbackPrefix", "QuizSession", "QuizType", "Word"]
