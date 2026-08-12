"""Story module for German language learning bot."""

from handlers.story.core import (
    _generate_story_for_lesson as generate_story_for_lesson,
    show_story_menu,
)
from handlers.story.view import (
    show_story,
    show_story_hint,
    show_story_translation,
    play_story_audio,
    play_story_listen_read,
    play_story_listen_only,
    show_story_words,
    replay_story,
)
from handlers.story.quiz import (
    start_story_quiz,
    handle_story_answer,
)

__all__ = [
    # Core
    "generate_story_for_lesson",
    "show_story_menu",
    # View
    "show_story",
    "show_story_hint",
    "show_story_translation",
    "play_story_audio",
    "play_story_listen_read",
    "play_story_listen_only",
    "show_story_words",
    "replay_story",
    # Quiz
    "start_story_quiz",
    "handle_story_answer",
]
