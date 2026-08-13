import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

from models import Word

logger = logging.getLogger(__name__)


def _parse_utc_datetime(value) -> Optional[datetime]:
    """
    تبدیل مقدار تاریخ/زمان ذخیره‌شده در دیتابیس به datetime aware در UTC.
    """
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1]

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    )

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    for candidate in (text, text.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

    return None


@dataclass
class FSRSState:
    difficulty: float
    stability: float
    reps: int
    lapses: int
    last_review: Optional[datetime]
    next_review: Optional[datetime]
    phase: str


class FSRSParams:
    """
    پارامترهای FSRS-inspired / FSRS-4.5-like.

    نکته:
    این نسخه برای سازگاری با دیتابیس فعلی بات طراحی شده و سعی دارد
    رفتار FSRS را تا حد ممکن درست شبیه‌سازی کند.
    """

    w = (
        0.4,
        0.6,
        2.4,
        5.8,
        4.93,
        0.94,
        0.86,
        0.01,
        1.49,
        0.14,
        0.94,
        2.18,
        0.05,
        0.34,
        1.26,
        0.29,
        2.61,
    )

    request_retention = 0.9
    max_interval_days = 365
    max_stability = 3650.0

    def _clamp_grade(self, grade: int) -> int:
        try:
            grade = int(grade)
        except Exception:
            grade = 3
        return max(1, min(4, grade))

    def calc_difficulty(self, grade: int, last_d: float) -> float:
        """
        محاسبه difficulty.

        برای کارت جدید:
        D0(G) = w4 - (G - 3) * w5

        برای کارت‌های قبلی:
        D' = w7 * D0(3) + (1 - w7) * (D - w6 * (G - 3))
        """
        grade = self._clamp_grade(grade)

        if last_d is None or last_d <= 0:
            d0 = self.w[4] - (grade - 3) * self.w[5]
            return min(max(d0, 1.0), 10.0)

        delta_d = -self.w[6] * (grade - 3)
        new_d = float(last_d) + delta_d

        # Mean reversion به سمت D0(3)
        new_d = self.w[7] * self.w[4] + (1.0 - self.w[7]) * new_d

        return min(max(new_d, 1.0), 10.0)

    def retrievability(self, elapsed_days: Optional[float], stability: float) -> float:
        """
        تخمین retrievability با منحنی فراموشی FSRS:

        R = (1 + t / (9 * S))^-1
        """
        if stability <= 0:
            return 0.0

        if elapsed_days is None:
            return self.request_retention

        if elapsed_days <= 0:
            return 1.0

        return (1.0 + (float(elapsed_days) / (9.0 * float(stability)))) ** -1

    def calc_stability(
        self,
        grade: int,
        last_s: float,
        last_d: float,
        retrievability: Optional[float],
    ) -> float:
        """
        محاسبه stability جدید.

        برای Again / grade=1:
        S'_fail = w11 * D^-w12 * ((S + 1)^w13 - 1) * exp(w14 * (1 - R))

        برای پاسخ موفق:
        S'_success = S * (1 + exp(w8) * (11 - D) * S^-w9 *
                           (exp(w10 * (1 - R)) - 1) *
                           hard_penalty * easy_bonus)
        """
        grade = self._clamp_grade(grade)

        if last_s is None or last_s <= 0:
            return max(0.1, float(self.w[grade - 1]))

        d = max(1.0, min(10.0, float(last_d or 5.0)))
        s = max(0.1, float(last_s))

        r = self.request_retention if retrievability is None else float(retrievability)
        r = min(max(r, 0.0), 1.0)

        if grade == 1:
            new_s = (
                self.w[11]
                * math.pow(d, -self.w[12])
                * (math.pow(s + 1.0, self.w[13]) - 1.0)
                * math.exp(self.w[14] * (1.0 - r))
            )

            # بعد از lapse معمولاً نباید stability از مقدار قبلی بیشتر شود.
            new_s = min(new_s, s)
        else:
            hard_penalty = self.w[15] if grade == 2 else 1.0
            easy_bonus = self.w[16] if grade == 4 else 1.0

            success_factor = (
                math.exp(self.w[8])
                * (11.0 - d)
                * math.pow(s, -self.w[9])
                * (math.exp(self.w[10] * (1.0 - r)) - 1.0)
            )

            new_s = s * (1.0 + success_factor * hard_penalty * easy_bonus)

            # در مرور موفق، stability نباید از مقدار قبلی کمتر شود.
            new_s = max(new_s, s)

        return min(max(new_s, 0.1), self.max_stability)

    def next_interval(self, stability: float) -> int:
        """
        محاسبه فاصله مرور بر اساس desired retention.

        برای منحنی FSRS:
        I = 9 * S * (1 / R - 1)

        برای R = 0.9:
        I ≈ S
        """
        if stability is None or stability <= 0:
            return 1

        interval = 9.0 * float(stability) * ((1.0 / self.request_retention) - 1.0)

        if interval < 1.0:
            return 1

        return max(1, min(self.max_interval_days, int(round(interval))))


class FSRSService:
    def __init__(self, db):
        self.db = db
        self.params = FSRSParams()

    def get_state(self, user_id: int, word_id: int) -> Optional[FSRSState]:
        stats = self.db.get_word_stats_full(user_id, word_id)
        if not stats:
            return None

        ease = stats.get("ease") or 2.5
        interval = stats.get("interval") or 0

        difficulty = stats.get("difficulty", 0.0)
        if not difficulty:
            difficulty = max(1.0, min(10.0, 11.0 - float(ease) * 2.0))

        stability = stats.get("stability", 0.0)
        if not stability:
            stability = float(interval if interval > 0 else 0.1)

        reps = int(stats.get("correct", 0) or 0) + int(stats.get("wrong", 0) or 0)
        lapses = int(stats.get("wrong", 0) or 0)

        next_review = _parse_utc_datetime(stats.get("next_review"))
        last_review = _parse_utc_datetime(stats.get("last_reviewed"))

        return FSRSState(
            difficulty=float(difficulty),
            stability=float(stability),
            reps=reps,
            lapses=lapses,
            last_review=last_review,
            next_review=next_review,
            phase=stats.get("phase") or "new",
        )

    def review(self, user_id: int, word_id: int, grade: int) -> Tuple[FSRSState, int]:
        grade = self.params._clamp_grade(grade)

        state = self.get_state(user_id, word_id)
        now = datetime.now(timezone.utc)

        is_new = state is None or state.reps <= 0

        retrievability = self.params.request_retention
        if not is_new and state.last_review is not None and state.stability > 0:
            elapsed_days = max(
                0.0,
                (now - state.last_review).total_seconds() / 86400.0,
            )
            retrievability = self.params.retrievability(elapsed_days, state.stability)

        if is_new:
            difficulty = self.params.calc_difficulty(grade, 0.0)
            stability = max(0.1, float(self.params.w[grade - 1]))
            reps = 1
            lapses = 1 if grade == 1 else 0
        else:
            difficulty = self.params.calc_difficulty(grade, state.difficulty)
            stability = self.params.calc_stability(
                grade,
                state.stability,
                state.difficulty,
                retrievability,
            )
            reps = state.reps + 1
            lapses = state.lapses + (1 if grade == 1 else 0)

        if grade == 1:
            interval_days = 0
            next_review = now + timedelta(minutes=10)
            phase = "learning"
        else:
            interval_days = self.params.next_interval(stability)
            next_review = now + timedelta(days=interval_days)

            if is_new:
                # کارت جدید با Hard بهتر است هنوز learning بماند.
                phase = "learning" if grade == 2 else "review"
            elif (state.phase or "new") == "learning":
                phase = "review" if grade >= 3 else "learning"
            elif grade >= 3 and (reps - lapses) >= 3:
                phase = "mastered"
            else:
                phase = "review"

        ease_factor = max(1.3, min(2.5, (11.0 - difficulty) / 2.0))

        srs_level = max(0, reps - lapses)
        srs_level = min(5, srs_level)

        self.db.update_word_stats_fsrs(
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

    def grade_from_correctness(
        self,
        is_correct: bool,
        consecutive_correct: int = 0,
    ) -> int:
        """
        تبدیل نتیجه کوییز به grade.

        1 = Again
        2 = Hard
        3 = Good
        4 = Easy

        اگر کاربر اشتباه زد: Again
        اگر درست زد و تعداد درست‌های متوالی واقعی زیاد بود: Easy
        در غیر این صورت: Good
        """
        if not is_correct:
            return 1

        try:
            consecutive_correct = int(consecutive_correct or 0)
        except Exception:
            consecutive_correct = 0

        if consecutive_correct >= 3:
            return 4

        return 3

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
        if new_limit is None:
            new_limit = min(5, limit)

        if only_new:
            return self.db.get_new_word_objects(
                user_id=user_id,
                lesson_id=lesson_id,
                limit=limit,
                exclude_ids=exclude_ids,
            )

        return self.db.get_flashcard_words(
            user_id=user_id,
            limit=limit,
            lesson_id=lesson_id,
            include_new=include_new,
            new_limit=new_limit,
            exclude_ids=exclude_ids,
        )

    def review_flashcard(
        self,
        user_id: int,
        word_id: int,
        grade: int,
    ) -> Tuple[FSRSState, int]:
        """
        بررسی فلش‌کارت.
        grade مستقیم از کاربر گرفته می‌شود:
        1=Again, 2=Hard, 3=Good, 4=Easy
        """
        return self.review(user_id, word_id, grade)

    def review_ltr(self, user_id: int, word_id: int, results) -> Tuple[FSRSState, int]:
        """
        تبدیل نتیجه‌های LTR به grade و سپس مرور FSRS.

        results معمولاً لیستی از True/False است.
        """
        recent = list(results or [])[-3:]

        if not recent:
            return self.review(user_id, word_id, 3)

        last_was_correct = bool(recent[-1])
        correct_count = sum(1 for r in recent if r)

        if not last_was_correct:
            # اگر آخرین پاسخ غلط باشد:
            # - اگر قبلاً در همان batch درست داشته: Hard
            # - اگر هیچ درستی نداشته: Again
            grade = 2 if correct_count > 0 else 1
        else:
            if len(recent) == 1:
                # یک پاسخ درست تنها: Good
                grade = 3
            elif correct_count == len(recent):
                # همه پاسخ‌های اخیر درست: Easy
                grade = 4
            elif correct_count >= len(recent) - 1:
                # فقط یک خطا در میان اخیرها و آخرین پاسخ درست: Good
                grade = 3
            else:
                grade = 2

        return self.review(user_id, word_id, grade)