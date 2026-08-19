"""Centralized wrong-option generation for all quiz types."""

import random
from typing import Callable, List, Optional

from models import Word


def sample_unique(primary: List[str], secondary: List[str], count: int) -> List[str]:
    """Sample unique non-empty strings from primary then secondary lists."""
    random.shuffle(primary)
    random.shuffle(secondary)
    result: List[str] = []
    for item in primary + secondary:
        item = str(item or "").strip()
        if item and item not in result:
            result.append(item)
        if len(result) == count:
            break
    return result


def get_wrong_options(
    db,
    word: Word,
    count: int,
    attr_getter: Callable[[Word], Optional[str]],
) -> List[str]:
    """Generate wrong options for a quiz question based on a word attribute.

    Prioritizes same word-type words, then falls back to others.
    """
    target_val = attr_getter(word)

    same_type_words: List[Word] = []
    if word.word_type:
        same_type_words = db.words.get_by_type(word.word_type, exclude_id=word.id, limit=50
        )

    other_words = db.words.get_by_type(None, exclude_id=word.id, limit=50)

    same_type = [
        attr_getter(w)
        for w in same_type_words
        if attr_getter(w) and attr_getter(w) != target_val
    ]

    other = [
        attr_getter(w)
        for w in other_words
        if attr_getter(w)
        and attr_getter(w) != target_val
        and (not word.word_type or w.word_type != word.word_type)
    ]

    return sample_unique(same_type, other, count)


def make_options(
    correct: str,
    wrongs: List[str],
    total: int = 4,
    min_options: int = 2,
) -> Optional[List[str]]:
    """Build a shuffled options list. Returns None if not enough options."""
    correct = str(correct or "").strip()
    if not correct:
        return None

    options = [correct]
    for wrong in wrongs or []:
        wrong = str(wrong or "").strip()
        if not wrong or wrong in options:
            continue
        options.append(wrong)
        if len(options) == total:
            break

    if len(options) < min_options:
        return None

    random.shuffle(options)
    return options
