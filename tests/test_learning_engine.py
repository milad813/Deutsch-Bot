"""Unit tests for learning_engine module."""

from unittest.mock import MagicMock, patch
import pytest


def test_record_quiz_answer_correct():
    """Test recording a correct quiz answer."""
    with patch("learning_engine.db") as mock_db, \
         patch("learning_engine.fsrs") as mock_fsrs:
        mock_fsrs.grade_from_correctness.return_value = 3
        
        from learning_engine import record_quiz_answer
        
        record_quiz_answer(
            user_id=1,
            word_id=10,
            skill_type="meaning",
            is_correct=True,
            update_srs=True,
            update_quiz_stats=True,
            xp=10,
        )
        
        mock_db.update_quiz_stats.assert_called_once_with(1, True)
        mock_db.learning.record_skill.assert_called_once_with(1, 10, "meaning", True)
        mock_fsrs.review.assert_called_once_with(1, 10, 3)
        mock_db.record_activity.assert_called_once_with(1, 10)
        mock_db.learning.record_mistake.assert_not_called()


def test_record_quiz_answer_wrong():
    """Test recording a wrong quiz answer."""
    with patch("learning_engine.db") as mock_db, \
         patch("learning_engine.fsrs") as mock_fsrs:
        mock_fsrs.grade_from_correctness.return_value = 1
        
        from learning_engine import record_quiz_answer
        
        record_quiz_answer(
            user_id=1,
            word_id=10,
            skill_type="meaning",
            is_correct=False,
            update_srs=True,
            update_quiz_stats=True,
            xp=0,
        )
        
        mock_db.learning.record_mistake.assert_called_once()


def test_record_quiz_answer_no_word_id():
    """Test that SRS is not called when word_id is None."""
    with patch("learning_engine.db") as mock_db, \
         patch("learning_engine.fsrs") as mock_fsrs:
        
        from learning_engine import record_quiz_answer
        
        record_quiz_answer(
            user_id=1,
            word_id=None,
            skill_type="story",
            is_correct=True,
            update_srs=True,
        )
        
        mock_fsrs.review.assert_not_called()
        mock_db.learning.record_skill.assert_not_called()


def test_record_skill():
    """Test recording a skill attempt."""
    with patch("learning_engine.db") as mock_db:
        from learning_engine import record_skill
        
        record_skill(user_id=1, word_id=10, skill_type="article", is_correct=True)
        
        mock_db.learning.record_skill.assert_called_once_with(1, 10, "article", True)


def test_record_mistake():
    """Test recording a mistake."""
    with patch("learning_engine.db") as mock_db:
        from learning_engine import record_mistake
        
        record_mistake(
            user_id=1,
            word_id=10,
            skill_type="meaning",
            quiz_type="meaning",
            user_answer="wrong",
            correct_answer="correct",
        )
        
        mock_db.learning.record_mistake.assert_called_once()
