"""Story module for German language learning bot."""

from handlers.story.core import _generate_story_for_lesson as generate_story_for_lesson
from handlers.story.core import show_story_menu
from handlers.story.quiz import handle_story_answer, start_story_quiz
from handlers.story.view import (
    play_story_audio,
    play_story_listen_only,
    play_story_listen_read,
    replay_story,
    show_story,
    show_story_hint,
    show_story_translation,
    show_story_words,
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
