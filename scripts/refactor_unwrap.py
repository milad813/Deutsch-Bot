"""One-shot refactor helper: unwrap redundant try/finally lock cleanup.

Phase-0 kept ``finally: context.user_data.pop("<lock>", None)`` blocks inside
answer handlers even though ``core.locks.callback_guard`` already pops the
key in its own ``finally``. This script removes those wrappers (and replaces
hand-rolled lock boilerplate with the decorator) without touching anything
else. Safe to delete after use.

Usage: python scripts/refactor_unwrap.py   (run once from project root)
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (relative path, function name, lock key or None when only unwrapping)
TARGETS = [
    ("handlers/learning/ltr_handlers.py", "handle_ltr_answer", None),
    ("handlers/story/quiz.py", "handle_story_answer", None),
    ("handlers/learning/flashcard_session.py", "handle_flip_card",
     "flashcard_flip_lock"),
    ("handlers/learning/flashcard_session.py", "handle_skip_flashcard",
     "flashcard_skip_lock"),
    ("handlers/learning/ltr_handlers.py", "handle_ltr_learned",
     "ltr_learned_lock"),
]


def find_func(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise SystemExit(f"function not found: {name}")


def strip_boilerplate(src: str, func, lock_key: str) -> str:
    """Remove manual lock lines before first try; add @callback_guard."""
    body = list(func.body)
    try_idx = next(i for i, s in enumerate(body) if isinstance(s, ast.Try))
    preamble = body[:try_idx]
    if preamble and isinstance(preamble[0], ast.Expr) and isinstance(
        preamble[0].value, ast.Constant
    ):
        preamble = preamble[1:]  # docstring stays

    found = set()
    for stmt in preamble:
        seg = ast.get_source_segment(src, stmt) or ""
        if "lock_key" not in seg:
            raise SystemExit(f"{func.name}: unexpected preamble:\n{seg}")
        m = re.search(r'lock_key\s*=\s*["\']([^"\']+)["\']', seg)
        if m:
            found.add(m.group(1))
    if found != {lock_key}:
        raise SystemExit(f"{func.name}: keys {found} != {{{lock_key!r}}}")

    doc_end = 0
    if isinstance(func.body[0], ast.Expr) and isinstance(
        func.body[0].value, ast.Constant
    ):
        doc_end = func.body[0].end_lineno
    cut_start = max(doc_end, body[0].lineno - 1)      # 0-based
    cut_end = body[try_idx].lineno - 1                # line of `try:`

    lines = src.splitlines(keepends=True)
    del lines[cut_start:cut_end]
    src = "".join(lines)

    indent = " " * func.col_offset
    insert_at = func.lineno - 1 - len(func.decorator_list)
    lines = src.splitlines(keepends=True)
    lines.insert(insert_at, f'{indent}@callback_guard("{lock_key}")\n')
    return "".join(lines)


def unwrap_try_finally(src: str, func) -> str:
    body = list(func.body)
    # Tolerate a leading docstring.
    if body and isinstance(body[0], ast.Expr) and isinstance(
        body[0].value, ast.Constant
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Try):
        raise SystemExit(f"{func.name}: expected lone try/finally body")
    tr = body[0]
    if tr.handlers or tr.orelse or not tr.finalbody:
        raise SystemExit(f"{func.name}: try is not a bare finally wrapper")

    lines = src.splitlines(keepends=True)

    h = tr.lineno - 1                                  # `try:` line
    b0 = tr.body[0].lineno - 1                         # first inner stmt
    bend = tr.body[-1].end_lineno                      # 0-based exclusive

    # Find the real `finally:` line (comments may sit between it and body).
    f0 = next(
        i
        for i in range(tr.finalbody[0].lineno - 1, b0, -1)
        if lines[i].strip().startswith("finally:")
    )

    out = []
    for i, line in enumerate(lines):
        if i == h or (f0 <= i < tr.end_lineno):
            continue                                   # drop header+finally
        if b0 <= i < bend and line.strip():
            out.append(line[4:] if line.startswith("    ") else line)
        else:
            out.append(line)
    return "".join(out)



def refactor(path: Path, func_name: str, lock_key) -> None:
    src = path.read_text(encoding="utf-8")
    func = find_func(ast.parse(src), name=func_name)

    if lock_key is not None:
        src = strip_boilerplate(src, func, lock_key)
        func = find_func(ast.parse(src), name=func_name)

    src = unwrap_try_finally(src, func)
    ast.parse(src)
    compile(src, str(path), "exec")
    path.write_text(src, encoding="utf-8")
    print(f"refactored {path.name}:{func_name}")


def main() -> None:
    by_file = {}
    for rel, fname, key in TARGETS:
        by_file.setdefault(ROOT / rel, []).append((fname, key))
    for path, targets in by_file.items():
        # Bottom-up within a file so earlier line numbers stay valid.
        for fname, key in sorted(targets, reverse=True):
            refactor(path, fname, key)
    print("done")


if __name__ == "__main__":
    sys.exit(main())

