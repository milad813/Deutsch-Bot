"""Deep study session management."""

import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from telegram import Update, CallbackQuery
    from telegram.ext import CallbackContext

from services import db
from models import Word

logger = logging.getLogger(__name__)


class StudySessionManager:
    """Manages deep study sessions with detailed word information."""
    
    def __init__(self):
        self.sessions: dict[int, dict] = {}
        
    def create_session(
        self,
        user_id: int,
        lesson_id: int,
        word_ids: Optional[List[int]] = None,
    ) -> List[Word]:
        """Create a new study session for a user."""
        if word_ids:
            words = [db.get_word_by_id(wid) for wid in word_ids if db.get_word_by_id(wid)]
        else:
            words = db.get_words_by_lesson(lesson_id)
            
        if not words:
            return []
            
        self.sessions[user_id] = {
            "lesson_id": lesson_id,
            "words": words,
            "current_index": 0,
            "studied_count": 0,
        }
        
        logger.info(
            "Created study session for user %d with %d words",
            user_id, len(words)
        )
        
        return words
        
    def get_session(self, user_id: int) -> Optional[dict]:
        """Get session data for a user."""
        return self.sessions.get(user_id)
        
    def get_current_word(self, user_id: int) -> Optional[Word]:
        """Get current word in the session."""
        session = self.sessions.get(user_id)
        if not session or session["current_index"] >= len(session["words"]):
            return None
        return session["words"][session["current_index"]]
        
    def next_word(self, user_id: int) -> Optional[Word]:
        """Move to next word and return it."""
        session = self.sessions.get(user_id)
        if not session:
            return None
            
        session["current_index"] += 1
        session["studied_count"] += 1
        
        if session["current_index"] >= len(session["words"]):
            self.end_session(user_id)
            return None
            
        return session["words"][session["current_index"]]
        
    def previous_word(self, user_id: int) -> Optional[Word]:
        """Move to previous word and return it."""
        session = self.sessions.get(user_id)
        if not session:
            return None
            
        if session["current_index"] > 0:
            session["current_index"] -= 1
            return session["words"][session["current_index"]]
            
        return session["words"][0]
        
    def is_session_complete(self, user_id: int) -> bool:
        """Check if session is complete."""
        session = self.sessions.get(user_id)
        return not session
        
    def end_session(self, user_id: int) -> None:
        """End the current session."""
        if user_id in self.sessions:
            stats = self.sessions[user_id]
            logger.info(
                "Ended study session for user %d: studied=%d",
                user_id,
                stats.get("studied_count", 0)
            )
            del self.sessions[user_id]


# Global instance
study_session_manager = StudySessionManager()
