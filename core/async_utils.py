# core/async_utils.py

import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_db(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Run a blocking database function in a worker thread.

    Usage:
        await run_db(db.words.get_due_count, user_id)
    """
    return await asyncio.to_thread(func, *args, **kwargs)