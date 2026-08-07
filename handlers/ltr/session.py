"""Look-Test-Review (LTR) session management."""

import logging
from typing import TYPE_CHECKING, Optional, List
from enum import Enum

if TYPE_CHECKING:
    from telegram import Update, CallbackQuery
    from telegram.ext import CallbackContext

from services import db
from models import Word
import config

logger = logging.getLogger(__name__)


class LTRStage(Enum):
    """Stages in the Look-Test-Review method."""
    LOOK = "look"      # Study phase
    TEST = "test"      # Self-test phase
    REVIEW = "review"  # Review mistakes


class LTRSessionManager:
    """Manages Look-Test-Review learning sessions."""
    
    def __init__(self):
        self.sessions: dict[int, dict] = {}
        
    def create_session(
        self,
        user_id: int,
        lesson_id: int,
        word_ids: Optional[List[int]] = None,
    ) -> List[Word]:
        """Create a new LTR session for a user."""
        # Get words for the lesson
        if word_ids:
            words = [db.get_word_by_id(wid) for wid in word_ids if db.get_word_by_id(wid)]
        else:
            words = db.get_words_by_lesson(lesson_id)
            
        if not words:
            return []
            
        # Store session state
        self.sessions[user_id] = {
            "lesson_id": lesson_id,
            "stage": LTRStage.LOOK,
            "words": words,
            "current_index": 0,
            "mistakes": [],
            "studied_count": 0,
        }
        
        logger.info(
            "Created LTR session for user %d with %d words",
            user_id, len(words)
        )
        
        return words
        
    def get_session(self, user_id: int) -> Optional[dict]:
        """Get session data for a user."""
        return self.sessions.get(user_id)
        
    def advance_stage(self, user_id: int) -> Optional[LTRStage]:
        """Advance to next stage in LTR cycle."""
        session = self.sessions.get(user_id)
        if not session:
            return None
            
        current_stage = session["stage"]
        
        if current_stage == LTRStage.LOOK:
            session["stage"] = LTRStage.TEST
        elif current_stage == LTRStage.TEST:
            if session["mistakes"]:
                session["stage"] = LTRStage.REVIEW
            else:
                # No mistakes, session complete
                self.end_session(user_id)
                return None
        elif current_stage == LTRStage.REVIEW:
            self.end_session(user_id)
            return None
            
        return session["stage"]
        
    def record_mistake(self, user_id: int, word: Word) -> None:
        """Record a word as mistaken during test phase."""
        session = self.sessions.get(user_id)
        if session and session["stage"] == LTRStage.TEST:
            session["mistakes"].append(word)
            
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
            # End of word list, advance stage
            self.advance_stage(user_id)
            return None
            
        return session["words"][session["current_index"]]
        
    def is_session_complete(self, user_id: int) -> bool:
        """Check if session is complete."""
        session = self.sessions.get(user_id)
        return not session
        
    def end_session(self, user_id: int) -> None:
        """End the current session."""
        if user_id in self.sessions:
            stats = self.sessions[user_id]
            logger.info(
                "Ended LTR session for user %d: studied=%d, mistakes=%d",
                user_id,
                stats.get("studied_count", 0),
                len(stats.get("mistakes", []))
            )
            del self.sessions[user_id]


# Global instance
ltr_session_manager = LTRSessionManager()
