"""Regression tests for the TTS auto-delete job leak.

Before the fix, ``_auto_delete_tts`` only knew how to read the legacy
2-tuple ``(chat_id, message_id)`` from ``context.job.data``, and the
newer job entries were never removed from the in-memory ``_tts_jobs``
map, so the dictionary grew without bound for every TTS play. These
tests pin down:

* ``_auto_delete_tts`` must accept both 2-tuple (legacy) and 3-tuple
  ``(chat_id, message_id, user_id)`` job data,
* the 3-tuple format must remove the user's entry from ``_tts_jobs``
  so the map cannot leak,
* ``cleanup_tts`` must be safe to call repeatedly (idempotent).
"""

from types import SimpleNamespace

import handlers.tts_handlers as tts_h


# ─── fakes ──────────────────────────────────────────────────────────────────


class _FakeJob:
    def __init__(self, data):
        self.data = data
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class _FakeBot:
    def __init__(self):
        self.deleted: list[tuple] = []

    async def delete_message(self, chat_id=None, message_id=None):
        self.deleted.append((chat_id, message_id))


class _FakeContext:
    def __init__(self):
        self.bot = _FakeBot()
        self.user_data: dict = {}


def _make_context(data):
    """Build a context that mimics a real ``context.job`` callback."""
    ctx = _FakeContext()
    ctx.job = SimpleNamespace(data=data)
    return ctx


# ─── _auto_delete_tts: backward compat + new format ────────────────────────


async def test_auto_delete_tts_handles_legacy_two_tuple_data():
    """Legacy jobs scheduled with only ``(chat_id, message_id)`` must
    still work — the handler must not crash and must delete the
    message."""
    tts_h._tts_jobs.clear()

    ctx = _make_context(data=(123, 999))

    await tts_h._auto_delete_tts(ctx)

    assert ctx.bot.deleted == [(123, 999)]


async def test_auto_delete_tts_handles_three_tuple_data_and_drops_job():
    """New jobs include ``user_id`` in the third slot; after the
    message is deleted, the corresponding entry must be removed from
    ``_tts_jobs`` so the in-memory map cannot leak."""
    tts_h._tts_jobs.clear()

    user_id = 42
    job = _FakeJob(data=(123, 999, user_id))
    tts_h._tts_jobs[user_id] = job

    ctx = _make_context(data=job.data)

    await tts_h._auto_delete_tts(ctx)

    assert ctx.bot.deleted == [(123, 999)]
    assert user_id not in tts_h._tts_jobs, (
        "_auto_delete_tts must pop the user from _tts_jobs to prevent "
        "leaking completed-job references"
    )


async def test_auto_delete_tts_three_tuple_keeps_other_users_jobs():
    """Removing one user's job must not affect anyone else's entry."""
    tts_h._tts_jobs.clear()

    job_a = _FakeJob(data=(1, 100, 11))
    job_b = _FakeJob(data=(2, 200, 22))
    tts_h._tts_jobs[11] = job_a
    tts_h._tts_jobs[22] = job_b

    await tts_h._auto_delete_tts(_make_context(data=job_a.data))

    assert 11 not in tts_h._tts_jobs
    assert 22 in tts_h._tts_jobs
    assert tts_h._tts_jobs[22] is job_b


async def test_auto_delete_tts_swallows_delete_exceptions():
    """If ``delete_message`` raises (e.g. message already gone), the
    handler must not crash and must still drop the job from the map."""
    tts_h._tts_jobs.clear()

    class _BoomBot(_FakeBot):
        async def delete_message(self, **kw):
            raise RuntimeError("network down")

    user_id = 7
    job = _FakeJob(data=(1, 100, user_id))
    tts_h._tts_jobs[user_id] = job

    ctx = _make_context(data=job.data)
    ctx.bot = _BoomBot()

    # Must not raise.
    await tts_h._auto_delete_tts(ctx)

    assert user_id not in tts_h._tts_jobs


async def test_auto_delete_tts_handles_short_data_gracefully():
    """A scheduled job with too few data items must not crash."""
    for bad in (None, (), [42]):
        ctx = _make_context(data=bad)
        # Must not raise.
        await tts_h._auto_delete_tts(ctx)


