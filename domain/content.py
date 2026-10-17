"""Validation of stored learning content, independent of Telegram."""

from typing import Any, Optional
from domain.utils import safe_json_list


def object_list(raw: Any) -> list[dict]:
    return [item for item in safe_json_list(raw) if isinstance(item, dict)]


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip())
    )


def story_question(raw: dict) -> Optional[dict]:
    text = raw.get("question") or raw.get("q")
    if not isinstance(text, str) or not text.strip():
        return None
    options = text_list(raw.get("options"))
    correct = raw.get("correct_answer")
    if not isinstance(correct, str) or not correct.strip():
        index = raw.get("correct_index")
        original = raw.get("options")
        if (
            not isinstance(original, list)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(original)
            or not isinstance(original[index], str)
        ):
            return None
        correct = original[index]
    correct = correct.strip()
    if not correct:
        return None
    if correct not in options:
        options.append(correct)
    if len(options) < 2:
        return None
    kind = raw.get("question_type")
    if kind not in ("comprehension", "vocabulary", "detail"):
        kind = "comprehension"
    return {
        "question": text.strip(),
        "options": options,
        "correct_answer": correct,
        "question_type": kind,
    }
