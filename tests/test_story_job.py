"""Tests for the background story-generation job (Phase 1, item 4).

Covers the four requirements from the planning checklist:

1. Payload validation accepts a complete required-fields payload.
2. Payload validation rejects missing ``user_id`` / ``chat_id`` /
   ``lesson_id`` (the test for ``progress_message_id`` is folded in
   to the same per-field "must be int" check).
3. ``_story_job_name`` is unique per user (``story_gen:<id>``).
4. ``show_story_menu`` does NOT schedule a job when the daily
   ``story`` quota is exhausted — it answers the callback, renders
   the Persian quota error, and leaves ``job_queue.run_once``
   untouched.

No real LLM is invoked: every quota / story-generation call is
monkey-patched to a controllable fake.
"""

from types import SimpleNamespace

import pytest

import services
from handlers.story import jobs as story_jobs
from handlers.story import core as story_core


# ─── fakes ───────────────────────────────────────────────────────────


class _FakeJobQueue:
    """A controllable stand-in for ``telegram.ext.JobQueue``.

    Records every ``run_once`` call so a test can assert the bot
    scheduled (or did not schedule) a job, and supports the
    ``get_jobs_by_name`` lookup that the dedup check uses.
    """

    def __init__(self, scheduled_jobs=None):
        self.scheduled = list(scheduled_jobs or [])
        self.names = {
            j.get("name"): j
            for j in self.scheduled
            if isinstance(j, dict) and j.get("name")
        }

    def run_once(self, callback, when, data=None, **kw):
        rec = {
            "callback": callback,
            "when": when,
            "data": data,
            "kw": kw,
        }
        self.scheduled.append(rec)
        if "name" in kw:
            self.names[kw["name"]] = rec
        return SimpleNamespace(
            callback=callback,
            data=data,
            name=kw.get("name"),
            job=rec,
        )

    def get_jobs_by_name(self, name):
        return [self.names[name]] if name in self.names else []


class _FakeBot:
    def __init__(self):
        self.sent: list[dict] = []
        self.edited: list[dict] = []

    async def send_message(self, chat_id=None, text=None, **kw):
        rec = {"chat_id": chat_id, "text": text, **kw}
        self.sent.append(rec)
        return SimpleNamespace(message_id=10_000 + len(self.sent))

    async def edit_message_text(
        self, chat_id=None, message_id=None, text=None,
        reply_markup=None, parse_mode=None, **kw,
    ):
        self.edited.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )

    async def answer_callback_query(self, **kw):
        self.last_answer = kw


def _complete_payload(**overrides):
    """A complete, valid payload — pass kwargs to override one field."""
    p = {
        "user_id": 42,
        "chat_id": 999,
        "lesson_id": 7,
        "progress_message_id": 12345,
        "exclude_ids": [],
        "user_data": {},
        "job_name": "story_gen:42",
    }
    p.update(overrides)
    return p


# ─── 1) payload validation accepts the required fields ─────────────


def test_payload_validation_accepts_required_fields():
    """A payload with every required key must validate cleanly.

    The optional keys (``exclude_ids``, ``user_data``, ``job_name``)
    can be present or absent — the validator must default them.
    """
    err_full = story_jobs._validate_payload(_complete_payload())
    assert err_full is None, err_full

    # Also accept a minimal payload that omits every optional key.
    minimal = {
        "user_id": 1,
        "chat_id": 2,
        "lesson_id": 3,
        "progress_message_id": 4,
    }
    assert story_jobs._validate_payload(minimal) is None


# ─── 2) payload validation rejects missing required fields ─────────


@pytest.mark.parametrize("missing_key", ["user_id", "chat_id", "lesson_id", "progress_message_id"])
def test_payload_validation_rejects_missing_required_field(missing_key):
    payload = _complete_payload()
    payload.pop(missing_key)
    err = story_jobs._validate_payload(payload)
    assert err is not None
    assert missing_key in err


def test_payload_validation_rejects_non_int_required_field():
    """A string in place of an int must be rejected with a clear error."""
    payload = _complete_payload(user_id="not-an-int")
    err = story_jobs._validate_payload(payload)
    assert err is not None
    assert "user_id" in err
    assert "int" in err


def test_payload_validation_rejects_non_dict_payload():
    """A non-dict ``data`` (e.g. ``None``) must be rejected up-front."""
    assert story_jobs._validate_payload(None) is not None
    assert story_jobs._validate_payload("payload") is not None
    assert story_jobs._validate_payload(42) is not None


# ─── 3) job name is unique per user ──────────────────────────────


def test_job_name_is_unique_per_user():
    a = story_jobs._story_job_name(1)
    b = story_jobs._story_job_name(2)
    assert a == "story_gen:1"
    assert b == "story_gen:2"
    assert a != b

    # Different user ids must produce different job names; identical
    # user ids must produce identical job names (idempotent).
    assert story_jobs._story_job_name(7) == story_jobs._story_job_name(7)
    assert story_jobs._story_job_name(7) != story_jobs._story_job_name(8)


def test_job_name_coerces_non_int_user_id():
    """`_story_job_name` accepts any int-like user id and normalises it."""
    # Floats and strings coerce to a clean int via int(...).
    assert story_jobs._story_job_name("42") == "story_gen:42"
    assert story_jobs._story_job_name(42.7) == "story_gen:42"
    # And the int() round-trip is idempotent.
    assert story_jobs._story_job_name(int("999")) == "story_gen:999"


