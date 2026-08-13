"""Unit tests for quiz_service."""
from quiz_service import QuizService


def test_article_quiz():
    quiz = QuizService.create_article_quiz("das", "Haus", "خانه")

    assert quiz is not None
    assert quiz["type"] == "article"
    assert quiz["correct_answer"] == "das"
    assert len(quiz["options"]) == 3


def test_meaning_quiz():
    quiz = QuizService.create_meaning_quiz(
        "Haus",
        "خانه",
        ["کتاب", "میز", "در"],
    )

    assert quiz is not None
    assert quiz["type"] == "meaning"
    assert quiz["correct_answer"] == "خانه"
    assert len(quiz["options"]) == 4
    assert "خانه" in quiz["options"]


def test_cloze_quiz_exact_match():
    quiz = QuizService.create_cloze_quiz(
        "Haus",
        "خانه",
        "Das Haus ist groß.",
    )

    assert quiz is not None
    assert quiz["type"] == "cloze"
    assert quiz["correct_answer"].lower() == "haus"
    assert "______" in quiz["question"]