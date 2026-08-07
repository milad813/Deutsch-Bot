"""Test configuration and fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_context():
    """Create a mock Telegram context."""
    context = MagicMock()
    context.user_data = {}
    context.bot = AsyncMock()
    context.job_queue = MagicMock()
    return context


@pytest.fixture
def mock_update():
    """Create a mock Telegram update."""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.from_user.id = 123456
    update.callback_query.data = "test_callback"
    update.message = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 123456
    update.effective_user.first_name = "Test User"
    return update


@pytest.fixture
def mock_authorized_update():
    """Create a mock authorized Telegram update."""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.from_user.id = 987654321  # Admin ID
    update.callback_query.data = "test_callback"
    update.message = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 987654321
    update.effective_user.first_name = "Admin"
    return update


@pytest.fixture
def mock_unauthorized_update():
    """Create a mock unauthorized Telegram update."""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.from_user.id = 111111  # Not admin
    update.callback_query.data = "test_callback"
    update.message = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 111111
    update.effective_user.first_name = "Unauthorized"
    return update


@pytest.fixture
def mock_db_connection():
    """Create a mock database connection."""
    with patch("app.database.connection.DatabaseConnection") as mock:
        yield mock


@pytest.fixture
def mock_word_repository():
    """Create a mock word repository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo.get_due_words = MagicMock(return_value=[])
    repo.count_due = MagicMock(return_value=0)
    repo.count_hard_due = MagicMock(return_value=0)
    return repo


@pytest.fixture
def mock_user_repository():
    """Create a mock user repository."""
    repo = MagicMock()
    repo.get_or_create_stats = MagicMock(return_value={"correct": 0, "total": 0})
    repo.update_stats = MagicMock()
    repo.get_progress = MagicMock(return_value={"xp": 0, "streak": 0})
    repo.update_progress = MagicMock(return_value={"xp": 10, "streak": 1})
    return repo


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service."""
    llm = MagicMock()
    llm.is_available = MagicMock(return_value=False)
    llm.generate_quiz_question = AsyncMock(return_value=None)
    llm.generate_reverse_quiz = AsyncMock(return_value=None)
    return llm


@pytest.fixture
def mock_fsrs_service():
    """Create a mock FSRS service."""
    fsrs = MagicMock()
    fsrs.get_state = MagicMock(return_value=None)
    fsrs.review = MagicMock(return_value=(MagicMock(), 0))
    fsrs.get_review_cards = MagicMock(return_value=[])
    return fsrs
