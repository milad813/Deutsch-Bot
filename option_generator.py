"""Backwards-compatibility shim (Phase R3).

The real module moved to ``domain.option_generator``; this keeps the
historical ``from option_generator import get_wrong_options`` call sites
working until they migrate.
"""

from domain.option_generator import get_wrong_options, make_options, sample_unique

__all__ = ["get_wrong_options", "make_options", "sample_unique"]
