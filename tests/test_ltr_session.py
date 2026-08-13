"""Unit tests for current LTRSessionManager implementation."""

from unittest.mock import Mock

from handlers.learning.ltr_session import LTRSessionManager
from models import Word


def make_context():
    context = Mock()
    context.user_data = {}
    return context


def make_word(word_id: int) -> Word:
    return Word(
        id=word_id,
        german=f"wort{word_id}",
        persian=f"معنی {word_id}",
        article="der",
        word_type="Noun",
    )


def test_initialize_session():
    context = make_context()
    ltr = LTRSessionManager(context)

    ok = ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[make_word(1)],
        new_words=[make_word(2)],
    )

    assert ok is True
    assert context.user_data["ltr_user_id"] == 1
    assert context.user_data["ltr_lesson_id"] == 2
    assert context.user_data["ltr_words"] == [1, 2]
    assert context.user_data["ltr_learn_index"] == 0
    assert context.user_data["ltr_words_learned"] == []
    assert context.user_data["ltr_delayed_tasks"] == []


def test_initialize_no_words():
    context = make_context()
    ltr = LTRSessionManager(context)

    ok = ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[],
        new_words=[],
    )

    assert ok is False


def test_mark_word_learned_schedules_test():
    context = make_context()
    ltr = LTRSessionManager(context)
    ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[make_word(1)],
        new_words=[make_word(2)],
    )
    ltr.mark_word_learned(1)
    assert 1 in context.user_data["ltr_words_learned"]
    assert context.user_data["ltr_learn_index"] == 1
    tasks = context.user_data["ltr_delayed_tasks"]
    assert len(tasks) == 1
    assert tasks[0]["word_id"] == 1
    
    # ✅ Dynamic: due_after رو از خود task می‌گیریم
    due_after = tasks[0]["due_after"]
    
    # Still not due because learned count < due_after
    assert ltr.get_due_test() is None
    
    # Add enough words to make the task due
    current_count = len(context.user_data["ltr_words_learned"])
    needed = due_after - current_count
    for i in range(needed):
        context.user_data["ltr_words_learned"].append(100 + i)
    
    task = ltr.get_due_test()
    assert task is not None
    assert task["word_id"] == 1

def test_record_correct_result():
    context = make_context()
    ltr = LTRSessionManager(context)

    ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[make_word(1)],
        new_words=[],
    )

    ltr.record_test_result(1, True)

    assert 1 in context.user_data["ltr_words_passed"]
    assert 1 in context.user_data["ltr_words_tested"]
    assert context.user_data["ltr_word_results"][1] == [True]


def test_record_wrong_result_schedules_retry():
    context = make_context()
    ltr = LTRSessionManager(context)

    ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[make_word(1)],
        new_words=[],
    )

    ltr.record_test_result(1, False)

    assert context.user_data["ltr_word_results"][1] == [False]
    assert context.user_data["ltr_word_retry_count"][1] == 1

    tasks = context.user_data["ltr_delayed_tasks"]
    assert any(task["word_id"] == 1 for task in tasks)

def test_max_retries_mark_word_failed():
    from handlers.learning.ltr_session import MAX_RETRIES
    
    context = make_context()
    ltr = LTRSessionManager(context)
    ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[make_word(1)],
        new_words=[],
    )
    # ✅ Dynamic: به جای عدد 2، از MAX_RETRIES استفاده می‌کنیم
    context.user_data["ltr_word_retry_count"][1] = MAX_RETRIES
    ltr.record_test_result(1, False)
    assert 1 in context.user_data["ltr_words_failed"]
    assert 1 not in context.user_data["ltr_words_passed"]

def test_clear_session():
    context = make_context()
    ltr = LTRSessionManager(context)

    ltr.initialize(
        user_id=1,
        lesson_id=2,
        weak_words=[make_word(1)],
        new_words=[],
    )

    context.user_data["ltr_current_options"] = ["a", "b"]
    context.user_data["ltr_current_correct_index"] = 0

    ltr.clear_session()

    assert "ltr_user_id" not in context.user_data
    assert "ltr_words" not in context.user_data
    assert "ltr_current_options" not in context.user_data
    assert "ltr_current_correct_index" not in context.user_data
