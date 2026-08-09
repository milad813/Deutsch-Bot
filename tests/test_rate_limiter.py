"""Unit tests for rate limiter middleware."""

import time
import pytest
from unittest.mock import patch

from middleware.rate_limiter import RateLimiter, rate_limiter


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh rate limiter with small limits for testing."""
        return RateLimiter(max_requests=5, window_seconds=10)

    def test_first_request_allowed(self, limiter):
        """Test that first request is allowed."""
        user_id = 123
        assert limiter.is_allowed(user_id) is True

    def test_multiple_requests_within_limit(self, limiter):
        """Test multiple requests within limit are allowed."""
        user_id = 123
        
        # First 5 requests should be allowed
        for i in range(5):
            assert limiter.is_allowed(user_id) is True, f"Request {i+1} should be allowed"

    def test_request_beyond_limit_blocked(self, limiter):
        """Test that requests beyond limit are blocked."""
        user_id = 123
        
        # Use up all requests
        for _ in range(5):
            limiter.is_allowed(user_id)
        
        # 6th request should be blocked
        assert limiter.is_allowed(user_id) is False

    def test_different_users_independent(self, limiter):
        """Test that different users have independent limits."""
        user1 = 123
        user2 = 456
        
        # User1 uses all requests
        for _ in range(5):
            limiter.is_allowed(user1)
        
        # User1 should be blocked
        assert limiter.is_allowed(user1) is False
        
        # User2 should still be allowed
        assert limiter.is_allowed(user2) is True

    def test_window_expiration(self, limiter):
        """Test that requests expire after window."""
        user_id = 123
        
        # Use up all requests
        for _ in range(5):
            limiter.is_allowed(user_id)
        
        # Should be blocked
        assert limiter.is_allowed(user_id) is False
        
        # Simulate time passing (window is 10 seconds)
        # Manually clean old requests
        old_time = time.time() - 11  # 11 seconds ago
        limiter._requests[user_id] = [old_time]
        
        # Now should be allowed (old requests expired)
        assert limiter.is_allowed(user_id) is True

    def test_cleanup_old_requests(self, limiter):
        """Test that old requests are cleaned up."""
        user_id = 123
        
        # Add some old requests
        old_time = time.time() - 15  # 15 seconds ago (beyond 10s window)
        limiter._requests[user_id] = [old_time]
        
        # Make a new request (should cleanup old ones)
        limiter.is_allowed(user_id)
        
        # Old request should be removed
        assert old_time not in limiter._requests[user_id]

    def test_reset_method(self, limiter):
        """Test reset method clears all requests."""
        user1 = 123
        user2 = 456
        
        # Add requests for both users
        limiter.is_allowed(user1)
        limiter.is_allowed(user2)
        
        # Reset
        limiter.reset()
        
        # Both should be empty
        assert len(limiter._requests) == 0

    def test_cleanup_method(self, limiter):
        """Test cleanup method removes old entries."""
        user1 = 123
        user2 = 456
        
        # Add old request for user1
        old_time = time.time() - 15
        limiter._requests[user1] = [old_time]
        
        # Add recent request for user2
        recent_time = time.time()
        limiter._requests[user2] = [recent_time]
        
        # Cleanup
        limiter.cleanup()
        
        # User1 should be removed (old)
        assert user1 not in limiter._requests or len(limiter._requests[user1]) == 0
        
        # User2 should remain (recent)
        assert user2 in limiter._requests


class TestGlobalRateLimiter:
    """Tests for global rate_limiter instance."""

    def test_global_instance_exists(self):
        """Test that global instance exists."""
        assert rate_limiter is not None
        assert isinstance(rate_limiter, RateLimiter)

    def test_global_instance_default_config(self):
        """Test global instance has reasonable defaults."""
        assert rate_limiter.max_requests > 0
        assert rate_limiter.window > 0


class TestRateLimiterEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_max_requests(self):
        """Test limiter with zero max requests blocks everything."""
        limiter = RateLimiter(max_requests=0, window_seconds=10)
        user_id = 123
        
        # Should block immediately
        assert limiter.is_allowed(user_id) is False

    def test_very_large_window(self):
        """Test limiter with very large window."""
        limiter = RateLimiter(max_requests=5, window_seconds=3600)  # 1 hour
        user_id = 123
        
        # First 5 should be allowed
        for _ in range(5):
            assert limiter.is_allowed(user_id) is True
        
        # 6th should be blocked
        assert limiter.is_allowed(user_id) is False

    def test_concurrent_users(self):
        """Test handling many concurrent users."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        # Simulate 100 users
        for user_id in range(100):
            assert limiter.is_allowed(user_id) is True
        
        # All should have one request recorded
        assert len(limiter._requests) == 100

    def test_rapid_requests_same_user(self):
        """Test rapid successive requests from same user."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        user_id = 123
        
        # Rapid fire requests
        results = [limiter.is_allowed(user_id) for _ in range(10)]
        
        # First 3 allowed, rest blocked
        assert results[:3] == [True, True, True]
        assert results[3:] == [False] * 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
