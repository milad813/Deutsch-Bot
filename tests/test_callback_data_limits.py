"""AST hygiene: detect literal ``callback_data`` strings longer than 64 bytes.

Telegram rejects any ``callback_data`` payload larger than 64 bytes with
``BadRequest: Button_data_invalid``. This test scans every Python file
under ``handlers/`` and fails if it finds an obvious literal
``callback_data="..."`` or ``callback_data='...'`` whose **constant**
string value exceeds 64 bytes (UTF-8 encoded).

Notes
-----
* We only inspect ``ast.Constant`` values passed via the
  ``callback_data`` keyword. Dynamic f-strings, ``+``-concatenations,
  and ``%``-formatted strings are intentionally ignored here — they're
  hard to evaluate statically, and the matching ``test_callbacks_codec``
  tests already pin down the safe path (``cb_safe``).
* The scanner returns the full list of offenders with file:line so a
  future PR that introduces an over-long literal gets a precise diff
  hint.
"""

from __future__ import annotations

import ast
import pathlib
from typing import List, Tuple

HANDLERS_ROOT = pathlib.Path(__file__).resolve().parent.parent / "handlers"
TELEGRAM_MAX_BYTES = 64


def _iter_handler_files() -> List[pathlib.Path]:
    """Yield every ``handlers/*.py`` and ``handlers/**/*.py`` (sorted)."""
    if not HANDLERS_ROOT.is_dir():
        return []
    files: List[pathlib.Path] = []
    # Top-level *.py
    files.extend(sorted(p for p in HANDLERS_ROOT.glob("*.py") if p.is_file()))
    # Recursive subdirs (*.py), avoiding __pycache__
    for p in sorted(HANDLERS_ROOT.rglob("*.py")):
        if p.is_file() and "__pycache__" not in p.parts and p not in files:
            files.append(p)
    return files


def _scan_for_overlong_literals(path: pathlib.Path) -> List[Tuple[int, str, int]]:
    """Return a list of ``(lineno, value, byte_len)`` for offending literals."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # A broken file shouldn't silently pass — surface it.
        raise AssertionError(f"could not read {path}: {exc}")

    tree = ast.parse(source, filename=str(path))
    offenders: List[Tuple[int, str, int]] = []

    for node in ast.walk(tree):
        # We only care about keyword arguments named ``callback_data``.
        if not isinstance(node, ast.keyword) or node.arg != "callback_data":
            continue
        value = node.value
        # Skip f-strings, joins, and function calls; only flag Constants.
        if not isinstance(value, ast.Constant):
            continue
        if not isinstance(value.value, str):
            continue
        text = value.value
        size = len(text.encode("utf-8"))
        if size > TELEGRAM_MAX_BYTES:
            offenders.append((value.lineno, text, size))

    return offenders


def test_no_overlong_callback_data_literals():
    """No handler may build an inline keyboard with a constant > 64 bytes."""
    all_offenders: List[str] = []
    for py_file in _iter_handler_files():
        rel = py_file.relative_to(HANDLERS_ROOT.parent)
        for lineno, value, size in _scan_for_overlong_literals(py_file):
            preview = value if len(value) <= 80 else value[:77] + "..."
            all_offenders.append(
                f"{rel.as_posix()}:{lineno}: {size} bytes -> {preview!r}"
            )

    assert not all_offenders, (
        "Found literal callback_data strings longer than "
        f"{TELEGRAM_MAX_BYTES} bytes (Telegram limit). "
        "Use ``cb_safe`` from ``core.callbacks`` instead, or shorten the "
        "constant. Offending sites:\n  " + "\n  ".join(all_offenders)
    )


def test_scanner_walks_expected_files():
    """Smoke test: the scanner must actually visit the files we expect."""
    files = [p for p in _iter_handler_files()]
    # Sanity: at minimum the migration targets should be present.
    expected_names = {
        "menus.py",
        "grammar_handlers.py",
        "listening_handlers.py",
    }
    assert expected_names.issubset({p.name for p in files}), (
        f"scanner missed expected files: {expected_names - {p.name for p in files}}"
    )
    # And the nested learning/story packages should be reached too.
    rels = {p.relative_to(HANDLERS_ROOT).as_posix() for p in files}
    assert any(rel.startswith("learning/") for rel in rels), rels
    assert any(rel.startswith("story/") for rel in rels), rels
