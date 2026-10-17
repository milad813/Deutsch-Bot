"""Shared test configuration.

Runs BEFORE any test module import, so the environment is ready when
config/services get imported (they read env vars at import time).
"""

import os
import tempfile
import pytest

# Never inherit a production DB_PATH. Each pytest process owns its database.
_test_db_dir = tempfile.TemporaryDirectory(prefix="deutsch-bot-tests-", ignore_cleanup_errors=True)
os.environ["DB_PATH"] = os.path.join(_test_db_dir.name, "words.db")

# Keep LLM/TTS disabled during tests regardless of local .env contents.
os.environ["BOT_MODE"] = "offline"


@pytest.fixture(scope="session", autouse=True)
def close_test_services():
    yield
    import services

    if services.is_app_built():
        services.get_app().close()
        services.reset_app()
    _test_db_dir.cleanup()
