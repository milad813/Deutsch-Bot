# Phase 2 backlog

> **Status:** planning only. Do not start work on this list until Phase 1
> is officially tagged as shipped.
>
> Each item below names a single, *self-contained* deliverable. They
> are ordered by approximate priority / dependency order, but any
> subset may be tackled in any order.

This document is the inbox of ideas that came up while building
Phase 1. It is intentionally **not** a roadmap or commitment: items
will be re-scoped, dropped, or merged as we learn more.

## Infrastructure & reliability

- [ ] **Move from `PicklePersistence` to safer session storage.**
  Phase 1 already removed every Python-only object from
  `context.user_data` (Phase 1, item 3) so this is now feasible.
  Candidates: a hand-rolled `JSONPersistence`, or a thin wrapper
  around `redis`/`sqlite` so the bot can survive a restart without
  losing user state. Must include a one-way migration script and
  a `dry-run` mode that emits a diff before the cutover.

- [ ] **Add a webhook deployment option.**
  Today the bot only runs as `python-telegram-bot` polling, which
  is fine for a single dev instance but does not scale to a
  horizontally-shared deployment. Webhook mode + a small
  reverse-proxy example (`caddy` or `nginx`) would unlock
  Fly.io / Render / a small VPS. Must coexist with the existing
  polling entrypoint, gated by an env var.

- [ ] **Add metrics dashboard.**
  Right now operational visibility comes from `log_event` records
  and `/status`. A Prometheus exporter (or a tiny FastAPI sidecar)
  that surfaces the same numbers as time-series data would let us
  graph LLM quota burn, reminder batch sizes, and TTS cache hit
  rate over time. Must not require a new heavy dependency; the
  stdlib `http.server` is enough for the first cut.

## Pedagogy & content

- [ ] **Add placement test.**
  Onboarding flow for new users: 15-20 mixed-difficulty questions
  across the existing word/quiz/grammar surfaces, then route the
  user to the matching CEFR level (A1, A2, B1) and seed their
  SRS queue with a starter set. Must reuse the existing quiz
  pipeline and not duplicate scoring logic.

- [ ] **Add CEFR can-do lesson structure.**
  Tag every existing lesson with a CEFR level and a `can_do`
  statement ("can order food in a restaurant"). Lessons become
  filterable by level so the user always sees material calibrated
  to their stage. Schema migration: nullable `level` and
  `can_do` columns on `lessons`; UI: a level filter on the lesson
  browser.

- [ ] **Add writing exercises.**
  Prompt the user with a short German writing task ("write three
  sentences about your morning routine"), collect the reply,
  send it to the LLM for a 0-5 rubric score + short feedback,
  store the score in the learning history so the SRS engine can
  weight it. Must respect the LLM quota gate from Phase 1.

- [ ] **Add speaking / shadowing exercises.**
  Play a TTS clip of a target sentence, ask the user to repeat
  it, and (optionally) score their attempt against the same
  sentence using a speech-to-text provider. The TTS half already
  exists; STT and similarity scoring are new. Must degrade
  gracefully when no STT provider is configured.

- [ ] **Add roleplay dialogues.**
  Scenario-based practice ("you are at the bakery, order
  three items"). Built on top of the existing story pipeline
  with a stricter system prompt and a fixed turn budget. Each
  completed roleplay becomes a flashcard-derivable artefact.

- [ ] **Add grammar-in-context exercises.**
  Spot-the-grammar-error questions drawn from the existing
  sentence corpus. New table for `grammar_points`
  (`pattern`, `explanation`, `example_sentence_id`); new
  `/grammar` command and a session handler that reuses the
  quiz-session dict shape from Phase 1 (so no JSON-safety work
  is needed).

## Trust & safety

- [ ] **Add content moderation / review workflow.**
  Today the LLM is asked to produce learner-appropriate German
  with a system prompt; there is no second-pass check. A small
  moderation step (LLM-as-judge or a regex/word-list filter) on
  every story and example would catch off-policy output before
  it reaches the user. Must be async, must not block the
  existing `generate_story_job`, and must be toggleable via env
  var (`MODERATION_ENABLED=0` to disable on dev).

