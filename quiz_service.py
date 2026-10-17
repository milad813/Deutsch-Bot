"""Backwards-compatibility shim (Phase R3).

The real module moved to ``services.quiz``; this keeps the historical
``from quiz_service import QuizService`` call sites (scripts, tests)
working until they migrate.
"""

from services.quiz import QuizService

__all__ = ["QuizService"]
