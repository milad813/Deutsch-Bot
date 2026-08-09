"""Unit tests for database functionality."""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Import database modules
from database import Database
from database.repositories.learning import LearningRepository


class TestDatabaseConnection:
    """Tests for database connection and thread safety."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_database_creation(self, temp_db):
        """Test database creation."""
        db = Database(temp_db)
        assert db is not None
        db.close()

    def test_database_close(self, temp_db):
        """Test database close."""
        db = Database(temp_db)
        db.close()
        # Should not raise

    def test_connection_sharing(self, temp_db):
        """Test that legacy and new repos share connection."""
        db = Database(temp_db)
        
        # Both should use same underlying connection
        assert hasattr(db, '_conn')
        assert hasattr(db, '_legacy')
        
        db.close()


class TestLearningRepository:
    """Tests for LearningRepository class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def learning_repo(self, temp_db):
        """Create a learning repository instance."""
        db = Database(temp_db)
        repo = db.learning
        yield repo
        db.close()

    def test_set_daily_goal(self, learning_repo):
        """Test setting daily goal."""
        user_id = 123
        goal = 20
        
        learning_repo.set_daily_goal(user_id, goal)
        
        # Verify by reading back
        retrieved = learning_repo.get_daily_goal(user_id)
        assert retrieved == goal

    def test_get_daily_goal_default(self, learning_repo):
        """Test getting default daily goal."""
        user_id = 999  # Non-existent user
        
        goal = learning_repo.get_daily_goal(user_id)
        assert goal == 10  # Default

    def test_get_today_activity_count_zero(self, learning_repo):
        """Test getting today's activity count with no data."""
        user_id = 123
        
        count = learning_repo.get_today_activity_count(user_id)
        assert count == 0

    def test_get_weekly_stats_empty(self, learning_repo):
        """Test getting weekly stats with no data."""
        user_id = 123
        
        stats = learning_repo.get_weekly_stats(user_id)
        assert stats["total_answers"] == 0
        assert stats["correct"] == 0
        assert stats["wrong"] == 0
        assert stats["accuracy"] == 0
        assert stats["active_days"] == 0

    def test_get_mistake_word_count_zero(self, learning_repo):
        """Test getting mistake count with no mistakes."""
        user_id = 123
        
        count = learning_repo.get_mistake_word_count(user_id)
        assert count == 0


class TestDailyGoalIntegration:
    """Integration tests for daily goal feature."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_full_daily_goal_flow(self, temp_db):
        """Test complete daily goal workflow."""
        db = Database(temp_db)
        user_id = 123
        
        # Set goal
        db.learning.set_daily_goal(user_id, 15)
        
        # Get goal
        goal = db.learning.get_daily_goal(user_id)
        assert goal == 15
        
        # Update goal
        db.learning.set_daily_goal(user_id, 25)
        goal = db.learning.get_daily_goal(user_id)
        assert goal == 25
        
        db.close()


class TestWeeklyStatsIntegration:
    """Integration tests for weekly stats feature."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_weekly_stats_structure(self, temp_db):
        """Test weekly stats returns correct structure."""
        db = Database(temp_db)
        user_id = 123
        
        stats = db.learning.get_weekly_stats(user_id)
        
        assert "total_answers" in stats
        assert "correct" in stats
        assert "wrong" in stats
        assert "accuracy" in stats
        assert "active_days" in stats
        
        db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
