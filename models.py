from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class QuizType(str, Enum):
    """Types of quiz questions."""

    ARTICLE = "article"
    MEANING = "meaning"


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
