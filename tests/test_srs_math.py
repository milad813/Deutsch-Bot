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
