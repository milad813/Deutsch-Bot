"""Unit tests for learning_engine module."""

from unittest.mock import patch


def test_record_quiz_answer_correct():
    """Test recording a correct quiz answer."""
    with patch("learning_engine.db") as mock_db, patch(
        "learning_engine.fsrs"
    ) as mock_fsrs:

        mock_db.learning.get_word_skills.return_value = [
            {
                "skill_type": "meaning",
                "correct": 1,
                "wrong": 0,
                "total": 1,
                "accuracy": 100,
                "correct_streak": 1,
            }
        ]

        mock_fsrs.grade_from_correctness.return_value = 3

        from learning_engine import record_quiz_answer

        record_quiz_answer(
            user_id=1,
            word_id=10,
            skill_type="meaning",
            is_correct=True,
            user_answer="house",
            correct_answer="خانه",
            update_srs=True,
            update_quiz_stats=True,
            xp=10,
            quiz_type="meaning",
        )

        mock_db.users.update_quiz_stats.assert_called_once_with(1, True)
        mock_db.users.record_activity.assert_called_once_with(1, 10)
        mock_fsrs.grade_from_correctness.assert_called_once_with(True, 1, None)
        mock_fsrs.review.assert_called_once_with(1, 10, 3)
        mock_db.learning.record_mistake.assert_not_called()


def test_record_quiz_answer_wrong():
    """Test recording a wrong quiz answer."""
    with patch("learning_engine.db") as mock_db, patch(
        "learning_engine.fsrs"
    ) as mock_fsrs:

        mock_db.learning.get_word_skills.return_value = [
            {
                "skill_type": "meaning",
                "correct": 0,
                "wrong": 1,
                "total": 1,
                "accuracy": 0,
                "correct_streak": 0,
            }
        ]

        mock_fsrs.grade_from_correctness.return_value = 1

        from learning_engine import record_quiz_answer

        record_quiz_answer(
            user_id=1,
            word_id=10,
            skill_type="meaning",
            is_correct=False,
            user_answer="wrong",
            correct_answer="correct",
            update_srs=True,
            update_quiz_stats=True,
            xp=0,
            quiz_type="meaning",
        )

        mock_db.users.update_quiz_stats.assert_called_once_with(1, False)
        mock_db.learning.record_skill.assert_called_once_with(1, 10, "meaning", False)

        mock_fsrs.review.assert_called_once_with(1, 10, 1)
        mock_db.learning.record_mistake.assert_called_once()


def test_record_quiz_answer_no_word_id():
    """Test that SRS is not called when word_id is None."""
    with patch("learning_engine.db") as mock_db, patch(
        "learning_engine.fsrs"
    ) as mock_fsrs:

        from learning_engine import record_quiz_answer

        record_quiz_answer(
            user_id=1,
            word_id=None,
            skill_type="story",
            is_correct=True,
            update_srs=True,
            update_quiz_stats=True,
            xp=5,
        )

        mock_db.learning.record_skill.assert_not_called()
        mock_fsrs.review.assert_not_called()
