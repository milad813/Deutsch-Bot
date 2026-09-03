Phase 1 checklist:
- [ ] Callback data is generated centrally and length-protected
- [x] HTML rendering is tag-aware and has plain-text fallback
- [x] Temporary user_data state is JSON-safe or explicitly documented
- [ ] Story generation runs in background jobs
- [ ] Daily reminders use batched queries and respect flood limits
- [ ] Structured logging exists for important operational events
- [ ] Admin can view status and usage
- [ ] Local test/check scripts exist
- [ ] All tests pass

## User_data JSON-safety (Phase 1, item 3)

Goal: drop Python-only objects from `context.user_data` so a future
swap of `PicklePersistence` for `JSONPersistence` does not require
re-writing every consumer.

### Changes

- `flashcard_session.py`
  - `flashcard_queue` is now a `list[int]` (was `collections.deque`).
    `pop_queue()` uses `list.pop(0)`, the requeue-on-Again block uses
    `list.insert(0, word_id)`.  Both are O(n) but the queue is bounded
    by `config.FLASHCARD_QUEUE_LIMIT` (≤ 20), so the cost is
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
manual migration is required — one bot restart is enough.
