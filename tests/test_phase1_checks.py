"""Phase 1 structural / regression checks.

These tests guard the *shape* of the Phase 1 architecture rather than
runtime behaviour.  They run purely against the project tree (no DB, no
network) and exist so that a refactor which accidentally deletes a
publicly-expected helper (e.g. ``cb_safe``) fails the build instead of
silently breaking callers.

All checks are read-only ``pathlib`` / ``importlib`` calls.  No mocks,
no fixtures with side effects.

Run::

    python -m pytest -q
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import unittest
from pathlib import Path


# Resolve the project root: this file lives at
# <root>/tests/test_phase1_checks.py, so the root is one level up.
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent


def _import_from_path(path: Path, module_name: str):
    """Import a module from an explicit file path.

    Uses ``importlib.util.spec_from_file_location`` so we don't have to
    mutate ``sys.path`` or rely on the module being on PYTHONPATH at the
    moment the test runs.  Returns ``None`` if the file does not exist
    or is not importable for any reason.
    """

    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - we want None on import errors
        return None
    return module



# ──────────────────────────────────────────────────────────────────────────
# 1. core/callbacks.cb_safe
# ──────────────────────────────────────────────────────────────────────────


class TestCoreCallbacksShape(unittest.TestCase):
    """``core/callbacks.cb_safe`` is the canonical safe-callback builder."""

    CALLBACKS_FILE = PROJECT_ROOT / "core" / "callbacks.py"

    def test_callbacks_module_file_exists(self):
        self.assertTrue(
            self.CALLBACKS_FILE.exists(),
            f"expected {self.CALLBACKS_FILE} to exist (Phase 1 base module)",
        )

    def test_cb_safe_is_importable(self):
        module = _import_from_path(self.CALLBACKS_FILE, "_phase1_callbacks")
        self.assertIsNotNone(module, "core/callbacks.py must be importable")
        self.assertTrue(
            hasattr(module, "cb_safe"),
            "core/callbacks must expose ``cb_safe``",
        )
        self.assertTrue(
            callable(getattr(module, "cb_safe")),
            "core/callbacks.cb_safe must be callable",
        )


# ──────────────────────────────────────────────────────────────────────────
# 2. ui.split_html_text
# ──────────────────────────────────────────────────────────────────────────


class TestUISplitHtmlTextShape(unittest.TestCase):
    """``ui.split_html_text`` is used by every long-text handler."""

    UI_FILE = PROJECT_ROOT / "ui.py"

    def test_ui_module_file_exists(self):
        self.assertTrue(
            self.UI_FILE.exists(),
            f"expected {self.UI_FILE} to exist",
        )

    def test_split_html_text_is_importable(self):
        module = _import_from_path(self.UI_FILE, "_phase1_ui")
        self.assertIsNotNone(module, "ui.py must be importable")
        self.assertTrue(
            hasattr(module, "split_html_text"),
            "ui must expose ``split_html_text``",
        )
        self.assertTrue(
            callable(getattr(module, "split_html_text")),
            "ui.split_html_text must be callable",
        )


# ──────────────────────────────────────────────────────────────────────────
# 3. core/logging_utils.log_event
# ──────────────────────────────────────────────────────────────────────────


class TestLoggingUtilsShape(unittest.TestCase):
    """``core/logging_utils.log_event`` is the structured logger."""

    LOGGING_FILE = PROJECT_ROOT / "core" / "logging_utils.py"

    def test_logging_utils_file_exists(self):
        self.assertTrue(
            self.LOGGING_FILE.exists(),
            f"expected {self.LOGGING_FILE} to exist (Phase 1 logging module)",
        )

    def test_log_event_is_importable(self):
        module = _import_from_path(self.LOGGING_FILE, "_phase1_logging")
        self.assertIsNotNone(module, "core/logging_utils.py must be importable")
        self.assertTrue(
            hasattr(module, "log_event"),
            "core/logging_utils must expose ``log_event``",
        )
        self.assertTrue(
            callable(getattr(module, "log_event")),
            "core/logging_utils.log_event must be callable",
        )


# ──────────────────────────────────────────────────────────────────────────
# 4. handlers/story/jobs.py + generate_story_job
# ──────────────────────────────────────────────────────────────────────────


class TestStoryJobsShape(unittest.TestCase):
    """Story generation lives in ``handlers/story/jobs.py``."""

    JOBS_FILE = PROJECT_ROOT / "handlers" / "story" / "jobs.py"

    def test_jobs_module_file_exists(self):
        # The user spec is "exists or generate_story_job exists"; we
        # therefore accept either the module file *or* a top-level
        # ``generate_story_job`` symbol defined anywhere in the project.
        if self.JOBS_FILE.exists():
            return  # happy path: the dedicated module is there

        # Fallback: search for ``generate_story_job`` in any handlers/*.py
        found_symbol = False
        handlers_dir = PROJECT_ROOT / "handlers"
        if handlers_dir.exists():
            for py in handlers_dir.rglob("*.py"):
                try:
                    text = py.read_text(encoding="utf-8")
                except OSError:
                    continue
                if re.search(
                    r"^\s*(async\s+def|def)\s+generate_story_job\s*\(",
                    text,
                    re.MULTILINE,
                ):
                    found_symbol = True
                    break
        self.assertTrue(
            found_symbol,
            "either handlers/story/jobs.py must exist, or a "
            "``generate_story_job`` callable must be defined in some "
            "module under handlers/",
        )

    def test_generate_story_job_is_callable(self):
        if not self.JOBS_FILE.exists():
            self.skipTest(
                "handlers/story/jobs.py not present; the alternative-path "
                "test above already enforces the contract."
            )
        module = _import_from_path(self.JOBS_FILE, "_phase1_story_jobs")
        self.assertIsNotNone(module, "handlers/story/jobs.py must be importable")
        self.assertTrue(
            hasattr(module, "generate_story_job"),
            "handlers/story/jobs must expose ``generate_story_job``",
        )
        self.assertTrue(
            callable(getattr(module, "generate_story_job")),
            "handlers/story/jobs.generate_story_job must be callable",
        )


# ──────────────────────────────────────────────────────────────────────────
# 5. bot.daily_reminder must not call get_all_users directly
#    if the reminder opt-in mechanism exists.
# ──────────────────────────────────────────────────────────────────────────


class TestDailyReminderRespectsOptIn(unittest.TestCase):
    """The daily reminder must use the opt-in recipient list, not ``get_all_users``.

    Phase 0 introduced an opt-in flag (``user_settings.reminders_enabled``)
    and a repository helper (``get_reminder_user_ids``).  Phase 1's
    hardening made the daily reminder job batched and flood-aware; this
    test pins the *architectural* rule that the job must consume the
    opt-in list, not a raw ``get_all_users`` scan.
    """

    BOT_FILE = PROJECT_ROOT / "bot.py"
    REPO_FILE = PROJECT_ROOT / "database" / "repositories" / "__init__.py"

    def _extract_function_source(self, source: str, func_name: str) -> str:
        """Return the source of the first top-level ``def func_name`` in ``source``.

        Robust to multi-line signatures: walks the file looking for
        ``def func_name(`` at column 0 and returns everything from that
        line to the next column-0 ``def`` / ``async def`` / ``class`` /
        ``if __name__`` sentinel.  Returns an empty string if the
        function is not present at all.
        """

        lines = source.splitlines()
        start = None
        for i, line in enumerate(lines):
            if re.match(rf"^(async\s+def|def)\s+{re.escape(func_name)}\s*\(", line):
                start = i
                break
        if start is None:
            return ""
        for j in range(start + 1, len(lines)):
            stripped = lines[j].lstrip()
            if re.match(r"^(async\s+def|def|class|if\s+__name__)", stripped):
                return "\n".join(lines[start:j])
        return "\n".join(lines[start:])

    def test_opt_in_helper_exists(self):
        """The opt-in helper must exist in the user repository.

        We don't actually import the database here (that would require
        a writable ``words.db``) -- we just verify the source file
        contains a top-level ``def get_reminder_user_ids`` definition.
        """

        self.assertTrue(
            self.REPO_FILE.exists(),
            f"expected {self.REPO_FILE} to exist",
        )
        text = self.REPO_FILE.read_text(encoding="utf-8")
        # ``assertRegex`` uses ``re.search`` without MULTILINE, so
        # we drop the leading ``^`` anchor and rely on the
        # function name itself to disambiguate.  Leading
        # indentation is fine -- the function lives inside
        # ``class UserRepository``.
        self.assertRegex(
            text,
            r"def\s+get_reminder_user_ids\s*\(",
            "UserRepository.get_reminder_user_ids must be defined",
        )

    def test_daily_reminder_does_not_call_get_all_users(self):
        """If the opt-in helper exists, ``daily_reminder`` must consume it.

        We look for direct textual references to ``get_all_users`` inside
        the body of ``daily_reminder``.  The user spec phrasing is:
        "does not call get_all_users directly if reminder opt-in
        exists", which we interpret as: once the opt-in helper is
        defined, the job must not also use the unfiltered
        ``get_all_users`` scan.
        """

        self.assertTrue(
            self.BOT_FILE.exists(),
            f"expected {self.BOT_FILE} to exist",
        )
        source = self.BOT_FILE.read_text(encoding="utf-8")
        body = self._extract_function_source(source, "daily_reminder")
        self.assertTrue(
            body,
            "bot.py must define a top-level ``daily_reminder`` function",
        )
        # Strip comments and string literals so a docstring reference
        # to ``get_all_users`` doesn't trip us up; the policy is about
        # actual call sites, not prose.
        code_only = re.sub(
            r"(\".*?\"|\'.*?\')",
            "",
            body,
            flags=re.DOTALL,
        )
        code_only = re.sub(r"#[^\n]*", "", code_only)
        self.assertNotIn(
            "get_all_users",
            code_only,
            "daily_reminder must not call db.users.get_all_users "
            "directly once the opt-in helper exists; use "
            "db.users.get_reminder_user_ids instead.",
        )

    def test_daily_reminder_uses_opt_in_helper(self):
        """Positive counterpart: the job must use ``get_reminder_user_ids``."""

        source = self.BOT_FILE.read_text(encoding="utf-8")
        body = self._extract_function_source(source, "daily_reminder")
        self.assertTrue(body, "daily_reminder must be defined in bot.py")
        self.assertIn(
            "get_reminder_user_ids",
            body,
            "daily_reminder must source its recipient list from "
            "db.users.get_reminder_user_ids (the opt-in helper).",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
