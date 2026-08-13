import random
import re
from typing import Dict, List, Optional, Tuple

from ui import esc

ARTICLES = ("der", "die", "das")
SEPARABLE_PREFIXES = {
    "ab",
    "an",
    "auf",
    "aus",
    "bei",
    "ein",
    "mit",
    "nach",
    "vor",
    "zu",
    "zurück",
}


class QuizService:

    @staticmethod
    def extract_article_and_noun(german_word: str) -> Tuple[Optional[str], str]:
        german_word = (german_word or "").strip()
        for article in ARTICLES:
            if german_word.lower().startswith(article + " "):
                return article, german_word[len(article) :].strip()
        return None, german_word

    @staticmethod
    def _inflection_pattern(candidate: str):
        candidate = str(candidate or "").strip()
        if not candidate:
            return None

        if len(candidate) <= 2:
            return re.compile(
                r"\b" + re.escape(candidate) + r"\b",
                re.IGNORECASE,
            )

        return re.compile(
            r"\b" + re.escape(candidate) + r"[a-zäöüß]*\b",
            re.IGNORECASE,
        )

    @staticmethod
    def _search_candidates(
        correct_word: str,
        noun: str,
        article: Optional[str] = None,
        word_type: Optional[str] = None,
    ) -> List[str]:
        candidates: List[str] = []

        def add(value: Optional[str]):
            value = str(value or "").strip()
            if not value:
                return
            if value not in candidates:
                candidates.append(value)

        correct_word = str(correct_word or "").strip()
        noun = str(noun or "").strip()
        article = str(article or "").strip().lower()
        word_type = str(word_type or "").strip()

        add(correct_word)

        if article and noun:
            add(f"{article} {noun}")

        if noun:
            add(noun)

        parts = correct_word.split()

        if len(parts) > 1:
            without_reflexive = " ".join(
                p for p in parts if p.lower() not in {"sich", "zu"}
            )
            add(without_reflexive)
            add(parts[-1])

        base = parts[0] if parts else correct_word

        if word_type.lower() == "verb" and base:
            stem = base

            if stem.endswith("ern") and len(stem) > 4:
                stem = stem[:-2]
            elif stem.endswith("eln") and len(stem) > 4:
                stem = stem[:-2]
            elif stem.endswith("en") and len(stem) > 3:
                stem = stem[:-2]

            if len(stem) >= 3:
                add(stem)

            for prefix in SEPARABLE_PREFIXES:
                if stem.startswith(prefix) and len(stem) > len(prefix) + 2:
                    rest = stem[len(prefix) :]

                    if len(rest) >= 3:
                        add(rest)

                    if rest.endswith("en") and len(rest) > 3:
                        add(rest[:-2])

        return candidates

    @staticmethod
    def _unique_options(
        correct: str, wrong_options: List[str], total: int = 4
    ) -> Optional[List[str]]:
        correct = str(correct or "").strip()
        if not correct:
            return None

        options = [correct]

        for wrong in wrong_options or []:
            wrong = str(wrong or "").strip()
            if not wrong:
                continue
            if wrong == correct:
                continue
            if wrong in options:
                continue

            options.append(wrong)
            if len(options) == total:
                break

        if len(options) < total:
            return None

        random.shuffle(options)
        return options

    @staticmethod
    def create_article_quiz(
        article: str, german_word: str, persian_meaning: str
    ) -> Optional[Dict]:
        if not article or article.lower() not in ARTICLES:
            return None

        article_lower = article.lower()
        _, noun = QuizService.extract_article_and_noun(german_word)

        options = list(ARTICLES)
        random.shuffle(options)

        question = (
            "🎯 آرتیکل صحیح کلمه‌ی زیر چیست؟\n"
            f"🇩🇪 ______ {esc(noun)}\n"
            f"🇮🇷 {esc(persian_meaning)}"
        )

        return {
            "type": "article",
            "question": question,
            "options": options,
            "correct_index": options.index(article_lower),
            "correct_answer": article_lower,
        }

    @staticmethod
    def create_meaning_quiz(
        german_word: str, persian_meaning: str, wrong_options: List[str]
    ) -> Optional[Dict]:
        correct = str(persian_meaning or "").strip()
        options = QuizService._unique_options(correct, wrong_options, total=4)
        if not options:
            return None

        question = "🧠 معنی کلمه‌ی زیر چیست؟\n" f"🇩🇪 <b>{esc(german_word)}</b>"

        return {
            "type": "meaning",
            "question": question,
            "options": options,
            "correct_index": options.index(correct),
            "correct_answer": correct,
        }

    @staticmethod
    def create_reverse_quiz(
        persian_meaning: str, correct_german: str, wrong_options: List[str]
    ) -> Optional[Dict]:
        correct = str(correct_german or "").strip()
        options = QuizService._unique_options(correct, wrong_options, total=4)
        if not options:
            return None

        question = (
            "🔄 معادل آلمانی کلمه‌ی زیر چیست؟\n" f"🇮🇷 <b>{esc(persian_meaning)}</b>"
        )

        return {
            "type": "reverse",
            "question": question,
            "options": options,
            "correct_index": options.index(correct),
            "correct_answer": correct,
        }

    @staticmethod
    def _find_word_in_sentence(word: str, sentence: str):
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        return pattern.search(sentence)

    @staticmethod
    def create_cloze_quiz(
        german_word: str,
        persian_meaning: str,
        example_german: str,
        article: Optional[str] = None,
        word_type: Optional[str] = None,
    ) -> Optional[Dict]:
        if not example_german:
            return None

        sentence = example_german.strip()

        extracted_article, noun = QuizService.extract_article_and_noun(german_word)
        article = article or extracted_article

        candidates = QuizService._search_candidates(
            german_word,
            noun,
            article=article,
            word_type=word_type,
        )

        best_match = None
        best_candidate = None
        best_score = -1

        for candidate in candidates:
            pattern = QuizService._inflection_pattern(candidate)
            if not pattern:
                continue

            match = pattern.search(sentence)
            if not match:
                continue

            matched_text = match.group(0)

            if len(matched_text) <= 2:
                continue

            score = len(matched_text)

            if " " in candidate:
                score += 3

            if matched_text.lower() == candidate.lower():
                score += 2

            if matched_text.lower() == german_word.lower():
                score += 1

            if score > best_score:
                best_score = score
                best_match = match
                best_candidate = candidate

        if not best_match or not best_candidate:
            return None

        sentence_with_blank = (
            sentence[: best_match.start()] + "______" + sentence[best_match.end() :]
        )

        question = (
            "📝 کلمه‌ی مناسب برای جای خالی چیست؟\n"
            f"🇩🇪 {esc(sentence_with_blank)}\n"
            f"🇮🇷 {esc(persian_meaning)}"
        )

        return {
            "type": "cloze",
            "question": question,
            "correct_answer": best_match.group(0),
            "matched_candidate": best_candidate,
        }

    @staticmethod
    def create_cloze_with_options(
        correct_word: str,
        persian_meaning: str,
        example_german: str,
        wrong_options: List[str],
        article: Optional[str] = None,
        word_type: Optional[str] = None,
    ) -> Optional[Dict]:
        cloze = QuizService.create_cloze_quiz(
            correct_word,
            persian_meaning,
            example_german,
            article=article,
            word_type=word_type,
        )

        if not cloze:
            return None

        answer = cloze["correct_answer"]

        cleaned_wrongs = []

        for w in wrong_options or []:
            w = str(w or "").strip()
            if not w:
                continue

            if w.lower() == answer.lower():
                continue

            if w.lower() == str(correct_word or "").strip().lower():
                continue

            cleaned_wrongs.append(w)

        options = QuizService._unique_options(answer, cleaned_wrongs, total=4)

        if not options:
            return None

        cloze["options"] = options
        cloze["correct_index"] = options.index(answer)
        cloze["correct_answer"] = answer

        return cloze
