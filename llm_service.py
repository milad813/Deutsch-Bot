"""Backwards-compatibility shim (Phase R3).

The real module moved to ``services.llm``; this keeps the historical
``from llm_service import LLMService`` call sites (scripts, tests)
working until they migrate.
"""

from services.llm import LLMService

__all__ = ["LLMService"]
