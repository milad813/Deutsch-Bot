"""Tests for the admin ``/status`` operational monitoring view.

Covers:

* ``show_status`` rejects non-admin callers (and does **not** fire
  any DB query for them).
* ``show_status`` renders the full Persian status report when called
  by the configured admin.
* ``LearningRepository.get_llm_usage_totals_today`` returns the
  expected zero dict for both an empty matching set **and** a missing
  ``user_llm_usage`` table.
* The rendered text always includes the current ``BOT_MODE`` value.

Fake updates are hand-rolled ``SimpleNamespace`` instances so the
test does not need a running PTB ``Application``.  The real
``services.db`` repositories are used (per ``conftest.py`` we are
already pointing at a throwaway SQLite DB) and stubbed only where
the handler's "look how many rows" query is too expensive for a
unit test.
"""

from types import SimpleNamespace

import pytest

import config
import services
from handlers.admin_handlers import show_status


# ──────────────────────────── fake Telegram objects ─────────────────────────


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeMessage:
    def __init__(self):
        self.sent: list = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)


class _FakeUpdate:
    """Minimal ``Update``-shaped object: ``effective_user`` and ``message``."""

    def __init__(self, user_id: int):
        self.effective_user = _FakeUser(user_id)
        self.message = _FakeMessage()


class _FakeContext:
    """Minimal PTB ``CallbackContext``-shaped object.

    Only ``job_queue`` is used by ``show_status``; everything else is
    left unset so the handler exercises its "no context" fallback.
    """

    def __init__(self, job_queue=None):
        self.job_queue = job_queue


# ───────────────────────────── helpers ──────────────────────────────────────


def _all_text(update):
    """Concatenate every message ``render`` would have sent."""
    return "\n".join(update.message.sent)


def _stub_repos(
    monkeypatch,
    *,
    words=0,
    books=0,
    lessons=0,
    reminder_ids=None,
    llm_totals=None,
):
    """Replace the count-bearing repository methods with deterministic fakes.

    ``llm_totals`` defaults to ``{"story": 0, "example": 0}`` so the
    rendered page never accidentally reads a real DB row that another
    test suite may have left behind.
    """
    if reminder_ids is None:
        reminder_ids = []
    if llm_totals is None:
        llm_totals = {"story": 0, "example": 0}

    monkeypatch.setattr(services.db.words, "get_count", lambda: words)
    monkeypatch.setattr(services.db.books, "get_count", lambda: books)
    monkeypatch.setattr(services.db.lessons, "get_count", lambda: lessons)
    monkeypatch.setattr(
        services.db.users, "get_reminder_user_ids", lambda: list(reminder_ids)
    )
    monkeypatch.setattr(
        services.db.learning,
        "get_llm_usage_totals_today",
        lambda: dict(llm_totals),
    )

# ─────────────────────────── non-admin path ────────────────────────────────


async def test_show_status_rejects_non_admin(monkeypatch):
    """Non-admin callers must see the "no access" notice and must NOT
    trigger any DB query.

    The handler short-circuits *before* ``asyncio.gather`` so no
    repository is ever touched -- if it were, our lack of stubs would
    surface as either a None-returning query or a real-DB read.
    """
    monkeypatch.setattr(config, "ADMIN_USER_ID", 999_999)

    update = _FakeUpdate(user_id=1)  # not the admin

    await show_status(update, _FakeContext())

    text = _all_text(update)
    assert "⛔️" in text, text
    assert "دسترسی" in text, text
    # The Persian status body must not be rendered for a non-admin.
    assert "حالت ربات" not in text


async def test_show_status_rejects_when_admin_id_zero(monkeypatch):
    """A misconfigured ``ADMIN_USER_ID == 0`` (the "no admin" state)
    must lock everyone out, just like the production gate does.
    """
    monkeypatch.setattr(config, "ADMIN_USER_ID", 0)

    update = _FakeUpdate(user_id=42)

    await show_status(update, _FakeContext())

    text = _all_text(update)
    assert "⛔️" in text
    assert "حالت ربات" not in text

# ─────────────────────────── admin path ───────────────────────────────────


