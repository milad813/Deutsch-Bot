"""Phase R1 regression guards for lint-caught bug fixes.

The Phase R1 ruff/mypy baseline surfaced three latent bugs (see
docs/REFACTOR_ROADMAP.md). These tests pin the fix shapes so a future
refactor cannot silently reintroduce them:

1. ``handlers/callback_router._handle_quiz_book`` calls
   ``menus.show_lessons_for_quiz`` -- the function went missing once and
   every book tap in the quiz-by-lesson flow raised AttributeError.
2. ``handlers.story.view._build_story_view`` accepts ``story_id`` --
   the story action buttons (listen/read, quiz, words, hint) referenced
   an undefined ``story_id`` and raised NameError on every press.

Source-inspection style, like ``test_phase1_checks.py``: no DB, no
network, no Telegram objects.
"""

import ast
import inspect
import pathlib

import handlers.menus
from handlers.story import view as story_view


def test_menus_provides_show_lessons_for_quiz():
    """The callback router calls menus.show_lessons_for_quiz; it must exist."""
    assert callable(handlers.menus.show_lessons_for_quiz)


def test_build_story_view_signature_accepts_story_id():
    """Story action buttons embed story_id; the builder needs the value."""
    params = inspect.signature(story_view._build_story_view).parameters
    assert "story_id" in params


def test_story_view_has_no_unresolved_story_id_names():
    """F821 guard: no free ``story_id`` Name loads outside function args.

    Guards the original failure mode: five ``cb_safe(..., story_id)``
    references inside a function that never bound ``story_id``.
    """
    source = pathlib.Path(story_view.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {a.arg for a in func.args.args}
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Name)
                and node.id == "story_id"
                and isinstance(node.ctx, ast.Load)
                and node.id not in bound
            ):
                offenders.append(f"{func.name}:{node.lineno}")

    assert not offenders, "unbound story_id references:\n" + "\n".join(offenders)