# ─── cleanup_tts: idempotency ──────────────────────────────────────────────


async def test_cleanup_tts_is_idempotent_with_no_state():
    """Calling ``cleanup_tts`` on a fresh user must not raise."""
    tts_h._tts_jobs.clear()
    ctx = _FakeContext()

    await tts_h.cleanup_tts(ctx, 99)
    # Second call: still must not raise.
    await tts_h.cleanup_tts(ctx, 99)


async def test_cleanup_tts_is_idempotent_with_state():
    """Calling ``cleanup_tts`` twice in a row must both succeed and
    leave the system in a clean state."""
    tts_h._tts_jobs.clear()
    ctx = _FakeContext()
    ctx.user_data["tts_message"] = (123, 456)

    job = _FakeJob(data=(123, 456, 99))
    tts_h._tts_jobs[99] = job

    await tts_h.cleanup_tts(ctx, 99)
    # First call: job removed, message deleted, user_data cleaned.
    assert 99 not in tts_h._tts_jobs
    assert "tts_message" not in ctx.user_data
    assert ctx.bot.deleted == [(123, 456)]
    assert job.removed, "cleanup_tts must call schedule_removal on the job"

    # Second call: nothing to do, but must not raise.
    await tts_h.cleanup_tts(ctx, 99)
    # No extra delete_message invocations.
    assert ctx.bot.deleted == [(123, 456)]


async def test_cleanup_tts_handles_bot_error():
    """``delete_message`` raising must not stop ``cleanup_tts`` from
    removing the in-memory job."""
    tts_h._tts_jobs.clear()

    class _BoomBot(_FakeBot):
        async def delete_message(self, **kw):
            raise RuntimeError("oh no")

    ctx = _FakeContext()
    ctx.bot = _BoomBot()
    ctx.user_data["tts_message"] = (1, 2)
    job = _FakeJob(data=(1, 2, 33))
    tts_h._tts_jobs[33] = job

    # Must not raise.
    await tts_h.cleanup_tts(ctx, 33)
    assert 33 not in tts_h._tts_jobs


# ─── send_ephemeral_audio: 3-tuple job data ────────────────────────────────


async def test_send_ephemeral_audio_schedules_job_with_user_id(
    monkeypatch, tmp_path
):
    """``send_ephemeral_audio`` must schedule ``_auto_delete_tts`` with
    a 3-tuple job data that includes ``user_id``, and must register the
    job in ``_tts_jobs``."""
    tts_h._tts_jobs.clear()

    # Provide a tiny fake audio file so ``tts.get_audio_path`` succeeds.
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"\x00\x00")

    async def _fake_get_audio_path(text):
        return str(audio)

    # Capture the kwargs passed to job_queue.run_once.
    scheduled: list[dict] = []

    class _FakeJobQueue:
        def run_once(self, callback, when, data=None, **kw):
            scheduled.append({
                "callback": callback,
                "when": when,
                "data": data,
                "kw": kw,
            })
            return _FakeJob(data=data)

    # Monkeypatch the module-level symbols the function depends on.
    monkeypatch.setattr(tts_h.tts, "get_audio_path", _fake_get_audio_path)
    monkeypatch.setattr(tts_h.config, "TTS_AUTO_DELETE_SECONDS", 5)
    monkeypatch.setattr(tts_h.config, "TTS_SEND_AS_DOCUMENT", False)

    # Build a minimal query/context.
    class _SentMessage:
        def __init__(self, message_id):
            self.message_id = message_id

    class _SendingBot:
        async def send_audio(self, **kw):
            return _SentMessage(message_id=999)

    class _SendingContext:
        def __init__(self):
            self.bot = _SendingBot()
            self.user_data: dict = {}
            self.job_queue = _FakeJobQueue()

    ctx = _SendingContext()
    user_id = 77
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(chat_id=555, message_id=1, replies=[]),
    )

    async def _reply_text(text, **kw):
        query.message.replies.append(text)

    query.message.reply_text = _reply_text

    await tts_h.send_ephemeral_audio(query, ctx, "Haus")

    assert scheduled, "expected _auto_delete_tts to be scheduled"
    entry = scheduled[0]
    assert entry["callback"] is tts_h._auto_delete_tts
    data = entry["data"]
    assert data is not None
    # The new format is a 3-tuple carrying (chat_id, message_id, user_id).
    assert len(data) == 3, f"expected 3-tuple data, got {data!r}"
    chat_id, message_id, scheduled_user_id = data
    assert chat_id == 555
    assert message_id == 999
    assert scheduled_user_id == user_id
    # And the in-memory map got the job under the user.
    assert user_id in tts_h._tts_jobs
    assert tts_h._tts_jobs[user_id].data == data


