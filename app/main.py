"""Main bot application with authorization middleware."""

import logging
import datetime
from typing import Optional

from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    PicklePersistence,
    Defaults,
    ContextTypes,
)

import app.config as config
from app.database import DatabaseConnection, WordRepository, UserRepository
from app.services import LLMService, FSRSService
from app.utils import SessionData

logger = logging.getLogger(__name__)


class GermanBot:
    """Main bot application class with dependency injection."""

    def __init__(self):
        self.db_conn: Optional[DatabaseConnection] = None
        self.word_repo: Optional[WordRepository] = None
        self.user_repo: Optional[UserRepository] = None
        self.llm: Optional[LLMService] = None
        self.fsrs: Optional[FSRSService] = None
        self.application: Optional[Application] = None

    def initialize(self) -> None:
        """Initialize all dependencies."""
        logger.info("Initializing German Learning Bot...")
        
        # Initialize database
        self.db_conn = DatabaseConnection(config.settings.db_path)
        self.word_repo = WordRepository(self.db_conn)
        self.user_repo = UserRepository(self.db_conn)
        
        # Initialize services
        self.llm = LLMService(db=self.db_conn)
        self.fsrs = FSRSService(word_repository=self.word_repo)
        
        logger.info("Initialization complete")

    async def check_authorization(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Check if user is authorized. Returns True if authorized."""
        user_id = update.effective_user.id if update.effective_user else None
        
        if not config.settings.is_authorized_user(user_id):
            logger.warning("Unauthorized access attempt from user %s", user_id)
            
            if update.callback_query:
                try:
                    await update.callback_query.answer(
                        "⛔️ دسترسی ندارید. لطفاً با ادمین تماس بگیرید.",
                        show_alert=True,
                    )
                except Exception:
                    pass
            elif update.message:
                try:
                    await update.message.reply_text(
                        "⛔️ دسترسی ندارید. لطفاً با ادمین تماس بگیرید."
                    )
                except Exception:
                    pass
            
            return False
        
        return True

    async def on_error(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler."""
        error = context.error
        
        if isinstance(error, (BadRequest, Forbidden)):
            logger.debug("Expected error: %s", error)
            return

        logger.error("Unexpected error processing update", exc_info=error)

        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید یا /menu را بزنید."
                )
            except Exception:
                pass

    async def set_commands(self, application: Application) -> None:
        """Set bot commands."""
        commands = [
            BotCommand("start", "شروع ربات"),
            BotCommand("menu", "منوی اصلی"),
        ]
        await application.bot.set_my_commands(commands)

    async def post_shutdown(self, application: Application) -> None:
        """Cleanup on shutdown."""
        if self.db_conn:
            self.db_conn.close()
            logger.info("Database connection closed")

    async def daily_backup(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Daily backup job."""
        if self.db_conn:
            try:
                backup_path = self.db_conn.backup()
                logger.info("Daily backup created: %s", backup_path)
            except Exception as e:
                logger.error("Daily backup failed: %s", e)

    def setup_handlers(self) -> None:
        """Setup all bot handlers."""
        # Import handlers here to avoid circular imports
        from app.handlers.main import (
            start_command,
            menu_command,
            callback_handler,
            text_handler,
        )
        
        self.application.add_handler(CommandHandler("start", start_command))
        self.application.add_handler(CommandHandler("menu", menu_command))
        self.application.add_handler(CallbackQueryHandler(callback_handler))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
        )
        self.application.add_error_handler(self.on_error)

    def setup_jobs(self) -> None:
        """Setup scheduled jobs."""
        job_queue = self.application.job_queue
        
        if job_queue:
            job_queue.run_daily(
                self.daily_backup,
                time=datetime.time(hour=3, minute=0, tzinfo=datetime.timezone.utc),
                name="daily_backup",
            )
            logger.info("Daily backup job scheduled")

    def run(self) -> None:
        """Run the bot."""
        # Validate configuration
        config.validate_config()
        
        # Initialize dependencies
        self.initialize()
        
        # Setup persistence and defaults
        persistence = PicklePersistence(filepath="bot_persistence.pkl")
        defaults = Defaults(parse_mode=ParseMode.HTML)
        
        # Build application
        self.application = (
            Application.builder()
            .token(config.settings.telegram_bot_token)
            .persistence(persistence)
            .defaults(defaults)
            .post_init(self.set_commands)
            .post_shutdown(self.post_shutdown)
            .build()
        )
        
        # Setup handlers and jobs
        self.setup_handlers()
        self.setup_jobs()
        
        # Start polling
        logger.info("German Learning Bot starting...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Entry point for running the bot."""
    config.setup_logging()
    bot = GermanBot()
    bot.run()


if __name__ == "__main__":
    main()
