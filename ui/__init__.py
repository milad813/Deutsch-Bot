"""UI layer — text safety, keyboards, and message rendering.

Phase R3 replaced the 700-line root ``ui.py`` with this package:

* :mod:`ui.text`     — escaping, sanitising, tag-aware chunk splitting
  (no telegram imports, unit-testable in isolation).
* :mod:`ui.keyboards`— inline/reply keyboard builders.
* :mod:`ui.render`   — the single ``render()`` sending entry point with
  graceful HTML → plain-text fallback.

Every historical ``from ui import X`` call site keeps working through the
re-exports below.
"""

from ui.keyboards import (
    back_inline_keyboard,
    callback_button,
    main_menu_keyboard,
    quiz_answer_keyboard,
)
from ui.render import render
from ui.text import (
    ALLOWED_HTML_TAGS,
    _bold_word_in_sentence,
    _chunk_html_text,
    _chunk_plain_text,
    _short_label,
    esc,
    progress_bar,
    sanitize_html,
    split_html_text,
    strip_html,
    to_plain_text,
)

__all__ = [
    # text
    "esc",
    "_short_label",
    "ALLOWED_HTML_TAGS",
    "strip_html",
    "to_plain_text",
    "sanitize_html",
    "split_html_text",
    "_chunk_html_text",
    "_chunk_plain_text",
    "progress_bar",
    "_bold_word_in_sentence",
    # keyboards
    "callback_button",
    "main_menu_keyboard",
    "back_inline_keyboard",
    "quiz_answer_keyboard",
    # render
    "render",
]
