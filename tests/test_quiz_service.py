"""Characterization tests for quiz_service (question generation)."""

from quiz_service import QuizService


def test_extract_article_and_noun():
    assert QuizService.extract_article_and_noun("der Hund") == ("der", "Hund")
    assert QuizService.extract_article_and_noun("das Fenster") == ("das", "Fenster")
    assert QuizService.extract_article_and_noun("Haus") == (None, "Haus")
    assert QuizService.extract_article_and_noun("") == (None, "")
    # article must be matched as a whole word, not a prefix
    assert QuizService.extract_article_and_noun("dieb") == (None, "dieb")


def test_create_meaning_quiz_contains_correct_answer():
    q = QuizService.create_meaning_quiz(
        "der Hund", "سگ", ["گربه", "پرنده", "ماهی"]
    )
    assert q is not None
    assert q["type"] == "meaning"
    opts = q["options"]
    assert len(opts) == 4
    assert opts[q["correct_index"]] == "سگ"
    assert len(set(opts)) == 4  # no duplicates


def test_create_meaning_quiz_handles_insufficient_wrongs():
    q = QuizService.create_meaning_quiz("der Hund", "سگ", [])
    if q is not None:  # falls back to fewer options or None — both valid
        assert q["options"][q["correct_index"]] == "سگ"


def test_create_reverse_quiz():
    # production always supplies count=3 wrongs; _unique_options demands 4 total
    q = QuizService.create_reverse_quiz("سگ", "Hund", ["Katze", "Vogel", "Fisch"])
    assert q is not None
    assert "Hund" in q["options"]
    assert q["options"][q["correct_index"]] == "Hund"


def test_create_reverse_quiz_needs_enough_wrongs():
    assert QuizService.create_reverse_quiz("سگ", "Hund", ["Katze"]) is None


def test_create_article_quiz():
    q = QuizService.create_article_quiz("der", "Hund", "سگ")
    assert q is not None
    assert set(q["options"]) == {"der", "die", "das"}
    assert q["correct_answer"] == "der"
    assert q["options"][q["correct_index"]] == "der"


def test_create_cloze_quiz_blanks_the_word():
    q = QuizService.create_cloze_quiz(
        "Haus", "خانه", "Ich wohne in einem kleinen Haus.", word_type="Noun"
    )
    assert q is not None
    assert "______" in q["question"]
    assert q["correct_answer"] == "Haus"
    assert "Haus" not in q["question"]


def test_create_cloze_with_options_is_consistent():
    q = QuizService.create_cloze_with_options(
        "Haus",
        "خانه",
        "Ich wohne in einem kleinen Haus.",
        ["Wohnung", "Garten", "Stadt"],
        word_type="Noun",
    )
    assert q is not None
    opts = q["options"]
    answer = opts[q["correct_index"]]
    assert answer == q["correct_answer"]
    assert len(opts) == 4
