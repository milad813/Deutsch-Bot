"""Stable db.learning facade over focused repositories."""

from database.repositories.ltr import LTRRepository
from database.repositories.skills import WordSkillRepository
from database.repositories.practice import PracticeProgressRepository
from database.repositories.learning_stats import LearningStatsRepository
from database.repositories.llm_cache import LLMRepository


class LearningRepository(
    LTRRepository,
    WordSkillRepository,
    PracticeProgressRepository,
    LearningStatsRepository,
    LLMRepository,
):
    """Share one connection and transaction boundary across learning features."""
