"""Backwards-compatibility shim (Phase R3).

The real module moved to ``services.tts``; this keeps the historical
``from tts_service import TTSService`` call sites (scripts, tests)
working until they migrate.
"""

from services.tts import TTSService

__all__ = ["TTSService"]
