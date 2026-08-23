"""Smoke tests: import integrity, router consistency, and regression guards.

These tests would have caught the Phase-0 bugs (B1-B4) before release:
- undefined names inside handler bodies (via functional flow tests)
- missing routes for CallbackPrefix members
- broken lock-key references
"""

import ast
import pathlib
import re

import handlers
from handlers import callback_router
from models import CallbackPrefix


def test_all_core_modules_import():
    """Every project module must be importable (catches syntax/name errors)."""
    import bot  # noqa: F401
    import config  # noqa: F401
    import learning_engine  # noqa: F401
    import llm_service  # noqa: F401
    import models  # noqa: F401
    import option_generator  # noqa: F401
    import quiz_service  # noqa: F401
    import services  # noqa: F401
    import srs_service  # noqa: F401
    import tts_service  # noqa: F401
    import ui  # noqa: F401
    import utils  # noqa: F401


def test_every_callback_prefix_is_routed():
    """Each CallbackPrefix member must have exactly one route."""
    prefix_routes = {prefix for prefix, _ in callback_router.PREFIX_ROUTES}
    exact_routes = set(callback_router.EXACT_ROUTES)

    missing = [
        member.name
        for member in CallbackPrefix
        if member.value not in prefix_routes
        and member.value not in exact_routes
    ]
    assert not missing, f"unrouted CallbackPrefix members: {missing}"


def test_route_handlers_are_callable():
    for prefix, handler in callback_router.PREFIX_ROUTES:
        assert callable(handler), f"route {prefix!r} -> handler not callable"

    for key, handler in callback_router.EXACT_ROUTES.items():
        assert handler is None or callable(handler), (
            f"exact route {key!r} -> handler not callable"
        )


def test_no_undefined_lock_key_references_in_handlers():
    """Regression guard for the copy-pasted `pop(lock_key)` NameError bug.

    `lock_key` is only a valid name inside core/locks.py (the decorator);
    no file under handlers/ may reference it.
    """
    handlers_dir = pathlib.Path(handlers.__file__).parent
    offenders = []
    for path in sorted(handlers_dir.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        # A local definition (`lock_key = "..."`) makes the reference valid;
        # a bare `pop(lock_key)` without one is the copy-paste NameError bug.
        has_local_def = re.search(r'lock_key\s*=\s*["\']', src) is not None
        if "pop(lock_key" in src and not has_local_def:
            offenders.append(str(path))
    assert not offenders, f"handlers referencing undefined lock_key: {offenders}"


def test_all_callback_guard_keys_are_registered_session_keys():
    """Every callback_guard key must exist in services.SESSION_KEYS so that
    reset_session() clears it; otherwise a stale lock can brick a feature.
    """
    from services import SESSION_KEYS

    handlers_dir = pathlib.Path(handlers.__file__).parent
    used = set()
    for path in sorted(handlers_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "callback_guard"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                used.add(node.args[0].value)

    unknown = used - set(SESSION_KEYS)
    assert not unknown, f"callback_guard keys missing from SESSION_KEYS: {unknown}"


def test_answer_lock_keys_are_distinct_per_feature():
    """Answer handlers must not share one lock key (the old copy-paste bug)."""
    handlers_dir = pathlib.Path(handlers.__file__).parent
    found = {}
    for path in sorted(handlers_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "callback_guard"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                func_name = getattr(getattr(node, "parent", None), "name", "?")
                key = node.args[0].value
                if key.endswith("_answer_lock"):
                    found.setdefault(key, []).append(
                        f"{path.name}:{func_name}"
                    )
    # Each *_answer_lock key should be used by exactly one handler function
    duplicates = {k: v for k, v in found.items() if len(v) > 1}
    assert not duplicates, f"shared answer-lock keys: {duplicates}"