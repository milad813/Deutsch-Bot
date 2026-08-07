"""SRS (Spaced Repetition System) service using FSRS algorithm."""

import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List, Iterable
from dataclasses import dataclass

from app.models import Word
import app.config as config

logger = logging.getLogger(__name__)


@dataclass
class FSRSState:
    """FSRS state for a word."""
    difficulty: float
    stability: float
    reps: int
    lapses: int
    last_review: Optional[datetime]
    next_review: Optional[datetime]
    phase: str


class FSRSParams:
    """FSRS algorithm parameters."""
    
    # Optimized weights for German language learning
    w = (
        0.4, 0.6, 2.4, 5.8, 4.93, 0.94, 0.86, 0.01,
        1.49, 0.14, 0.94, 2.18, 0.05, 0.34, 1.26, 0.29, 2.61
    )
    request_retention = 0.9

    def calc_difficulty(self, grade: int, last_d: float) -> float:
        """Calculate new difficulty based on grade."""
        if last_d <= 0:
            return self.w[4]

        delta_d = -self.w[6] * (grade - 3)
        new_d = last_d + delta_d
        new_d = self.w[7] * self.w[4] + (1 - self.w[7]) * new_d

        return min(max(new_d, 1.0), 10.0)

    def calc_stability(self, grade: int, last_s: float, last_d: float) -> float:
        """Calculate new stability based on grade and current state."""
        if last_s <= 0:
            grade = max(1, min(4, grade))
            return max(0.1, float(self.w[grade - 1]))

        r = self.request_retention

        if grade == 1:
            new_s = (
                self.w[11]
                * math.pow(last_d, -self.w[12])
                * (math.pow(last_s + 1, self.w[13]) - 1)
                * math.exp(self.w[14] * (1 - r))
            )
        else:
            factor = math.exp(self.w[8])
            hard_penalty = self.w[15] if grade == 2 else 1.0
            easy_bonus = self.w[16] if grade == 4 else 1.0

            new_s = last_s * (
                1
                + factor
                * math.pow(last_d, -self.w[9])
                * (math.pow(last_s + 1, self.w[10]) - 1)
                * hard_penalty
                * easy_bonus
            )

        return max(new_s, 0.1)

    def next_interval(self, stability: float) -> int:
        """Calculate next review interval in days."""
        if stability <= 0:
            return 1

        interval = stability * math.log(self.request_retention) / math.log(0.9)
        return max(1, min(365, round(interval)))


class FSRSService:
    """Service for managing spaced repetition using FSRS algorithm."""

    def __init__(self, word_repository):
        self.repo = word_repository
        self.params = FSRSParams()

    def get_state(self, user_id: int, word_id: int) -> Optional[FSRSState]:
        """Get current FSRS state for a word."""
        stats = self.repo.get_stats_full(user_id, word_id)
        if not stats:
            return None

        ease = stats.get("ease") or 2.5
        interval = stats.get("interval") or 0
        difficulty = stats.get("difficulty", 0.0) or max(1.0, min(10.0, 11.0 - ease * 2))
        stability = stats.get("stability", 0.0) or float(interval if interval > 0 else 0.1)

        reps = stats["correct"] + stats["wrong"]
        lapses = stats["wrong"]

        next_review = None
        if stats["next_review"]:
            try:
                next_review = datetime.strptime(stats["next_review"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass

        return FSRSState(
            difficulty=difficulty,
            stability=stability,
            reps=reps,
            lapses=lapses,
            last_review=None,
            next_review=next_review,
            phase=stats.get("phase", "new"),
        )

    def review(self, user_id: int, word_id: int, grade: int) -> Tuple[FSRSState, int]:
        """Process a review and update FSRS state."""
        if grade not in [1, 2, 3, 4]:
            logger.warning("Invalid grade: %s", grade)
            grade = 3

        state = self.get_state(user_id, word_id)
        now = datetime.now(timezone.utc)

        if state is None:
            difficulty = self.params.w[4]
            grade = max(1, min(4, grade))
            stability = max(0.1, float(self.params.w[grade - 1]))
            reps = 1
            lapses = 1 if grade == 1 else 0
        else:
            difficulty = self.params.calc_difficulty(grade, state.difficulty)
            stability = self.params.calc_stability(grade, state.stability, state.difficulty)
            reps = state.reps + 1
            lapses = state.lapses + (1 if grade == 1 else 0)

        # Grade 1 (Again) → immediate review in 4 hours
        if grade == 1:
            interval_days = 0
            next_review = now + timedelta(hours=4)
            phase = "learning"
        else:
            interval_days = self.params.next_interval(stability)
            next_review = now + timedelta(days=interval_days)
            if state is None:
                phase = "mastered" if grade >= 4 else "review"
            elif state.phase == "learning":
                phase = "review" if grade >= 3 else "learning"
            elif grade >= 3 and (reps - lapses) >= 3:
                phase = "mastered"
            else:
                phase = "review"

        ease_factor = max(1.3, min(2.5, (11.0 - difficulty) / 2))
        srs_level = max(0, reps - lapses)
        srs_level = min(5, srs_level)

        self.repo.update_stats_fsrs(
            user_id=user_id,
            word_id=word_id,
            correct=1 if grade >= 2 else 0,
            wrong=1 if grade == 1 else 0,
            ease_factor=ease_factor,
            interval_days=interval_days,
            srs_level=srs_level,
            last_review=now.strftime("%Y-%m-%d %H:%M:%S"),
            next_review=next_review.strftime("%Y-%m-%d %H:%M:%S"),
            phase=phase,
            stability=stability,
            difficulty=difficulty,
        )

        new_state = FSRSState(
            difficulty=difficulty,
            stability=stability,
            reps=reps,
            lapses=lapses,
            last_review=now,
            next_review=next_review,
            phase=phase,
        )
        return new_state, interval_days

    def grade_from_correctness(self, is_correct: bool) -> int:
        """Convert boolean correctness to FSRS grade."""
        return 3 if is_correct else 1

    def get_review_cards(
        self,
        user_id: int,
        limit: int = 10,
        lesson_id: int = None,
        include_new: bool = True,
        new_limit: Optional[int] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        only_new: bool = False,
    ) -> List[Word]:
        """Get words for review session."""
        if new_limit is None:
            new_limit = min(5, limit)

        if only_new:
            return self.repo.get_new_words(
                user_id=user_id,
                lesson_id=lesson_id,
                limit=limit,
                exclude_ids=exclude_ids,
            )

        return self.repo.get_flashcard_words(
            user_id=user_id,
            limit=limit,
            lesson_id=lesson_id,
            include_new=include_new,
            new_limit=new_limit,
            exclude_ids=exclude_ids,
        )

    def review_flashcard(self, user_id: int, word_id: int, grade: int) -> Tuple[FSRSState, int]:
        """Process a flashcard review."""
        return self.review(user_id, word_id, grade)

    def review_ltr(self, user_id: int, word_id: int, results: List[bool]) -> Tuple[FSRSState, int]:
        """Process LTR (Learn Then Review) session results."""
        if not results:
            return self.get_state(user_id, word_id), 0
        
        final_results = list(results)[-3:]
        correct_count = sum(final_results)
        
        if correct_count >= 3:
            grade = 3
        elif correct_count == 2:
            grade = 2
        else:
            grade = 1
        
        return self.review(user_id, word_id, grade)