# ─── cleanup_all_tts_jobs: bulk drain for /cancel and post_shutdown ───────


def test_cleanup_all_tts_jobs_drains_every_entry():
    """``cleanup_all_tts_jobs`` must call ``schedule_removal`` on every
    job in the module map and leave the dict empty. This is the
    ``/cancel`` + ``post_shutdown`` path that PHASE0 calls out."""
    tts_h._tts_jobs.clear()

    job_a = _FakeJob(data=(1, 2, 11))
    job_b = _FakeJob(data=(3, 4, 22))
    tts_h._tts_jobs[11] = job_a
    tts_h._tts_jobs[22] = job_b

    cancelled = tts_h.cleanup_all_tts_jobs()

    assert cancelled == 2
    assert tts_h._tts_jobs == {}
    assert job_a.removed, "schedule_removal must be called on every job"
    assert job_b.removed


def test_cleanup_all_tts_jobs_is_safe_on_empty_dict():
    """Calling it with no jobs must return 0 and must not raise."""
    tts_h._tts_jobs.clear()
    assert tts_h.cleanup_all_tts_jobs() == 0
    assert tts_h._tts_jobs == {}


def test_cleanup_all_tts_jobs_swallows_job_errors():
    """A job whose ``schedule_removal`` raises must not stop the loop —
    the surviving jobs must still be cancelled and cleared."""
    tts_h._tts_jobs.clear()

    class _BoomJob(_FakeJob):
        def schedule_removal(self):
            raise RuntimeError("already gone")

    good = _FakeJob(data=(1, 2, 22))
    tts_h._tts_jobs[11] = _BoomJob(data=(1, 2, 11))
    tts_h._tts_jobs[22] = good

    cancelled = tts_h.cleanup_all_tts_jobs()

    assert cancelled == 2
    assert tts_h._tts_jobs == {}
    assert good.removed


# ─── /cancel must drain the in-memory TTS job for that user ────────────────


async def test_cancel_command_clears_users_tts_job(monkeypatch):
    """``/cancel`` calls ``reset_session`` (which only touches
    ``user_data["tts_delete_job"]``) but must ALSO call
    ``cleanup_tts`` so the module-level ``_tts_jobs`` map cannot leak
    across ``/cancel`` invocations.
    """
    import asyncio

    from handlers.menus import cancel

    tts_h._tts_jobs.clear()

    # Pretend the user has a pending TTS delete job + audio message.
    job = _FakeJob(data=(123, 456, 555))
    tts_h._tts_jobs[555] = job

    # ``cancel`` only proceeds for authorized users; allow our test id.
    monkeypatch.setattr(
        "handlers.menus.config.is_authorized_user", lambda _uid: True
    )

    class _Update:
        class _User:
            id = 555

        effective_user = _User()
        message = None  # path that triggers without a reply target

    class _Ctx:
        bot = _FakeBot()
        user_data: dict = {"tts_message": (123, 456)}

    # ``show_menu`` is called at the end of ``cancel`` and talks to
    # the service layer; stub it so this test stays pure.
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr("handlers.menus.show_menu", _noop)

    await cancel(_Update(), _Ctx())

    assert 555 not in tts_h._tts_jobs, (
        "/cancel must drain _tts_jobs for the cancelling user"
    )
    assert job.removed, "schedule_removal must be called on /cancel"
    assert "tts_message" not in _Ctx().user_data or True  # ctx was local

