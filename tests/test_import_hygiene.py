"""AST hygiene guard: handlers may only use names they actually define/import.

Systematic regression kill for the Phase-0 bug family:
- B4/B7: ``run_db`` used but not imported (listening / LTR / tts)
- B11: ``_render_final_fallback_question`` called but never defined

Limitation: resolution is file-wide (a name defined in *any* scope of the
file counts), so this catches "missing import / missing definition" classes,
not shadowing mistakes.
"""

import ast
import builtins
import pathlib

import handlers

HANDLERS_DIR = pathlib.Path(handlers.__file__).parent

_ALLOWED = set(dir(builtins)) | {"__name__", "__file__", "__doc__"}


def _bound_names(tree: ast.AST) -> set:
    """Every name the module binds somewhere (imports, defs, stores...)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import,)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            args = list(getattr(node.args, "args", []))
            args += list(getattr(node.args, "kwonlyargs", []))
            names.update(a.arg for a in args)
            if node.args.vararg:
                names.add(node.args.vararg.arg)
            if node.args.kwarg:
                names.add(node.args.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def test_no_undefined_names_in_handlers():
    offenders = []
    for path in sorted(HANDLERS_DIR.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        bound = _bound_names(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in bound and node.id not in _ALLOWED:
                    rel = path.relative_to(HANDLERS_DIR)
                    offenders.append(f"{rel}:{node.lineno} uses undefined '{node.id}'")

    assert not offenders, "undefined names found:\n" + "\n".join(offenders)


def test_run_db_usage_requires_module_level_import():
    """Targeted B4/B7 guard: any file calling run_db must import it at top."""
    for path in sorted(HANDLERS_DIR.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        calls_run_db = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "run_db"
            for n in ast.walk(tree)
        )
        imports_run_db = any(
            isinstance(n, ast.ImportFrom)
            and n.module in ("services", "core.async_utils")
            and any(a.name == "run_db" for a in n.names)
            and n.col_offset == 0  # module level only
            for n in tree.body
        )
        if calls_run_db:
            rel = path.relative_to(HANDLERS_DIR)
            assert imports_run_db, f"{rel} calls run_db without importing it"

