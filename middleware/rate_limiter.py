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



# Global instance
rate_limiter = RateLimiter(max_requests=80, window_seconds=60)
