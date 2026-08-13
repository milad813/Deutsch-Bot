"""Base handler classes and utilities."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class BaseHandler(ABC):
    """Abstract base class for all handlers.

    Provides common functionality like error handling, logging,
    and user authorization checks.
    """

    def __init__(self, name: str = None):
        self.name = name or self.__class__.__name__
        self.logger = logging.getLogger(self.name)

    async def check_authorization(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Check if user is authorized to use the bot.

        Returns True if authorized, False otherwise.
        Sends an error message if not authorized.
        """
        from config import is_authorized_user

        user = update.effective_user
        if not user:
            return False

        if not is_authorized_user(user.id):
            await self.send_error(
                update, context, "⛔️ شما دسترسی ندارید.", show_alert=True
            )
            return False

        return True

    async def send_error(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        show_alert: bool = False,
        reply_markup=None,
    ):
        """Send an error message to the user."""
        from ui import render

        try:
            if update.callback_query:
                await update.callback_query.answer(message, show_alert=show_alert)
            elif update.effective_message:
                await render(update, message, reply_markup=reply_markup)
        except Exception as e:
            self.logger.error("Error sending error message: %s", e)

    async def handle_exception(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        exception: Exception,
        fallback_message: str = "⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
    ):
        """Handle exceptions gracefully."""
        self.logger.error("Exception in %s: %s", self.name, exception, exc_info=True)

        if isinstance(exception, (BadRequest, Forbidden)):
            self.logger.debug("Ignorable error: %s", exception)
            return

        await self.send_error(update, context, fallback_message)

    @abstractmethod
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the update. Must be implemented by subclasses."""


class CallbackHandler(BaseHandler):
    """Base class for callback query handlers.

    Provides common functionality for handling inline button clicks.
    """

    def __init__(self, callback_prefix: str, name: str = None):
        super().__init__(name)
        self.callback_prefix = callback_prefix

    def matches(self, callback_data: str) -> bool:
        """Check if this handler should process the callback."""
        return callback_data.startswith(self.callback_prefix)

    def extract_suffix(self, callback_data: str) -> str:
        """Extract the suffix from callback data after the prefix."""
        return callback_data[len(self.callback_prefix) :]

    async def handle(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, suffix: str = None
    ):
        """Handle callback with optional suffix.

        Subclasses can override handle_with_suffix instead.
        """
        query = update.callback_query

        if not await self.check_authorization(update, context):
            return

        # Rate limiting check
        from middleware.rate_limiter import rate_limiter

        if not rate_limiter.is_allowed(query.from_user.id):
            await self.send_error(
                update, context, "⏳ لطفاً کمی صبر کنید.", show_alert=True
            )
            return

        try:
            if suffix is not None:
                await self.handle_with_suffix(query, context, suffix)
            else:
                await self.handle_callback(query, context)
        except Exception as e:
            await self.handle_exception(update, context, e)

    async def handle_callback(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback without suffix. Override in subclass."""

    async def handle_with_suffix(
        self, query, context: ContextTypes.DEFAULT_TYPE, suffix: str
    ):
        """Handle callback with suffix. Override in subclass."""


class SessionMixin:
    """Mixin for session management helpers."""

    def get_session_data(
        self, context: ContextTypes.DEFAULT_TYPE, key: str, default: Any = None
    ) -> Any:
        """Get session data safely."""
        return context.user_data.get(key, default)

    def set_session_data(
        self, context: ContextTypes.DEFAULT_TYPE, key: str, value: Any
    ):
        """Set session data."""
        context.user_data[key] = value

    def clear_session_key(self, context: ContextTypes.DEFAULT_TYPE, key: str):
        """Remove a key from session data."""
        context.user_data.pop(key, None)

    def has_session_key(self, context: ContextTypes.DEFAULT_TYPE, key: str) -> bool:
        """Check if a key exists in session data."""
        return key in context.user_data


# Import here to avoid circular imports
from telegram.error import BadRequest, Forbidden
