"""Unified learning engine for recording answers, skills and mistakes."""

from typing import Optional

from services import db, fsrs


def record_skill(user_id: int, word_id: int, skill_type: str, is_correct: bool) -> None:
    """Record a word skill attempt without affecting SRS directly."""
    if word_id:
        db.learning.record_skill(user_id, word_id, skill_type, is_correct)


def record_mistake(
    user_id: int,
    word_id: Optional[int] = None,
    grammar_point_id: Optional[int] = None,
    story_id: Optional[int] = None,
    skill_type: Optional[str] = None,
    quiz_type: Optional[str] = None,
    user_answer: Optional[str] = None,
    correct_answer: Optional[str] = None,
) -> None:
    """Record mistake."""
    db.learning.record_mistake(
        user_id=user_id,
        word_id=word_id,
        grammar_point_id=grammar_point_id,
        story_id=story_id,
        skill_type=skill_type,
        quiz_type=quiz_type,
        user_answer=user_answer,
        correct_answer=correct_answer,
    )


def record_quiz_answer(
    user_id: int,
    word_id: Optional[int],
    skill_type: str,
    is_correct: bool,
    user_answer: Optional[str] = None,
    correct_answer: Optional[str] = None,
    update_srs: bool = True,
    update_quiz_stats: bool = True,
    xp: Optional[int] = None,
    quiz_type: Optional[str] = None,
    response_time_sec: float = None,  # ← خط جدید
) -> None:
    """Record a normal quiz answer.

    This updates:
    - user quiz stats
    - word skill
    - SRS if requested
    - mistakes if wrong
    - XP/activity if xp is provided
    """
    quiz_type = quiz_type or skill_type

    if update_quiz_stats:
        db.users.update_quiz_stats(user_id, is_correct)

    if word_id:
        db.learning.record_skill(user_id, word_id, skill_type, is_correct)

    if update_srs and word_id:
        # گرفتن تعداد correct متوالی از skill
        skills = db.learning.get_word_skills(user_id, word_id)
        consecutive = 0
        for s in skills:
            if s["skill_type"] == skill_type:
                consecutive = s.get("correct_streak", 0)
                break
        grade = fsrs.grade_from_correctness(is_correct, consecutive, response_time_sec)
        fsrs.review(user_id, word_id, grade)

    if not is_correct:
        db.learning.record_mistake(
            user_id=user_id,
            word_id=word_id,
            skill_type=skill_type,
            quiz_type=quiz_type,
            user_answer=user_answer,
            correct_answer=correct_answer,
        )

    if xp is not None:
        db.users.record_activity(user_id, xp)
