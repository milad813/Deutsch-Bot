"""Simple in-memory rate limiter for Telegram bot."""

import time
from collections import defaultdict
from typing import Dict, List

import config


class RateLimiter:
    """Rate limiter using sliding window algorithm."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: Dict[int, List[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        """Check if request is allowed for user.

        Behavior is unchanged from the original implementation: prune
        timestamps older than ``self.window`` from this user's history,
        reject the request if the remaining count is at or above the
        limit, otherwise record the new timestamp and accept.
        """
        now = time.time()
        # Remove old requests outside the window
        self._requests[user_id] = [
            t for t in self._requests[user_id] if now - t < self.window
        ]
        if len(self._requests[user_id]) >= self.max_requests:
            return False
        self._requests[user_id].append(now)
        return True

    def cleanup(self) -> None:
        """Drop bookkeeping for users that have been quiet for at least one
        full window.

        ``is_allowed`` already prunes stale timestamps from each user's
        list, but the per-user key itself never gets removed. Over a long
        uptime that means the dict grows without bound, even if the same
        users never come back. ``cleanup`` walks the dict once and
        deletes entries whose *newest* timestamp is older than the
        window — i.e. users who can't affect any future decision.
        """
        now = time.time()
        threshold = self.window
        stale: List[int] = []
        for user_id, timestamps in self._requests.items():
            if not timestamps:
                stale.append(user_id)
                continue
            if now - max(timestamps) >= threshold:
                stale.append(user_id)
        for user_id in stale:
            self._requests.pop(user_id, None)


# Global instance — driven by config so it's tunable from .env without
# touching code. ``config`` is guaranteed to be importable here because
# ``bot.py`` imports this module via the handler package, and ``config``
# only depends on stdlib + a local .env file.
rate_limiter = RateLimiter(
    max_requests=config.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=config.RATE_LIMIT_WINDOW_SECONDS,
)