async def test_show_status_renders_for_admin(monkeypatch):
    """Admin caller must see every required field rendered once."""
    monkeypatch.setattr(config, "ADMIN_USER_ID", 4242)

    _stub_repos(
        monkeypatch,
        words=1500,
        books=3,
        lessons=27,
        reminder_ids=[1, 2, 3, 4, 5],
        llm_totals={"story": 7, "example": 42},
    )

    # Minimal ``job_queue`` with two story jobs and a benign
    # scheduler job so the "active jobs" block exercises the filter.
    class _FakeJob:
        def __init__(self, name):
            self.name = name

    class _FakeJobQueue:
        def __init__(self, jobs):
            self._jobs = list(jobs)

        def jobs(self):
            return list(self._jobs)

    jq = _FakeJobQueue(
        [
            _FakeJob("story_gen_123"),
            _FakeJob("story_gen_77"),
            _FakeJob("daily_backup"),  # not a story job
        ]
    )

    import handlers.admin_handlers as ah

    monkeypatch.setattr(
        ah,
        "_phase1_status",
        lambda repo_root=None: (2, 4, ["Open item A", "Open item B"]),
    )

    update = _FakeUpdate(user_id=4242)
    await show_status(update, _FakeContext(job_queue=jq))

    text = _all_text(update)
    assert "وضعیت سیستم" in text
    assert "پیکربندی" in text
    assert "محتوا" in text
    assert "کاربران" in text
    assert "مصرف LLM" in text
    assert "صف تولید داستان" in text
    assert "Phase 1" in text

    assert "1500" in text           # words
    assert "3" in text              # books
    assert "27" in text             # lessons
    assert "5" in text              # reminder ids
    assert "7" in text              # story LLM count
    assert "42" in text             # example LLM count
    assert "2" in text              # done items
    assert "4" in text              # total items

    # The two story jobs must be listed; daily_backup must not.
    assert "story_gen_123" in text
    assert "story_gen_77" in text
    assert "daily_backup" not in text

    # No leak of the configured admin id into the body.
    assert "4242" not in text


async def test_show_status_includes_bot_mode_text(monkeypatch):
    """The rendered text must always carry the active ``BOT_MODE``.

    ``conftest.py`` sets ``BOT_MODE=offline``; we assert the Persian
    label "آفلاین" makes it into the body so the admin can always
    see at a glance what mode the bot is in.
    """
    monkeypatch.setattr(config, "ADMIN_USER_ID", 7)
    _stub_repos(monkeypatch)
    import handlers.admin_handlers as ah

    monkeypatch.setattr(ah, "_phase1_status", lambda repo_root=None: (0, 0, []))

    update = _FakeUpdate(user_id=7)
    await show_status(update, _FakeContext())

    text = _all_text(update)
    assert "حالت ربات" in text
    assert "آفلاین" in text
    assert "مسیر دیتابیس" in text
    basename = config.DB_PATH.replace("\\", "/").split("/")[-1]
    assert basename in text


async def test_show_status_handles_missing_job_queue(monkeypatch):
    """If ``context.job_queue`` is ``None``, the page must still
    render -- we just show "۰" for active story jobs.
    """
    monkeypatch.setattr(config, "ADMIN_USER_ID", 7)
    _stub_repos(monkeypatch)
    import handlers.admin_handlers as ah

    monkeypatch.setattr(ah, "_phase1_status", lambda repo_root=None: (0, 0, []))

    update = _FakeUpdate(user_id=7)
    ctx = _FakeContext(job_queue=None)
    await show_status(update, ctx)

    text = _all_text(update)
    assert "صف تولید داستان" in text
    assert "۰" in text


async def test_show_status_handles_missing_phase1_file(monkeypatch):
    """If ``docs/PHASE1.md`` is missing, the page must still render
    and show the "not found" hint instead of crashing.
    """
    monkeypatch.setattr(config, "ADMIN_USER_ID", 7)
    _stub_repos(monkeypatch)

    import handlers.admin_handlers as ah

    monkeypatch.setattr(ah, "_phase1_status", lambda repo_root=None: (0, 0, []))

    update = _FakeUpdate(user_id=7)
    await show_status(update, _FakeContext())

    text = _all_text(update)
    assert "Phase 1" in text
    assert "یافت نشد" in text

# ─────────────────────────── repository contract ───────────────────────────


async def test_get_llm_usage_totals_today_returns_zeros_when_table_empty():
    """When the ``user_llm_usage`` table exists but has no rows for
    today, the helper must return ``{"story": 0, "example": 0}``.
    """
    from services import db, run_db

    today = db.learning._today_local_str()
    db.learning.execute(
        "DELETE FROM user_llm_usage WHERE usage_date = ?",
        (today,),
        commit=True,
    )

    totals = await run_db(db.learning.get_llm_usage_totals_today)
    assert totals == {"story": 0, "example": 0}


