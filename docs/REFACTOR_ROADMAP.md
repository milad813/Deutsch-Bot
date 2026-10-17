# Refactor roadmap (Phases R1–R6)

> Continues the hardening work of `docs/PHASE0.md` / `docs/PHASE1.md`.
> Each phase is a set of small, individually verifiable steps; every
> step must keep `python scripts/run_checks.py` green and all tests
> passing. The Phase 2 backlog (`docs/PHASE2_BACKLOG.md`) slots in
> after R2–R4, in dependency order.

## Phase R1 — Freeze the safety net ✅ (done)

Goal: make every later step mechanically verifiable.

Delivered:

- **ruff + mypy** added (`requirements-dev.txt`, config in `pyproject.toml`),
  wired into `scripts/run_checks.py` (steps 3–4, with `--skip-ruff` /
  `--skip-mypy`) and the CI lint job. The mypy per-module override list in
  `pyproject.toml` is the **typing debt register**: delete entries layer by
  layer in R2+ (services first, then handlers, then database).
- **Tool consolidation:** the old lint job (`black` + `isort` + `flake8`)
  was already failing on the tree (black wanted to reformat 66 files), so
  the stack was consolidated on ruff (`ruff check` + `ruff format`) in CI,
  pre-commit and local checks. One-time `ruff format .` pass normalized
  the codebase (69 files, mechanical only).
- **Import-hygiene layer rules** in `tests/test_import_hygiene.py`:
  domain → nothing; core/database/middleware → no services/handlers/
  telegram; services → no handlers; handlers → no database. Extend the
  forbidden lists as layers get cleaned up.
- **Coverage baseline:** 63% on Python 3.12; CI enforces
  `--cov-fail-under=60` (raised as coverage grows).
- **Real bugs fixed** (all caught by the baseline lint, none covered by
  the old test suite):
  - `handlers/story/view.py::_build_story_view` referenced an undefined
    `story_id` — every story action button (listen/read, quiz, words,
    hint) raised `NameError`. Signature now takes `story_id`; both
    callers pass it.
  - `handlers/menus.py` had no `show_lessons_for_quiz`, but the callback
    router's `_handle_quiz_book` calls it — every book tap in the
    quiz-by-lesson flow raised `AttributeError`. Implemented (modeled on
    `show_lessons`, emitting `QUIZ_LESSON` callbacks).
  - `llm_service.py` logged `GROQ_API_KEYS` (undefined) in the
    all-keys-failed path → `NameError` inside the error handler. Now
    `config.GROQ_API_KEYS`.
  - `bot.py` daily-reminder loop shadowed the imported `start` handler
    with a loop variable (renamed to `start_idx`).
- **Environment repair:** the committed `.venv` was broken (pointed at a
  non-existent base interpreter) and a stray Linux `pyvenv.cfg` sat in the
  repo root; both removed, venv rebuilt on Python 3.12.
- Regression guards for the bug fixes: `tests/test_phase_r1_guards.py`.

## Phase R2 — Finish the dependency-injection migration ✅ (done)

Goal: one construction point, no import-time construction.

Delivered (via lazy container rather than a mass call-site rewrite):

- **No import-time construction.** `services/__init__.py` no longer calls
  `build_app()` at import. Importing `bot`, `handlers`, or `services` is
  side-effect free; the `AppContext` is built once, on first use, by
  `services.get_app()` and cached. Pinned by
  `tests/test_services_lazy.py` (subprocess check: `import bot, handlers,
  services` → `is_app_built() is False`).
- **Canonical instance in production.** `bot.main()` calls `get_app()`
  explicitly and stores the real instance in `application.bot_data["app"]`;
  `post_shutdown` closes it.
- **Legacy call sites keep working via late-binding proxies.** The
  module-level names (`db`, `llm`, `fsrs`, `tts`, `quiz_service`, `app`)
  are proxies that resolve against the *current* `AppContext` on every
  attribute access — so `from services import db` no longer constructs
  anything, monkeypatching `services.db.<repo>` still patches the object
  handlers resolve to, and `set_app()` / `reset_app()` let tests swap the
  whole context.
- **Test fixes:** three `monkeypatch.setattr(<proxy>, ...)` call sites
  (they now patch the underlying service instance from `get_app()` —
  proxies are read-through).
