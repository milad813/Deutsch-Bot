"""Utility functions and helpers."""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set


@dataclass
class SessionData:
    """Type-safe session data management."""
    
    # Quiz session
    current_quiz: Optional[Dict] = None
    quiz_session: Optional[Dict] = None
    quiz_type: str = "meaning"
    quiz_lesson_id: Optional[int] = None
    quiz_source_filter: Optional[str] = None
    quiz_lesson_preset: bool = False
    
    # Flashcard session
    current_flashcard: Optional[Dict] = None
    flashcard_queue: list = field(default_factory=list)
    learning_session: Optional[Dict] = None
    active_lesson_id: Optional[int] = None
    flashcard_only_new: bool = False
    flashcard_only_due: bool = False
    flashcard_hard_only: bool = False
    flashcard_skipped_ids: set = field(default_factory=set)
    
    # TTS
    current_tts_text: Optional[str] = None
    tts_message: Optional[tuple] = None
    
    # Study session
    study_words: list = field(default_factory=list)
    study_index: int = 0
    study_lesson_id: Optional[int] = None
    
    # LTR (Learn Then Review)
    ltr_words: list = field(default_factory=list)
    ltr_index: int = 0
    ltr_lesson_id: Optional[int] = None
    ltr_word_results: dict = field(default_factory=dict)
    ltr_current_word_id: Optional[int] = None
    ltr_state: Optional[str] = None
    ltr_correct_answer: Optional[str] = None
    ltr_correct_index: Optional[int] = None
    ltr_delayed_1: Optional[Any] = None
    ltr_delayed_2: Optional[Any] = None
    ltr_round: int = 0
    ltr_main_index: int = 0
    ltr_main_progress: list = field(default_factory=list)
    ltr_delayed_tasks: dict = field(default_factory=dict)
    ltr_retry_stage: Optional[str] = None
    ltr_current_word_pos: int = 0
    ltr_round2_started: bool = False
    
    # Grammar
    grammar_current: Optional[Dict] = None
    
    # Story
    current_story_id: Optional[int] = None
    story_quiz: Optional[Dict] = None
    
    # Flags
    fsrs_guide_shown: bool = False
    ltr_answer_lock: bool = False
    flashcard_rate_lock: bool = False
    
    # Conversation history for LLM
    conversation_history: list = field(default_factory=list)
    
    # Wrong words for retry
    quiz_wrong_word_ids: list = field(default_factory=list)
    quiz_fixed_word_ids: list = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            k: v for k, v in self.__dict__.items() 
            if v is not None and not k.startswith('_')
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionData':
        """Create from dictionary."""
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
    
    def clear_quiz_session(self) -> None:
        """Clear quiz-related session data."""
        self.current_quiz = None
        self.quiz_session = None
        self.quiz_type = "meaning"
        self.quiz_lesson_id = None
        self.quiz_source_filter = None
        self.quiz_lesson_preset = False
        self.quiz_wrong_word_ids = []
        self.quiz_fixed_word_ids = []
    
    def clear_flashcard_session(self) -> None:
        """Clear flashcard-related session data."""
        self.current_flashcard = None
        self.flashcard_queue = []
        self.learning_session = None
        self.flashcard_skipped_ids = set()
    
    def clear_ltr_session(self) -> None:
        """Clear LTR session data."""
        self.ltr_words = []
        self.ltr_index = 0
        self.ltr_lesson_id = None
        self.ltr_word_results = {}
        self.ltr_current_word_id = None
        self.ltr_state = None
        self.ltr_correct_answer = None
        self.ltr_correct_index = None
        self.ltr_delayed_1 = None
        self.ltr_delayed_2 = None
        self.ltr_round = 0
        self.ltr_main_index = 0
        self.ltr_main_progress = []
        self.ltr_delayed_tasks = {}
        self.ltr_retry_stage = None
        self.ltr_current_word_pos = 0
        self.ltr_round2_started = False
