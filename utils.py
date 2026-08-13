"""Shared utility functions."""

import json
from typing import Any, List


def safe_json_list(raw: Any) -> List[Any]:
    """Safely parse a JSON array string. Returns [] on failure."""
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def safe_id_list(raw: Any) -> List[int]:
    """Safely parse a JSON array of IDs. Returns [] on failure."""
    result = []
    for item in safe_json_list(raw):
        try:
            result.append(int(item))
        except Exception:
            continue
    return result
