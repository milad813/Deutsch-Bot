"""Pure domain models (no I/O, no framework imports).

Phase R3: the dataclasses and enums that describe the learning domain live
here. ``CallbackPrefix`` is a Telegram routing concern and lives in
``core.callbacks``; the root ``models.py`` shim re-exports everything so
existing ``from models import Word`` call sites keep working.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class QuizType(str, Enum):
    """Types of quiz questions."""

    ARTICLE = "article"
    MEANING = "meaning"


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
