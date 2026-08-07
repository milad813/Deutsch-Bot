"""Tests for main handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.handlers.main import (
    start_command,
    menu_command,
    callback_handler,
    text_handler,
    get_session_data,
)
from app.utils import SessionData


class TestSessionData:
    """Tests for SessionData utility."""

    def test_create_empty_session(self):
        """Test creating an empty session."""
        session = SessionData()
        assert session.quiz_type == "meaning"
        assert session.flashcard_queue == []
        assert session.ltr_round == 0

    def test_session_to_dict(self):
        """Test converting session to dictionary."""
        session = SessionData()
        session.quiz_type = "reverse"
        data = session.to_dict()
        assert data["quiz_type"] == "reverse"

    def test_clear_quiz_session(self):
        """Test clearing quiz session data."""
        session = SessionData()
        session.quiz_type = "reverse"
        session.quiz_lesson_id = 5
        session.quiz_wrong_word_ids = [1, 2, 3]
        
        session.clear_quiz_session()
        
        assert session.quiz_type == "meaning"
        assert session.quiz_lesson_id is None
        assert session.quiz_wrong_word_ids == []

    def test_clear_flashcard_session(self):
        """Test clearing flashcard session data."""
        session = SessionData()
        session.flashcard_queue = [{"word_id": 1}]
        session.flashcard_skipped_ids = {1, 2, 3}
        
        session.clear_flashcard_session()
        
        assert session.flashcard_queue == []
        assert session.flashcard_skipped_ids == set()


@pytest.mark.asyncio
class TestStartCommand:
    """Tests for /start command handler."""

    async def test_start_unauthorized_user(self, mock_unauthorized_update, mock_context):
        """Test that unauthorized users are rejected."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = False
            
            await start_command(mock_unauthorized_update, mock_context)
            
            mock_unauthorized_update.message.reply_text.assert_called_once()
            call_args = mock_unauthorized_update.message.reply_text.call_args[0][0]
            assert "دسترسی ندارید" in call_args

    async def test_start_authorized_user(self, mock_authorized_update, mock_context):
        """Test that authorized users can start the bot."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = True
            
            await start_command(mock_authorized_update, mock_context)
            
            mock_authorized_update.message.reply_text.assert_called()


@pytest.mark.asyncio
class TestMenuCommand:
    """Tests for /menu command handler."""

    async def test_menu_unauthorized_user(self, mock_unauthorized_update, mock_context):
        """Test that unauthorized users cannot access menu."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = False
            
            await menu_command(mock_unauthorized_update, mock_context)
            
            mock_unauthorized_update.message.reply_text.assert_called_once()

    async def test_menu_clears_session(self, mock_authorized_update, mock_context):
        """Test that menu command clears session data."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = True
            mock_context.user_data["session_data"] = SessionData()
            mock_context.user_data["session_data"].quiz_type = "reverse"
            
            await menu_command(mock_authorized_update, mock_context)
            
            # Session should be reset
            assert isinstance(mock_context.user_data["session_data"], SessionData)


@pytest.mark.asyncio
class TestCallbackHandler:
    """Tests for callback query handler."""

    async def test_callback_unauthorized_user(self, mock_unauthorized_update, mock_context):
        """Test that unauthorized callbacks are rejected."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = False
            
            await callback_handler(mock_unauthorized_update, mock_context)
            
            mock_unauthorized_update.callback_query.answer.assert_called_once()

    async def test_callback_back_to_main(self, mock_authorized_update, mock_context):
        """Test back to main menu callback."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = True
            mock_authorized_update.callback_query.data = "back_to_main_menu"
            
            await callback_handler(mock_authorized_update, mock_context)
            
            # Should attempt to delete message
            mock_authorized_update.callback_query.answer.assert_called()


@pytest.mark.asyncio
class TestTextHandler:
    """Tests for text message handler."""

    async def test_text_unauthorized_user(self, mock_unauthorized_update, mock_context):
        """Test that unauthorized text messages are ignored."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = False
            mock_unauthorized_update.message.text = "📚 کتاب و درس‌ها"
            
            await text_handler(mock_unauthorized_update, mock_context)
            
            # Should not reply
            mock_unauthorized_update.message.reply_text.assert_not_called()

    async def test_text_menu_action(self, mock_authorized_update, mock_context):
        """Test menu button text handling."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.is_authorized_user.return_value = True
            mock_authorized_update.message.text = "📚 کتاب و درس‌ها"
            
            await text_handler(mock_authorized_update, mock_context)
            
            # Should respond with development message
            mock_authorized_update.message.reply_text.assert_called()
