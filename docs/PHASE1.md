Phase 1 checklist:
- [x] Callback data is generated centrally and length-protected (`core/callbacks.cb_safe` + 64-byte guard)
- [x] HTML rendering is tag-aware and has plain-text fallback
- [x] Temporary user_data state is JSON-safe or explicitly documented
- [x] Story generation runs in background jobs (`handlers/story/jobs.py::generate_story_job`)
- [x] Daily reminders use batched queries and respect flood limits (opt-in via `get_reminder_user_ids` + `REMINDER_BATCH_SIZE` chunks + `RetryAfter` handling)
- [x] Structured logging exists for important operational events (`core/logging_utils.log_event`)
- [x] Admin can view status and usage (`/status` -> `handlers/admin_handlers.show_status`)
- [x] Local test/check scripts exist (`scripts/run_checks.py` + `scripts/run_checks.ps1`)
- [x] All tests pass (282 passed, 0 warnings)


## User_data JSON-safety (Phase 1, item 3)

Goal: drop Python-only objects from `context.user_data` so a future
swap of `PicklePersistence` for `JSONPersistence` does not require
re-writing every consumer.

### Changes

- `flashcard_session.py`
  - `flashcard_queue` is now a `list[int]` (was `collections.deque`).
    `pop_queue()` uses `list.pop(0)`, the requeue-on-Again block uses
    `list.insert(0, word_id)`.  Both are O(n) but the queue is bounded
    by `config.FLASHCARD_QUEUE_LIMIT` (<= 20), so the cost is
    negligible.
  - `flashcard_skipped_ids` is now a `list[int]` (was `set[int]`).
    Idempotency is preserved by an `in` check before `append`.
  - A private `_coerce_to_list` helper normalises any legacy `deque`
    / `set` value left in `user_data` by older bot instances after
    `PicklePersistence` reload, so a one-time migration is safe.
- `ltr_session.py`
  - `ltr_word_success_types` is now `dict[word_id, list[str]]`
    (was `dict[word_id, set[str]]`).  Uniqueness is preserved by an
    `in` check before `append`.  The reader in `ltr_handlers.py`
    only ever uses `len(success_types)`, so the change is transparent
    to that call site.
- `quiz_handlers.py`
  - `quiz_session_obj` is now a plain `dict` with eight fields
    (`quiz_type`, `total_questions`, `current_index`, `correct_count`,
    `wrong_count`, `question_ids`, `source_filter`, `lesson_id`).
    Previously a `models.QuizSession` dataclass instance.  All
    helpers (`_init_quiz_session`, `_get_quiz_session`,
    `_update_quiz_session`, `_get_session_progress`,
    `_is_session_finished`, `_show_quiz_summary`) and the lone
    external reader in `_start_generic_quiz` were rewritten to use
    `dict[str, Any]`.
  - The `from models import QuizSession` import in `quiz_handlers.py`
    was removed; the dataclass remains in `models.py` for any
    downstream code that still imports it.
  - `tests/test_quiz_flow.py` was updated to build the session as a
    plain dict (`_make_session()` helper) instead of a `QuizSession`
    dataclass.
- `tests/test_user_data_json_safety.py` (new)
  - Asserts `json.dumps(context.user_data, default=str)` succeeds
    after each session is initialised and after realistic interactions
    (queue push/pop, skipped add, LTR success types, quiz
    init+update).  Spot-checks the round-tripped payload to make sure
    the new shapes survive a JSON encode/decode.

### Not changed

- The `QuizSession` dataclass in `models.py` is **kept** so that any
  external tooling that imports it still works.  It is no longer the
  runtime representation under `quiz_session_obj`.
- The `core/sessions.py` registry (typed `SESSION_FEATURES`) only
  enumerates *keys*; the value types were never tracked, so the
  registry requires no edits.
- `PicklePersistence` is still the active persistence backend.  The
  migration to `JSONPersistence` is out of scope for this item and
  will be a separate phase.

### Migration notes (legacy pickled state)

`PicklePersistence` will deserialise any previously-stored `deque`,
`set`, or `QuizSession` value back into its original Python type the
next time the bot is started.  The flashcard helpers detect that case
and coerce the value into a list on first access, writing the new
shape back to `user_data`.  The LTR success-types writer and the quiz
session writer do the same for the legacy shapes they replace.  No
manual migration is required -- one bot restart is enough.

## Local checks (Phase 1, item 8)

A one-shot developer entrypoint that runs the full test suite plus a
byte-compile pass over every source tree, then prints a PASS/FAIL
summary table and exits non-zero on any failure.

### Cross-platform entry points

```bash
# macOS / Linux
python scripts/run_checks.py

# Windows (PowerShell; auto-resolves the venv interpreter)
.\scripts\run_checks.ps1
```

Both invocations:

