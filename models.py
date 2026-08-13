from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class QuizType(str, Enum):
    """Types of quiz questions."""

    ARTICLE = "article"
    MEANING = "meaning"
    PLURAL = "plural"
    VERB = "verb"
    ADJECTIVE = "adjective"
    COLLOCATION = "collocation"


class CallbackPrefix(str, Enum):
    """Callback data prefixes for routing."""

    QUIZ_TYPE = "quiz_type:"
    QUIZ_SOURCE = "quiz_source:"
    QUIZ_COUNT = "quiz_count:"
    QUIZ_BOOK = "quiz_book:"
    QUIZ_LESSON = "quiz_lesson:"
    QUIZ_ANS = "quiz_ans:"
    QUIZ_FROM_LESSON = "quiz_from_lesson:"
    FLASHCARD_LESSON = "flashcard_lesson:"
    STUDY_LESSON = "study_lesson:"
    FLIP_CARD = "flip_card:"
    SKIP_FLASHCARD = "skip_flashcard:"
    RATE_CARD = "rate_card:"
    SPEAK_CURRENT = "speak_current:"
    LESSON_WORDS = "lesson_words_"
    BOOK = "book_"
    LESSON = "lesson_"
    LTR_ANS = "ltr_ans:"
    GRAMMAR_LESSON = "grammar_lesson:"
    GRAMMAR_POINT = "grammar_point:"
    GRAMMAR_QUIZ = "grammar_quiz:"
    GRAMMAR_ANS = "grammar_ans:"
    STORY_LESSON = "story_lesson:"
    STORY_VIEW = "story_view:"
    STORY_FA = "story_fa:"
    STORY_WORDS = "story_words:"
    STORY_AUDIO = "story_audio:"
    STORY_HINT = "story_hint:"
    STORY_LISTEN_READ = "story_listen_read:"
    STORY_LISTEN_ONLY = "story_listen_only:"
    STORY_REPLAY = "story_replay:"
    STORY_QUIZ = "story_quiz:"
    STORY_ANS = "story_ans:"
    STORY_NEXT = "story_next:"
    STORY_NEXT_Q = "story_next_q:"
    SET_LEVEL = "set_level:"
    SET_GOAL = "set_goal:"
    WRITING_START = "writing_start:"
    WRITING_SKIP = "writing_skip:"
    WRITING_EXIT = "writing_exit:"
    LISTENING_START = "listening_start:"
    LISTENING_ANS = "listening_ans:"
    LISTENING_SKIP = "listening_skip:"
    LISTENING_EXIT = "listening_exit:"
    LISTENING_REPLAY = "listening_replay:"


@dataclass
class Word:
    id: int
    german: str
    persian: str
    article: Optional[str] = None
    word_type: Optional[str] = None
    example_de: Optional[str] = None
    example_fa: Optional[str] = None
    english_meaning: Optional[str] = None
    plural_form: Optional[str] = None
    verb_forms: Optional[str] = None
    comparative: Optional[str] = None
    collocation_de: Optional[str] = None
    collocation_fa: Optional[str] = None

    def __post_init__(self):
        def _clean(value):
            if value is None:
                return None
            text = " ".join(str(value).split())
            return text or None

        for field_name in (
            "german",
            "persian",
            "article",
            "word_type",
            "example_de",
            "example_fa",
            "english_meaning",
            "plural_form",
            "verb_forms",
            "comparative",
            "collocation_de",
            "collocation_fa",
        ):
            setattr(self, field_name, _clean(getattr(self, field_name)))

        if self.article:
            self.article = self.article.lower()

    @property
    def display_german(self) -> str:
        if self.article:
            return f"{self.article} {self.german}".strip()
        return self.german

    @property
    def extra_forms_line(self) -> Optional[str]:
        if self.word_type == "Noun" and self.plural_form:
            return f"جمع: {self.plural_form}"
        if self.word_type == "Verb" and self.verb_forms:
            return f"صرف فعل: {self.verb_forms}"
        if self.word_type == "Adjective" and self.comparative:
            return f"تفضیلی/عالی: {self.comparative}"
        return None

    @property
    def collocation_line(self) -> Optional[str]:
        de = (self.collocation_de or "").strip()
        if not de:
            return None
        fa = (self.collocation_fa or "").strip()
        return f"{de} — {fa}" if fa else de


@dataclass
class QuizSession:
    """State for a quiz session."""

    quiz_type: str
    total_questions: int
    current_index: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    question_ids: list = field(default_factory=list)
    source_filter: Optional[str] = None
    lesson_id: Optional[int] = None


@dataclass
class FlashcardSession:
    """State for a flashcard learning session."""

    words: list = field(default_factory=list)
    current_index: int = 0
    skipped_ids: list = field(default_factory=list)
    only_new: bool = False
    only_due: bool = False
    hard_only: bool = False
    lesson_id: Optional[int] = None


@dataclass
class LTRSession:
    """State for Learn-Test-Review (LTR) session."""

    lesson_id: int
    weak_words: list = field(default_factory=list)
    new_words: list = field(default_factory=list)
    main_index: int = 0
    main_progress: dict = field(default_factory=dict)
    delayed_tasks: dict = field(default_factory=dict)
    retry_stage: dict = field(default_factory=dict)
    current_word_pos: Optional[int] = None
    round2_started: bool = False
    state: str = "intro"
    correct_answer: Optional[str] = None


@dataclass
class StorySession:
    """State for story learning session."""

    story_id: int
    hint_level: int = 0
    genre_history: list = field(default_factory=list)
    quiz_mode: bool = False
    word_ids: list = field(default_factory=list)


@dataclass
class GrammarSession:
    """State for grammar learning session."""

    grammar_point_id: int
    current_question_index: int = 0
    correct_count: int = 0
    wrong_count: int = 0


@dataclass
class ListeningSession:
    """State for listening exercise session."""

    word_id: int
    attempts: int = 0
    max_attempts: int = 3


@dataclass
class WritingSession:
    """State for writing exercise session."""

    prompt: str
    examples: list = field(default_factory=list)


@dataclass
class UserSession:
    """Container for all user session state."""

    quiz: Optional[QuizSession] = None
    flashcard: Optional[FlashcardSession] = None
    ltr: Optional[LTRSession] = None
    story: Optional[StorySession] = None
    grammar: Optional[GrammarSession] = None
    listening: Optional[ListeningSession] = None
    writing: Optional[WritingSession] = None

    # Additional state
    conversation_history: list = field(default_factory=list)
    active_lesson_id: Optional[int] = None
    current_tts_text: Optional[str] = None
    tts_message: tuple = None  # (chat_id, message_id)
    tts_delete_job: object = None
    awaiting_state: Optional[str] = None

    # FSRS guide shown flag
    fsrs_guide_shown: bool = False

    def clear(self):
        """Clear all session state."""
        self.quiz = None
        self.flashcard = None
        self.ltr = None
        self.story = None
        self.grammar = None
        self.listening = None
        self.writing = None
        self.conversation_history.clear()
        self.active_lesson_id = None
        self.current_tts_text = None
        self.tts_message = None
        self.awaiting_state = None
        self.fsrs_guide_shown = False
