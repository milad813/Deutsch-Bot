"""Characterization tests for option_generator and utils."""

from models import Word
from option_generator import get_wrong_options, make_options, sample_unique
from utils import safe_id_list, safe_json_list


def _word(**kw):
    defaults = dict(
        id=1, german="Hund", persian="سگ", word_type="Noun", article="der"
    )
    defaults.update(kw)
    return Word(**defaults)


class FakeWordRepo:
    def __init__(self, pool):
        self.pool = pool

    def get_by_type(self, word_type, exclude_id=None, limit=50):
        out = [
            w
            for w in self.pool
            if (word_type is None or w.word_type == word_type)
            and w.id != exclude_id
        ]
        return out[:limit]


def test_sample_unique_dedupes_and_limits():
    out = sample_unique(["a", "a", "b"], ["b", "c", ""], 3)
    assert len(out) == 3
    assert len(set(out)) == 3


def test_make_options_requires_minimum():
    assert make_options("", ["x"], total=4) is None
    assert make_options("correct", ["w1"], total=4, min_options=3) is None
    opts = make_options("correct", ["w1", "w2"], total=4, min_options=2)
    assert opts is not None
    assert "correct" in opts and "w1" in opts
    assert len(set(opts)) == len(opts)


def test_make_options_respects_total():
    opts = make_options("c", ["w1", "w2", "w3", "w4"], total=4, min_options=2)
    assert len(opts) == 4


def test_get_wrong_options_prioritizes_same_type():
    target = _word(id=1, persian="سگ", word_type="Noun")
    pool = [
        _word(id=2, persian="گربه", word_type="Noun"),
        _word(id=3, persian="پریدن", word_type="Verb"),
        _word(id=4, persian="آبی", word_type="Adjective"),
        _word(id=5, persian="سریع", word_type="Adjective"),
    ]
    db = type("DB", (), {"words": FakeWordRepo(pool)})()

    wrongs = get_wrong_options(db, target, count=2, attr_getter=lambda w: w.persian)

    assert len(wrongs) == 2
    assert "سگ" not in wrongs
    # same-type candidates come first
    assert "گربه" in wrongs


def test_get_wrong_options_excludes_target_value():
    target = _word(id=1, persian="سگ", word_type="Noun")
    pool = [_word(id=2, persian="سگ", word_type="Noun")]
    db = type("DB", (), {"words": FakeWordRepo(pool)})()
    wrongs = get_wrong_options(db, target, count=3, attr_getter=lambda w: w.persian)
    assert wrongs == []


# ─── utils ───────────────────────────────────────────────────────


def test_safe_json_list():
    assert safe_json_list('[1, "a", 3]') == [1, "a", 3]
    assert safe_json_list(None) == []
    assert safe_json_list("not json") == []
    assert safe_json_list('{"a": 1}') == []  # dict is not a list


def test_safe_id_list():
    assert safe_id_list('[1, "2", 3.0, "x"]') == [1, 2, 3]
    assert safe_id_list(None) == []
    assert safe_id_list("[]") == []