# ─── 4) show_story_menu does not schedule when quota is exhausted ──


class _FakeQuery:
    """Minimal stand-in for a ``CallbackQuery``."""

    def __init__(self, user_id, chat_id=555):
        self.from_user = SimpleNamespace(id=user_id)
        self.edits: list[dict] = []
        self.replies: list[dict] = []
        self.message = SimpleNamespace(
            chat_id=chat_id,
            message_id=1,
            async_reply_text=self.replies,
        )
        self.chat_id = chat_id
        self.answers: list[dict] = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append({"text": text, "show_alert": show_alert, **kw})

    async def edit_message_text(self, text=None, reply_markup=None, **kw):
        self.edits.append({"text": text, "reply_markup": reply_markup, **kw})

    async def reply_text(self, text=None, reply_markup=None, **kw):
        self.replies.append({"text": text, "reply_markup": reply_markup, **kw})


class _FakeContext:
    def __init__(self, user_id):
        # user_id is passed for parity with the real ``ContextTypes``,
        # but the production code reads it from the query, not the context.
        self.user_data: dict = {}
        self.bot = _FakeBot()
        self.job_queue = _FakeJobQueue()


async def _patch_quota(monkeypatch, allowed: bool):
    """Make ``is_llm_action_allowed`` return ``allowed`` and record calls."""
    calls: list[tuple] = []

    def _fake_is_allowed(user_id, feature):
        calls.append((user_id, feature))
        return allowed

    increments: list[tuple] = []

    def _fake_increment(user_id, feature):
        increments.append((user_id, feature))
        return None

    # Patch the symbols the module under test uses.
    monkeypatch.setattr(
        "services.db.learning.is_llm_action_allowed", _fake_is_allowed
    )
    monkeypatch.setattr(
        "services.db.learning.increment_llm_usage", _fake_increment
    )
    # Also make ``llm.is_available`` return True so the quota gate is
    # the *only* reason to short-circuit.
    monkeypatch.setattr(services.llm, "is_available", lambda: True)

    return calls, increments


async def test_show_story_menu_does_not_schedule_when_quota_exceeded(monkeypatch):
    """Phase 1, item 4.5: ``show_story_menu`` must short-circuit
    *before* incrementing the quota and *before* scheduling the
    job when the daily ``story`` quota is exhausted.
    """
    _quota_calls, increments = await _patch_quota(monkeypatch, allowed=False)

    ctx = _FakeContext(user_id=42)
    query = _FakeQuery(user_id=42, chat_id=555)

    await story_core.show_story_menu(query, ctx, lesson_id=7)

    # 1) The quota gate was consulted.
    assert _quota_calls and _quota_calls[0] == (42, "story")

    # 2) The quota was NOT incremented (we returned before that line).
    assert increments == [], (
        "quota must not be incremented when is_llm_action_allowed returns False"
    )

    # 3) The job was NOT scheduled.
    assert ctx.job_queue.scheduled == [], (
        f"no run_once call expected, got {ctx.job_queue.scheduled}"
    )

    # 4) The bot rendered the quota error to the user (either as a
    #    message edit, a reply, or a callback answer, depending on
    #    the code path).  We do not require a specific channel here;
    #    we just need the user to see *something* so they are not
    #    left waiting on a non-existent background job.
    surfaced = bool(query.answers) or bool(query.edits) or bool(query.replies)
    assert surfaced, (
        f"expected the quota error to be surfaced; "
        f"answers={query.answers!r} edits={query.edits!r} replies={query.replies!r}"
    )

    # 5) The busy marker was NOT set (the user can retry after quota
    #    resets without having to clear a stuck flag).
    assert "story_generating" not in ctx.user_data
    assert "story_active_job_name" not in ctx.user_data


async def test_show_story_menu_schedules_job_when_quota_allows(monkeypatch):
    """Positive control: when the quota allows, ``show_story_menu``
    must schedule a job (not the pre-change synchronous generation)
    and pass a payload that the job's ``_validate_payload`` accepts.
    """
    _quota_calls, _increments = await _patch_quota(monkeypatch, allowed=True)

    ctx = _FakeContext(user_id=42)
    query = _FakeQuery(user_id=42, chat_id=555)

    await story_core.show_story_menu(query, ctx, lesson_id=7)

    # 1) The quota gate was consulted *and* the slot reserved.
    assert _quota_calls and _quota_calls[0] == (42, "story")
    assert _increments == [(42, "story")]

    # 2) Exactly one job was scheduled.
    assert len(ctx.job_queue.scheduled) == 1
    job = ctx.job_queue.scheduled[0]

    # 3) The job name embeds the user id and is the unique per-user one.
    assert job["kw"]["name"] == "story_gen:42"
    assert job["when"] == pytest.approx(0.1)
    assert job["callback"] is story_jobs.generate_story_job

    # 4) The payload validates cleanly (would crash inside the worker
    #    otherwise; we catch it here so the test does not have to).
    err = story_jobs._validate_payload(job["data"])
    assert err is None, err

    # 5) Busy markers were set so /cancel can find the job.
    assert ctx.user_data.get("story_generating") is True
    assert ctx.user_data.get("story_active_job_name") == "story_gen:42"