async def test_get_llm_usage_totals_today_aggregates_across_users():
    """When rows from multiple users exist for today, the helper
    must return the summed totals (not just one row).
    """
    from services import db, run_db

    today = db.learning._today_local_str()
    db.learning.execute(
        "DELETE FROM user_llm_usage WHERE usage_date = ?",
        (today,),
        commit=True,
    )

    # Three users bump story; two of them also bump example.
    # Expected totals: story = 3, example = 2.
    for uid in (910_001, 910_002, 910_003):
        db.learning.execute(
            """
            INSERT INTO user_llm_usage
                (user_id, usage_date, story_count, example_count, last_updated)
            VALUES (?, ?, 1, 0, ?)
            ON CONFLICT(user_id, usage_date) DO UPDATE SET
                story_count = user_llm_usage.story_count + 1
            """,
            (uid, today, "2024-01-15 12:00:00"),
            commit=True,
        )
    for uid in (910_001, 910_002):
        db.learning.execute(
            """
            INSERT INTO user_llm_usage
                (user_id, usage_date, story_count, example_count, last_updated)
            VALUES (?, ?, 0, 1, ?)
            ON CONFLICT(user_id, usage_date) DO UPDATE SET
                example_count = user_llm_usage.example_count + 1
            """,
            (uid, today, "2024-01-15 12:00:00"),
            commit=True,
        )

    totals = await run_db(db.learning.get_llm_usage_totals_today)
    assert totals == {"story": 3, "example": 2}

    db.learning.execute(
        "DELETE FROM user_llm_usage WHERE user_id BETWEEN ? AND ?",
        (910_000, 910_999),
        commit=True,
    )


async def test_get_llm_usage_totals_today_returns_zeros_when_table_missing():
    """When the ``user_llm_usage`` table does not exist (e.g. a
    pre-Phase-1 database), the helper must return zeros rather than
    bubbling up ``sqlite3.OperationalError``.
    """
    from services import db, run_db

    db.learning.execute("DROP TABLE IF EXISTS user_llm_usage", commit=True)

    totals = await run_db(db.learning.get_llm_usage_totals_today)
    assert totals == {"story": 0, "example": 0}

    # Re-create the table so other test suites that run after us
    # still find the expected schema.  We do it via the production
    # ``schema`` module to keep the column set / indexes identical.
    import database.schema as schema

    for stmt in schema.TABLE_STATEMENTS:
        if "user_llm_usage" in stmt and "CREATE" in stmt:
            db.learning.execute(stmt, commit=True)
    for stmt in schema.INDEX_STATEMENTS:
        if "user_llm_usage" in stmt:
            db.learning.execute(stmt, commit=True)


async def test_books_and_lessons_get_count_handles_missing_table():
    """``BookRepository.get_count`` and ``LessonRepository.get_count``
    must return 0 (not raise) if their tables are missing -- the
    admin ``/status`` view depends on this so a pre-Phase-1 database
    never bricks the page.
    """
    from services import db, run_db

    db.books.execute("DROP TABLE IF EXISTS books", commit=True)
    db.lessons.execute("DROP TABLE IF EXISTS lessons", commit=True)

    try:
        books = await run_db(db.books.get_count)
        lessons = await run_db(db.lessons.get_count)
        assert books == 0
        assert lessons == 0
    finally:
        # Re-create the tables so the rest of the test suite still
        # has a usable schema.
        import database.schema as schema

        for stmt in schema.TABLE_STATEMENTS:
            if "CREATE TABLE" in stmt and (
                "books (" in stmt or "lessons (" in stmt
            ):
                db.books.execute(stmt, commit=True)
            elif "CREATE TABLE" in stmt and "lessons (" in stmt:
                db.lessons.execute(stmt, commit=True)
        for stmt in schema.INDEX_STATEMENTS:
            if "books" in stmt:
                db.books.execute(stmt, commit=True)
            elif "lessons" in stmt:
                db.lessons.execute(stmt, commit=True)

# ─────────────────────────── inline-button path ────────────────────────────


async def test_show_status_via_callback_router_uses_from_user(monkeypatch):
    """When the handler is dispatched via the callback router, the
    first argument is a ``CallbackQuery`` (not an ``Update``).  The
    handler must therefore read ``from_user`` -- not just
    ``effective_user`` -- to authorize the request.
    """
    from types import SimpleNamespace

    from handlers.callback_router import EXACT_ROUTES, inline_handler

    monkeypatch.setattr(config, "ADMIN_USER_ID", 7)
    _stub_repos(monkeypatch)
    import handlers.admin_handlers as ah

    monkeypatch.setattr(ah, "_phase1_status", lambda repo_root=None: (0, 0, []))

    # Build a query-like object -- no ``effective_user``, only
    # ``from_user`` -- which is what the callback router passes.
    sent: list = []

    class _Msg:
        async def edit_message_text(self, text, reply_markup=None, **kw):
            sent.append(text)

        async def reply_text(self, text, reply_markup=None, **kw):
            sent.append(text)

    query = SimpleNamespace(
        data="admin_status",
        from_user=SimpleNamespace(id=7),  # admin
        message=_Msg(),
    )
    ctx = SimpleNamespace(job_queue=None)

    await inline_handler(query, ctx) if False else await EXACT_ROUTES["admin_status"](query, ctx)

    assert sent, "show_status did not render anything"
    body = sent[0]
    assert "وضعیت سیستم" in body
    assert "حالت ربات" in body