- **mypy debt register trimmed:** `services.container` and `config.DB_PATH`
  typing fixed and removed from the ignore list.

Remaining R2 follow-up (folded into R3/R4): as each handler file is
touched/moved, switch it from the `services` proxy names to
`context.bot_data["app"]`; delete the proxies once the last call site is
gone.

Exit criteria met: no import-time construction; single construction point;
services injectable in tests without monkeypatching module globals.

## Phase R3 — Dissolve the legacy root modules ✅ (done)

Pure moves + re-export shims; every historical import path keeps working
(295 tests green before and after each move):

- **`models.py` split.** Pure dataclasses (`Word`, `QuizSession`,
  `QuizType`) → `domain/models.py`; `CallbackPrefix` → `core/callbacks.py`
  (it is a Telegram routing concern, not a domain model). Root `models.py`
  is now a shim re-exporting both — its ~22 importers are untouched.
- **Pure logic → `domain/`.** `utils.py` → `domain/utils.py`,
  `option_generator.py` → `domain/option_generator.py` (now imports
  `domain.models` directly), both with root shims.
- **Services → `services/`.** `llm_service.py` → `services/llm.py`,
  `srs_service.py` → `services/srs.py`, `quiz_service.py` →
  `services/quiz.py`, `tts_service.py` → `services/tts.py`;
  `container.py` imports them directly. Root shims keep scripts/tests
  (`from srs_service import FSRSParams, FSRSService, FSRSState`) working.
- **`ui.py` (700 lines) → `ui/` package.** `ui/text.py` (escaping,
  sanitising, tag-aware chunk splitter, formatting — zero telegram
  imports), `ui/keyboards.py` (button/menu builders),
  `ui/render.py` (`render()` with HTML→plain-text fallback). The package
  `__init__` re-exports the combined surface, so all `from ui import X`
  call sites and the Phase 1 shape pins still pass
  (`test_phase1_checks.py` updated for the package layout).
- **Deferred:** `config.py` stays at root for now — moving it into
  `core/` would trip the middleware layer rule (`middleware` may not
  import `core`); move it together with a hygiene-rule update in R4.
- mypy debt register renamed for the moved modules
  (`services.llm`, `services.srs`, `services.tts`,
  `domain.option_generator`).

Exit criteria met: root holds only `bot.py`, the shims, and `config.py`;
all old import paths work; test count unchanged (295).

## Phase R4 — Split handler god-files and type the sessions

1. Split `handlers/menus.py` (900+ lines): navigation vs settings.
2. Extract pure question/rendering logic from `handlers/quiz_handlers.py`
   and `handlers/story/core.py` into `domain/` functions
   `(session, input) -> (text, keyboard)`.
3. Give every session dict a `TypedDict` in `core/sessions.py` plus an
   accessor module; handlers never touch `user_data[...]` keys directly
   (pin with a source-inspection test).
4. Move job bodies out of `bot.py` into `jobs/`.

Exit: no handler file over ~400 lines; session access only via accessors.

## Phase R5 — Database layer consolidation

1. Replace the flat 672-line `database/repositories/__init__.py` facade
   with explicit repository attributes.
2. Split `database/repositories/learning.py` (800+ lines) by concern.
3. Add a `PRAGMA user_version` migration runner; route all schema changes
   through it.

Exit: repos under ~300 lines each; migrate-from-scratch test in
`tests/test_schema.py`.

## Phase R6 — Phase-2 backlog integration

1. JSON persistence (trivial after R2/R4; user_data is already JSON-safe).
2. Webhook deployment (after the `jobs/` extraction makes `bot.py` thin).
3. Placement test / writing exercises / moderation (after R4 gives them
   clean insertion points in `domain/quiz_flow.py` and the story split).

## Maintenance update — 2026-10-17

Menu/settings/dashboard/quiz navigation and question generation are now split.
Flashcard state and keyboards have dedicated modules. Repository catalogue,
users/reminders, and learning concerns are separated behind stable imports.
Schema upgrades are atomic and use PRAGMA user_version (schema 6).
See [the audit](REFACTOR_AUDIT.md) for the verified fixes and dead-code removals.
The remaining TypedDict/accessor migration and deployment phases above are not
marked complete by these changes.
