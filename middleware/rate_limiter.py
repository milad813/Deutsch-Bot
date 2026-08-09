"""Simple in-memory rate limiter for Telegram bot."""
import time
from collections import defaultdict
from typing import Dict, List


class RateLimiter:
    """Rate limiter using sliding window algorithm."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: Dict[int, List[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        """Check if request is allowed for user."""
        now = time.time()
        # Remove old requests outside the window
        self._requests[user_id] = [
            t for t in self._requests[user_id] if now - t < self.window
        ]
        if len(self._requests[user_id]) >= self.max_requests:
            return False
        self._requests[user_id].append(now)
        return True

    def reset(self, user_id: int) -> None:
        """Reset rate limit for a specific user."""
        self._requests.pop(user_id, None)

    def cleanup(self) -> None:
        """Remove all expired entries to free memory."""
        now = time.time()
        for user_id in list(self._requests.keys()):
            self._requests[user_id] = [
                t for t in self._requests[user_id] if now - t < self.window
            ]
            if not self._requests[user_id]:
                del self._requests[user_id]


# Global instance
rate_limiter = RateLimiter(max_requests=30, window_seconds=60)
