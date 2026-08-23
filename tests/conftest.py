"""Shared test configuration.

Runs BEFORE any test module import, so the environment is ready when
config/services get imported (they read env vars at import time).
"""

import os
import tempfile

# Use a throwaway database so tests never touch words.db in the project root.
os.environ.setdefault(
    "DB_PATH",
    os.path.join(tempfile.gettempdir(), "deutsch_bot_test_words.db"),
)

# Keep LLM/TTS disabled during tests regardless of local .env contents.
os.environ.setdefault("BOT_MODE", "offline")