from dataclasses import dataclass
from typing import Optional

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
            "german", "persian", "article", "word_type", "example_de", "example_fa",
            "english_meaning", "plural_form", "verb_forms", "comparative",
            "collocation_de", "collocation_fa",
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