"""User-domain pure logic (no I/O, no framework imports)."""


def level_from_xp(xp: int) -> tuple:
    """Map XP to (level, current_progress, needed_per_level).

    Levels advance every 100 XP.
    """
    xp = max(0, int(xp or 0))
    level = (xp // 100) + 1
    current = xp % 100
    needed = 100
    return level, current, needed
