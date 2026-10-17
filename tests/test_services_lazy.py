"""Phase R2 guards: the AppContext must be lazy and injectable.

R2 deliverables pinned here (see docs/REFACTOR_ROADMAP.md):

1. Importing ``bot`` / ``handlers`` / ``services`` must NOT construct the
   AppContext (no database opened at import time). Checked in a subprocess
   because the test session itself builds the app via other tests.
2. ``get_app()`` returns the same instance on every call (single
   construction point).
3. The late-binding proxies (``services.db`` etc.) always resolve against
   the *current* AppContext, so ``set_app()`` swaps what every consumer
   sees — including legacy ``from services import db`` call sites.
"""

import subprocess
import sys
import pathlib

import services

PROJECT_ROOT = pathlib.Path(services.__file__).resolve().parent.parent


def test_importing_bot_and_handlers_does_not_build_app():
    code = (
        "import sys; sys.path.insert(0, r'{root}'); "
        "import bot, handlers, services; "
        "print('BUILT' if services.is_app_built() else 'LAZY')"
    ).format(root=PROJECT_ROOT)
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "LAZY" in out.stdout, "AppContext was built during import"


class _FakeNested:
    marker = "nested-ok"


class _FakeDB:
    words = _FakeNested()


class _FakeApp:
    def __init__(self):
        self.db = _FakeDB()
        self.closed = False

    def close(self):
        self.closed = True


def test_get_app_returns_same_instance():
    first = services.get_app()
    second = services.get_app()
    assert first is second
    assert services.is_app_built()


def test_proxies_resolve_against_current_app():
    fake = _FakeApp()
    services.set_app(fake)
    try:
        assert services.db.words.marker == "nested-ok"
        services.app.close()
        assert fake.closed
    finally:
        services.reset_app()
    # After the reset the proxy rebuilds the real context on next access.
    assert services.get_app() is not fake


def test_reset_app_clears_cache():
    built = services.get_app()
    services.reset_app()
    try:
        assert not services.is_app_built()
    finally:
        services.set_app(built)
    assert services.is_app_built()