- prefer the active virtual-env `python.exe` / `python`,
- run `pytest -q -p no:cacheprovider --no-header` first,
- then run `python -m compileall -q` over `core/`, `database/`,
  `domain/`, `handlers/`, `middleware/`, `scripts/`, `services/`,
  `tests/`,
- print a single PASS/FAIL table with elapsed time per step,
- exit `0` only when every step passes (and `1` otherwise).

### Optional flags

```bash
# Skip a step (useful for fast local iteration)
python scripts/run_checks.py --skip-pytest
python scripts/run_checks.py --skip-compileall
```

### No new dependencies

`scripts/run_checks.py` uses only the standard library
(`argparse`, `pathlib`, `subprocess`, `sys`, `platform`, `time`,
`typing`).  `scripts/run_checks.ps1` is a thin shim -- no modules
imported, just process invocation.

### Regression test

`tests/test_phase1_checks.py` (11 tests) pins the *shape* of every
Phase 1 deliverable so a future refactor cannot silently break the
contract:

- `core/callbacks.cb_safe` exists and is importable,
- `ui.split_html_text` exists and is importable,
- `core/logging_utils.log_event` exists and is importable,
- `generate_story_job` is callable (in `handlers/story/jobs.py` or
  the next most-specific location under `handlers/`),
- `bot.daily_reminder` calls `get_reminder_user_ids` and **does not**
  call `get_all_users` (the opt-in rule is enforced structurally).

These tests are pure source inspection -- no DB, no network, no
fixtures -- so they run on a fresh clone in well under a second.

## Manual test checklist

A pre-release smoke test for any developer or QA. Run these steps on
a real Telegram account (or a private test bot) before tagging a
release.  Each step has a clear pass/fail signal that can be checked
without a debugger.

| # | Step | What to verify | Why it matters |
|---|------|----------------|----------------|
| 1 | **Start bot in a private chat** | `/start` returns the main menu with inline keyboard | Confirms the bot token, persistence, and base dispatcher all load |
| 2 | **Send any command in a group chat** | Bot refuses politely (no-op or fixed message), no traceback in logs | Phase 0 privacy guard; unauthorized groups must never get a real reply |
| 3 | **Press each menu button** | Navigation, back, and "main menu" all work; no "old button" warnings | Confirms callback data stays inside the 64-byte Telegram limit and the registry has not drifted |
| 4 | **Generate a story** | Bot acknowledges immediately, the story arrives in a follow-up message after a few seconds; the bot stays responsive to other commands during the wait | Background `generate_story_job` is wired correctly; the main loop is not blocked |
| 5 | **Trigger the LLM quota** (if the bot is configured with a low `DAILY_LLM_LIMIT`) | Bot refuses the next LLM-backed command with the Persian "quota exhausted" message; flashcards and SRS still work (they do not use the LLM) | LLM quota gate is in place; non-LLM features survive a quota outage |
| 6 | **Toggle reminders** (`/settings` -> reminders on/off) | After opting in, a daily reminder arrives at `DAILY_REMINDER_HOUR_LOCAL:DAILY_REMINDER_MINUTE_LOCAL`; after opting out, no reminder arrives the next day | The opt-in flag is honoured by the cron job, not just the UI |
| 7 | **Run `/status` as admin** | Page renders with books, lessons, today LLM usage, top-3 users, and any active warnings; missing tables render as `0`, not as `5xx` | Admin observability is operational |
| 8 | **Inspect the log file** | A recent reminder run produces a `reminder_batch_started` event with `recipient_count`, `batch_size`, and `inter_batch_sleep_seconds` fields; quota hits log a `llm_quota_exceeded` event | Structured logging is wired into the hot paths |
| 9 | **Run a flashcard session** | Words queue, "Again / Hard / Good / Easy" buttons all respond; queue and skipped-list survive a `/cancel` + restart | Flashcard state is JSON-safe and idempotent |
| 10 | **Run a quiz** | Question -> multiple choice -> immediate feedback -> next question -> summary at the end; `/cancel` mid-quiz exits cleanly | Quiz session dict is JSON-safe and the writer/reader agree |
| 11 | **Run an LTR (long-term review) session** | Each word asks for both translation types; `Success` requires *both* types correct; `/cancel` exits cleanly | LTR `success_types` is a `list[str]` per word, not a `set[str]` |
| 12 | **Run `pytest`** | `python -m pytest -q` reports `282 passed` and exits `0`; `python scripts/run_checks.py` reports `ALL CHECKS PASSED` | The Phase 1 regression test + the local check script both pass |

### Quick command reference

```bash
# Pre-flight: full local check before opening a PR
python -m pytest -q
python scripts/run_checks.py

# Just the new Phase 1 regression test (fast smoke)
python -m pytest tests/test_phase1_checks.py -v

# Sanity: structured log events present
grep -E "reminder_batch_started|llm_quota_exceeded|story_job_started" logs/*.log | tail
```
