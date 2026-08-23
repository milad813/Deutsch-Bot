"""Characterization tests for srs_service (pure FSRS math + grade mapping)."""

import math

from srs_service import FSRSParams, FSRSService

P = FSRSParams()


# ─── grade clamping ──────────────────────────────────────────────


def test_clamp_grade_bounds():
    assert P._clamp_grade(0) == 1
    assert P._clamp_grade(1) == 1
    assert P._clamp_grade(4) == 4
    assert P._clamp_grade(99) == 4
    assert P._clamp_grade("junk") == 3


# ─── difficulty ──────────────────────────────────────────────────


def test_new_card_difficulty_formula():
    # D0(G) = w4 - (G-3)*w5
    assert P.calc_difficulty(3, 0.0) == P.w[4]
    assert P.calc_difficulty(1, None) == min(max(P.w[4] + 2 * P.w[5], 1.0), 10.0)
    assert P.calc_difficulty(4, 0.0) == max(P.w[4] - P.w[5], 1.0)


def test_difficulty_mean_reversion_pulls_extremes_back():
    # repeated Goods from the ceiling drift back down toward D0(3)
    d = 10.0
    for _ in range(20):
        d = P.calc_difficulty(3, d)
        assert 1.0 <= d <= 10.0
    assert d < 10.0


def test_harder_grades_lower_difficulty():
    after_good = P.calc_difficulty(3, 5.0)
    after_easy = P.calc_difficulty(4, 5.0)
    after_again = P.calc_difficulty(1, 5.0)
    assert after_again > after_good > after_easy


# ─── stability ───────────────────────────────────────────────────


def test_new_card_stability_uses_weight_vector():
    for g in (1, 2, 3, 4):
        assert P.calc_stability(g, None, None, None) == P.w[g - 1]


def test_lapse_never_increases_stability():
    new_s = P.calc_stability(1, last_s=50.0, last_d=8.0, retrievability=0.9)
    assert new_s <= 50.0


def test_success_never_decreases_stability():
    new_s = P.calc_stability(3, last_s=50.0, last_d=5.0, retrievability=0.5)
    assert new_s >= 50.0


# ─── interval & retrievability ───────────────────────────────────


def test_next_interval_edges():
    assert P.next_interval(None) == 1
    assert P.next_interval(0) == 1
    one_day = P.next_interval(P.request_retention / 9 * 10)  # solves I=1... ~S
    assert one_day >= 1
    assert P.next_interval(3650) <= P.max_interval_days


def test_interval_grows_with_stability():
    assert P.next_interval(2) <= P.next_interval(10) <= P.next_interval(100)


def test_retrievability_curve():
    assert P.retrievability(None, 5.0) == P.request_retention
    assert P.retrievability(0, 5.0) == 1.0
    assert P.retrievability(1, 5.0) < 1.0
    # R(9*S) ≈ 0.5 by construction of the forgetting curve
    half_life = P.retrievability(9 * 5.0, 5.0)
    assert math.isclose(half_life, 0.5, rel_tol=0.01)


# ─── quiz-result → grade mapping (learning_engine contract) ──────


def _svc():
    return FSRSService(db=None)


def test_wrong_answer_is_always_again():
    svc = _svc()
    assert svc.grade_from_correctness(False) == 1
    assert svc.grade_from_correctness(False, consecutive_correct=10) == 1


def test_slow_correct_answer_is_hard():
    svc = _svc()
    assert svc.grade_from_correctness(True, 0, response_time_sec=99.0, quiz_type="meaning") == 2


def test_type_specific_time_thresholds():
    svc = _svc()
    # cloze tolerates 12s; listening 15s; meaning only 8s
    assert svc.grade_from_correctness(True, 0, response_time_sec=10.0, quiz_type="cloze") == 3
    assert svc.grade_from_correctness(True, 0, response_time_sec=10.0, quiz_type="listening") == 3
    assert svc.grade_from_correctness(True, 0, response_time_sec=10.0, quiz_type="meaning") == 2


def test_three_consecutive_correct_is_easy():
    svc = _svc()
    assert svc.grade_from_correctness(True, consecutive_correct=3) == 4
    assert svc.grade_from_correctness(True, consecutive_correct=2) == 3


# ─── LTR results → grade mapping ─────────────────────────────────


