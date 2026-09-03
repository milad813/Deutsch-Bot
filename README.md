# Deutsch-Bot

A Persian-language Telegram bot for learning German vocabulary, grammar, and
reading comprehension.  Built on
[`python-telegram-bot`](https://docs.python-telegram-bot.org/) and an
SQLite-backed content store.  LLM features (story generation, contextual
example generation) are optional and degrade gracefully when no `groq`
credentials are configured.

The bot has a single authorised user by default (see
`ADMIN_USER_ID` / `ALLOW_PUBLIC_ACCESS` below) and is intended for private
single-user setups.  A public mode is also supported.

For the per-phase architecture notes see:

* `docs/PHASE0.md` -- security & reliability hardening.
* `docs/PHASE1.md` -- monitoring, /status view, LLM quotas.

## Quick start

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy the environment template and fill in real values:

   ```bash
   cp .env.example .env
   ```

   See [Environment variables](#environment-variables) below for the full
   list.  The minimum required to start the bot is `TELEGRAM_BOT_TOKEN`
   and (for private mode) `ADMIN_USER_ID`.

5. Run the bot:

   ```bash
   python bot.py
   ```

The first start creates `words.db` and runs the additive schema migrations
in `database/schema.py`.  No data is downloaded -- you can populate
vocabulary via the `scripts/import_csv.py` helper.

## Development

### How to run tests

```bash
python -m pytest -q
```

This runs every test in `tests/` and prints a one-line summary.  Tests use
a throwaway SQLite database (see `tests/conftest.py`) and never touch
your real `words.db`.

The full suite takes ~10s locally.  Individual test files can be run
with the standard pytest selection syntax, e.g.:

```bash
python -m pytest tests/test_callbacks_codec.py -q
```



### How to run all checks

```bash
python scripts/run_checks.py
```

This is the single entry point used by both humans and CI.  It runs:

1. `pytest -q` -- the unit / regression tests.
2. `python -m compileall -q <project root>` -- bytecode-compiles every
   `.py` file under the project root to catch syntax errors that the
   test suite might not hit.

The script prints a clear PASS/FAIL table at the end and exits with
a non-zero code on any failure, so it is safe to use in shell pipelines
or as a pre-commit gate.

Flags:

* `--skip-pytest` -- skip the test step (useful when iterating on
  compile-only changes).
* `--skip-compileall` -- skip the bytecode-compile step.

On Windows, a PowerShell wrapper is also provided for convenience:

```powershell
.\scripts\run_checks.ps1
```

The wrapper resolves the active virtualenv's Python automatically and
propagates the underlying exit code to `$LASTEXITCODE`.

### Project layout

```
bot.py                       -- entry point; wires handlers and the job queue
config.py                    -- environment-driven configuration
core/                        -- shared utilities (callbacks, logging, sessions, ...)
database/                    -- schema, migrations, repositories
domain/                      -- domain entities and pure helpers
handlers/                    -- Telegram handlers (story, quiz, flashcard, ...)
middleware/                  -- rate limiter, error handlers
scripts/                     -- maintenance scripts and ``run_checks.py``
services/                    -- external-facing services (TTS, etc.)
tests/                       -- pytest test suite
docs/                        -- phase notes, design docs
```


## Environment variables

All runtime configuration is driven by environment variables.  The full
template with safe placeholder values lives in
[`.env.example`](.env.example).  Copy it to `.env` and fill in the
values you need; the bot reads both `.env` (if `python-dotenv` is
installed) and the process environment, with the latter taking
precedence.

| Variable | Purpose | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather. **Required.** | -- |
| `ADMIN_USER_ID` | Telegram numeric user id of the bot owner. | `0` |
| `ALLOW_PUBLIC_ACCESS` | `1` to allow any Telegram user to use the bot. | `0` |
| `DB_PATH` | SQLite database file (relative paths are resolved from the project root). | `words.db` |
| `AUDIO_CACHE_DIR` | Where generated TTS audio is cached. | `audio_cache` |
| `BOT_MODE` | `offline` (no LLM), `hybrid` (opportunistic), or `online` (LLM mandatory). | `offline` |
| `GROQ_API_KEY` | Primary Groq API key. | empty |
| `GROQ_API_KEYS` | Comma-separated list of fallback Groq keys. | empty |
| `GROQ_MODEL` | Default Groq chat model. | `llama-3.3-70b-versatile` |
| `LLM_TIMEOUT_SECONDS` | Hard timeout for non-quiz LLM calls. | `8` |
| `QUIZ_LLM_TIMEOUT_SECONDS` | Hard timeout for quiz LLM calls. | `2.5` |
| `FLASHCARD_QUEUE_LIMIT` | Max cards loaded into one flashcard session. | `20` |
| `FLASHCARD_NEW_LIMIT` | Max *new* cards mixed into a flashcard session. | `5` |
| `TTS_AUTO_DELETE_SECONDS` | Auto-delete ephemeral TTS after N seconds; `0` disables. | `60` |
| `DAILY_REMINDER_HOUR_LOCAL` / `DAILY_REMINDER_MINUTE_LOCAL` | When the daily reminder fires (user-local). | `9` / `0` |
| `USER_TIMEZONE_OFFSET_HOURS` / `_MINUTES` | User timezone offset (Iran = +3:30). | `3` / `30` |
| `REMINDER_BATCH_SIZE` | Opt-in users per batch for the daily reminder job. | `50` |
| `REMINDER_SLEEP_SECONDS` | Pause between reminder batches. | `1.0` |
| `BACKUP_KEEP_DAYS` / `BACKUP_KEEP_MAX` | Retention policy for daily DB backups. | `14` / `30` |
| `LOG_FORMAT` | `text` (human-readable) or `json` (one line per record). | `text` |
| `LOG_LEVEL` | Standard level name (`DEBUG` / `INFO` / ...). | `INFO` |
| `RATE_LIMIT_MAX_REQUESTS` | Max accepted requests per user per sliding window. | `80` |
| `RATE_LIMIT_WINDOW_SECONDS` | Length of the sliding window. | `60` |
| `LLM_DAILY_STORY_LIMIT` | Per-user daily LLM story quota. | `20` |
| `LLM_DAILY_EXAMPLE_LIMIT` | Per-user daily LLM example quota. | `200` |

For the up-to-date list with full inline comments see
[`.env.example`](.env.example).

## Continuous integration

The repository ships with a GitHub Actions workflow at
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) that runs the test
suite on Python 3.9 / 3.10 / 3.11 for every push and pull request, plus
a formatting/linting job (`black`, `isort`, `flake8`).  Locally the same
checks can be run with:

```bash
python scripts/run_checks.py
black --check .
isort --check-only .
flake8 . --max-line-length=100 --extend-ignore=E203
```

## License

See [`LICENSE`](LICENSE).
