"""Backwards-compatibility shim (Phase R3).

The real module moved to ``services.srs``; this keeps the historical
``from srs_service import FSRSService`` call sites (scripts, tests)
working until they migrate.
"""

from services.srs import FSRSParams, FSRSService, FSRSState

__all__ = ["FSRSParams", "FSRSService", "FSRSState"]