def test_review_ltr_mapping(monkeypatch):
    svc = FSRSService(db=None)
    seen = {}

    def fake_review(user_id, word_id, grade):
        seen["grade"] = grade
        return ("state", 7)

    monkeypatch.setattr(svc, "review", fake_review)

    uid, wid = 1, 2
    svc.review_ltr(uid, wid, [True])
    assert seen["grade"] == 3

    svc.review_ltr(uid, wid, [True, True])
    assert seen["grade"] == 4

    svc.review_ltr(uid, wid, [True, False, True])
    assert seen["grade"] == 3

    svc.review_ltr(uid, wid, [True, False, False])
    assert seen["grade"] == 2

    svc.review_ltr(uid, wid, [False])
    assert seen["grade"] == 1

    svc.review_ltr(uid, wid, [False, True, False])
    assert seen["grade"] == 2

    svc.review_ltr(uid, wid, [])
    assert seen["grade"] == 3  # empty → default Good


# ─── long-gap memory decay & spacing effect (edge cases) ─────────


def test_retrievability_after_100_days_decays_monotonically():
    r10 = P.retrievability(10, 10.0)
    r50 = P.retrievability(50, 10.0)
    r100 = P.retrievability(100, 10.0)

    assert P.request_retention > r10 > r50 > r100 > 0.0
    # Forgetting curve is constructed so that R(9*S) ≈ 0.5.
    assert math.isclose(P.retrievability(90, 10.0), 0.5, rel_tol=0.01)


def test_success_after_100_day_gap_multiplies_stability():
    """Spacing effect: a successful recall after a long gap boosts S hard."""
    old_s = 10.0
    r = P.retrievability(100, old_s)

    new_s = P.calc_stability(3, last_s=old_s, last_d=5.0, retrievability=r)

    assert new_s > old_s * 5, "long gap + success should multiply stability"
    assert new_s <= P.max_stability


def test_interval_from_long_gap_stability_is_capped():
    new_s = P.calc_stability(4, last_s=200.0, last_d=3.0, retrievability=0.95)
    assert P.next_interval(new_s) <= P.max_interval_days


# ─── clock drift (negative elapsed days) ─────────────────────────


def test_negative_elapsed_days_is_treated_as_just_reviewed():
    # Clock skew must never produce R > 1 or negative-day weirdness.
    assert P.retrievability(-3, 10.0) == 1.0
    assert P.retrievability(-0.001, 10.0) == 1.0


def test_review_with_future_last_review_grants_no_free_stability(monkeypatch):
    """If last_review lies in the future, elapsed clamps to 0 → R=1 → ΔS=0."""
    from datetime import datetime, timedelta, timezone
    from srs_service import FSRSState

    svc = FSRSService(db=None)
    future = datetime.now(timezone.utc) + timedelta(days=2)
    frozen = FSRSState(
        difficulty=5.0,
        stability=30.0,
        reps=4,
        lapses=1,
        last_review=future,
        next_review=None,
        phase="review",
    )

    captured = {}

    class _WordsRepo:
        @staticmethod
        def update_stats_fsrs(**kwargs):
            captured.update(kwargs)

    class _DB:
        words = _WordsRepo()

    monkeypatch.setattr(svc, "get_state", lambda u, w: frozen)
    svc.db = _DB()

    state, _interval = svc.review(1, 2, grade=3)

    assert state.stability == 30.0
    assert captured["stability"] == 30.0


# ─── grade_from_correctness edge inputs ──────────────────────────


def test_grade_with_none_response_time_and_unknown_quiz_type():
    svc = _svc()

    # Unknown quiz_type falls back to the 8s threshold; rt=None skips it.
    assert (
        svc.grade_from_correctness(True, 0, response_time_sec=None, quiz_type="telepathy")
        == 3
    )
    # Unknown type + genuinely slow answer → Hard via default threshold.
    assert (
        svc.grade_from_correctness(True, 0, response_time_sec=20.0, quiz_type="telepathy")
        == 2
    )
    # Streak-based Easy is unaffected by missing rt/type.
    assert svc.grade_from_correctness(True, 3, response_time_sec=None, quiz_type=None) == 4
    # Wrong answers are always Again regardless of timing metadata.
    assert svc.grade_from_correctness(False, 0, response_time_sec=None, quiz_type="???") == 1


def test_grade_threshold_is_strictly_greater():
    svc = _svc()
    # Exactly AT the threshold is still fast enough (comparison is `>`).
    assert svc.grade_from_correctness(True, 0, response_time_sec=8.0, quiz_type="meaning") == 3
    assert svc.grade_from_correctness(True, 0, response_time_sec=8.01, quiz_type="meaning") == 2
