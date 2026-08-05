import random
import re
from typing import Dict, List, Optional, Tuple

from ui import esc

ARTICLES = ("der", "die", "das")


class QuizService:

    @staticmethod
    def extract_article_and_noun(german_word: str) -> Tuple[Optional[str], str]:
        german_word = (german_word or "").strip()
        for article in ARTICLES:
            if german_word.lower().startswith(article + " "):
                return article, german_word[len(article):].strip()
        return None, german_word

    @staticmethod
    def _unique_options(correct: str, wrong_options: List[str], total: int = 4) -> Optional[List[str]]:
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
    def create_article_quiz(article: str, german_word: str, persian_meaning: str) -> Optional[Dict]:
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
    def create_meaning_quiz(german_word: str, persian_meaning: str, wrong_options: List[str]) -> Optional[Dict]:
        correct = str(persian_meaning or "").strip()
        options = QuizService._unique_options(correct, wrong_options, total=4)
        if not options:
            return None

        question = (
            "🧠 معنی کلمه‌ی زیر چیست؟\n"
            f"🇩🇪 <b>{esc(german_word)}</b>"
        )

        return {
            "type": "meaning",
            "question": question,
            "options": options,
            "correct_index": options.index(correct),
            "correct_answer": correct,
        }

    @staticmethod
    def create_reverse_quiz(persian_meaning: str, correct_german: str, wrong_options: List[str]) -> Optional[Dict]:
        correct = str(correct_german or "").strip()
        options = QuizService._unique_options(correct, wrong_options, total=4)
        if not options:
            return None

        question = (
            "🔄 معادل آلمانی کلمه‌ی زیر چیست؟\n"
            f"🇮🇷 <b>{esc(persian_meaning)}</b>"
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
    def _search_candidates(german_word: str, noun: str) -> List[str]:
        candidates: List[str] = []
        for item in (german_word, noun):
            item = (item or "").strip()
            if not item:
                continue
            if item not in candidates:
                candidates.append(item)
            parts = item.split()
            if len(parts) > 1:
                # حذف sich/zu
                without_reflexive = " ".join(p for p in parts if p.lower() not in {"sich", "zu"})
                if without_reflexive and without_reflexive not in candidates:
                    candidates.append(without_reflexive)
                # اضافه کردن آخرین کلمه (برای separable verbs)
                if parts[-1] and parts[-1] not in candidates:
                    candidates.append(parts[-1])
        return candidates


    @staticmethod
    def create_cloze_quiz(german_word: str, persian_meaning: str, example_german: str) -> Optional[Dict]:
        if not example_german:
            return None

        sentence = example_german.strip()
        _, noun = QuizService.extract_article_and_noun(german_word)

        match = None
        answer = None

        for candidate in QuizService._search_candidates(german_word, noun):
            match = QuizService._find_word_in_sentence(candidate, sentence)
            if match:
                answer = candidate
                break

        if not match or not answer:
            return None

        sentence_with_blank = sentence[:match.start()] + "______" + sentence[match.end():]

        question = (
            "📝 کلمه‌ی مناسب برای جای خالی چیست؟\n"
            f"🇩🇪 {esc(sentence_with_blank)}\n"
            f"🇮🇷 {esc(persian_meaning)}"
        )

        return {
            "type": "cloze",
            "question": question,
            "correct_answer": answer,
        }

    @staticmethod
    def create_cloze_with_options(
        correct_word: str,
        persian_meaning: str,
        example_german: str,
        wrong_options: List[str],
    ) -> Optional[Dict]:
        cloze = QuizService.create_cloze_quiz(correct_word, persian_meaning, example_german)
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