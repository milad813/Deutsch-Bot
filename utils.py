"""Backwards-compatibility shim (Phase R3).

The real module moved to ``domain.utils``; this keeps the historical
``from utils import safe_json_list`` call sites working until they
migrate.
"""

from domain.utils import safe_id_list, safe_json_list

__all__ = ["safe_id_list", "safe_json_list"]
