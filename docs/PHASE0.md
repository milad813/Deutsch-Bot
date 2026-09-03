# Phase 0 — Hardening checklist

This document captures the **Phase 0** hardening goals for the Deutsch-Bot
repository. Phase 0 is intentionally **behavior-preserving**: no refactors of
the database layer, no migration to webhook, no new dependencies, and no
pedagogical changes. The focus is making the bot safer, more robust, and
better behaved under multi-user / abuse conditions.

The accompanying preparation artifacts (this file, `.env.example`, and the
`phase0-hardening` branch) are tracked here so future phases can pick up
without re-litigating scope.

---

## Phase 0 goals

- [ ] **Make bot private-chat safe**
  - Confirm `config.is_authorized_user` is enforced in **every** entry point
    (`CommandHandler`, `MessageHandler`, `CallbackQueryHandler`, inline
    jobs). Today the check exists in `inline_handler` and `handle_text_input`
    but a couple of admin / direct callbacks may rely on the router alone.
  - Reject calls from unauthorized users in `inline_handler`, `start`,
    `show_menu`, and any helper reachable without the router.

- [ ] **Add `/cancel` command**
  - Register a new `CommandHandler("cancel", ...)` in `bot.py`.
  - It must call `reset_session(context)` (already exposed via
    `services.reset_session`) and confirm to the user.
  - Should also cancel any pending TTS delete jobs (see next item).

- [ ] **Fix `response_time_sec` bug**
  - `learning_engine.record_quiz_answer` already accepts
    `response_time_sec`. Audit every call site and ensure callers either pass
    a `float` or `None` — never an `await`-able object or wrong type.

- [ ] **Fix TTS job leak**
  - `handlers/tts_handlers.py` keeps a module-level `_tts_jobs` dict that
    grows unbounded and never gets cleaned when a user ends their session
    silently. Make sure:
      - The dict is cleared when the user ends the chat/session.
      - The job is cancelled on `/cancel`, on `reset_session`, and on bot
        shutdown (`post_shutdown`).
      - The `_tts_jobs` dict is bounded by the active user set.

- [ ] **Add callback-data length protection**
  - Telegram caps callback_data at 64 bytes. Today, dynamic suffixes
    (`quiz_count:all`, `lesson_words_3_2`, etc.) are short, but story
    titles/words and lesson ids can blow the limit.
  - Add a guard in `core/callbacks.cb()` (or in the router) that asserts
    `len(data) <= 64` and truncates / logs violations.

- [ ] **Add LLM quota protection**
  - `LLMService._chat` should track concurrent in-flight requests and short-
    circuit (return `None` / fallback) when above a configurable limit.
  - Optional: a simple token-bucket per minute to avoid hitting Groq RPM/TPM
    limits when many users spam LLM-dependent features.

- [ ] **Add reminder opt-in / opt-out**
  - The `daily_reminder` job currently sends a message to *every* user
    discovered in the DB. Add an opt-in flag (default = opt-out) so users
    can disable it from the settings menu.
  - Persist the flag in `user_settings` (new column, additive migration
    only).

- [ ] **Make HTML rendering safer**
  - `ui.sanitize_html` allows only a small set of tags but several handlers
    still build HTML with raw `f"{user_input}"`. Audit and replace all
    `esc(...)` misses, especially in `menus.py`, `story/view.py`, and
    admin handlers.

- [ ] **Add rate-limiter cleanup**
  - `middleware/rate_limiter.RateLimiter` keeps entries forever for users
    who stop using the bot. Add a periodic sweep that drops entries whose
    newest request is older than `window_seconds`.

- [ ] **Keep all tests passing**
  - Run `python -m pytest -q` after each item and ensure no regression.
  - Add tests for the new behaviors (`/cancel`, length guard, opt-out,
    LLM quota) before merging.

---

## Non-goals for Phase 0

The following are **out of scope** for this phase and must not be touched:

- No database architecture refactors (no new ORM, no schema redesign).
- No migration from polling to webhook.
- No new third-party dependencies.
- No changes to pedagogical / SRS logic.

Anything that falls into the above categories belongs to Phase 1+.

---

## Preparation artifacts (this commit)

- `.env.example` — safe placeholder environment variables, derived from
  `config.py`. Should be the template used for new deployments.
- `docs/PHASE0.md` — this file.
- Branch `phase0-hardening` — all Phase 0 work lands here before being
  merged back to `main`.