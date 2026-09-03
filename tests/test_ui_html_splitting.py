"""Tests for ``ui.split_html_text`` and the plain-text fallback helper.

These cover Phase 1 item 2 of ``docs/PHASE1.md``: ``render()`` must
chunk long HTML messages safely so that Telegram never sees an
unbalanced tag. The previous splitter cut on newlines only, which could
slice a chunk right in the middle of ``<b>...</b>`` and trigger
``BadRequest: can't parse entities``.
"""

import pytest

from ui import split_html_text, to_plain_text


# ─── split_html_text — basic shape ──────────────────────────────────────────


def test_short_text_returns_one_chunk():
    """Inputs that already fit in one chunk are returned verbatim."""
    text = "Hello <b>world</b>!"
    chunks = split_html_text(text, max_len=4096)
    assert chunks == [text]


def test_long_text_returns_multiple_chunks():
    """Inputs that exceed max_len must produce more than one chunk."""
    text = "<b>" + ("a" * 100 + " ") * 200 + "</b>"  # ~20 KB
    chunks = split_html_text(text, max_len=3900)
    assert len(chunks) >= 2


def test_every_chunk_is_under_max_len_bytes():
    """Every chunk must fit the UTF-8 byte budget, regardless of length."""
    text = "word " * 5000  # 25 KB of plain text
    max_len = 3900
    chunks = split_html_text(text, max_len=max_len)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= max_len


# ─── split_html_text — tag balancing ────────────────────────────────────────


def test_bold_tag_is_closed_and_reopened_across_chunks():
    """A long ``<b>`` span is closed at the end of one chunk and
    reopened at the start of the next so Telegram never sees an
    unbalanced tag.
    """
    text = "<b>" + ("x " * 1000) + "</b>"  # ~6 KB inside one <b>...</b>
    max_len = 1000
    chunks = split_html_text(text, max_len=max_len)

    # The first chunk must end with the closing </b> and the next
    # chunk must start by re-opening <b>.
    assert len(chunks) >= 2
    assert chunks[0].endswith("</b>")
    assert chunks[1].startswith("<b>")
    # Each chunk is bounded.
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= max_len
    # The inner text (no tags) is preserved across all chunks: the
    # total number of ``x`` characters in the joined output equals
    # the number in the input. The chunk-aware splitter inserts
    # extra ``<b>``/``</b>`` pairs around each fragment, so we
    # only check the *content*, not byte-equality of the joined
    # string.
    inner = "x " * 1000
    total_x = sum(chunk.count("x") for chunk in chunks)
    assert total_x == inner.count("x")


def test_nested_tags_close_in_correct_order():
    """When several tags are open at the boundary, they must close
    inner-first and reopen outer-first, so the rendered structure is
    preserved.
    """
    inner = "x " * 1500  # ~3 KB
    text = f"<b><i>{inner}</i></b>"
    max_len = 800
    chunks = split_html_text(text, max_len=max_len)

    assert len(chunks) >= 2

    # The boundary on chunk 0 ends with </i></b> (inner first, then
    # outer), and the next chunk reopens with <b><i> (outer first).
    boundary = chunks[0][-32:]
    assert "</i>" in boundary
    assert boundary.endswith("</b>")

    reopen = chunks[1][:32]
    assert reopen.startswith("<b>")
    assert "<i>" in reopen

    # The inner text content is preserved across chunks.
    total_x = sum(chunk.count("x") for chunk in chunks)
    assert total_x == inner.count("x")


def test_pre_block_is_not_split_into_invalid_html():
    """A ``<pre>...</pre>`` block is treated as a single token: the
    splitter may place it whole in one chunk, but it must never
    produce a chunk that contains ``<pre>`` without the matching
    ``</pre>``.
    """
    body = "line\n" * 800
    text = f"<pre>{body}</pre>"
    max_len = 500
    chunks = split_html_text(text, max_len=max_len)

    # Either the whole <pre> block fits in a single chunk, or each
    # chunk that contains <pre> has a matching </pre>. The chunk-
    # aware splitter may insert extra <pre>...</pre> pairs to keep
    # each chunk self-contained, so we only check structural
    # well-formedness, not byte-equality with the input.
    for chunk in chunks:
        opens = chunk.count("<pre>")
        closes = chunk.count("</pre>")
        assert opens == closes, f"unbalanced <pre> in chunk: {chunk[:80]!r}"
        assert len(chunk.encode("utf-8")) <= max_len
    # The inner body text is preserved across chunks.
    total_lines = sum(chunk.count("line") for chunk in chunks)
    assert total_lines >= body.count("line")


# ─── split_html_text — robustness / fallback ───────────────────────────────


def test_unsupported_tag_triggers_plain_text_fallback():
    """Tags outside the allow-list (e.g. ``<span>``) must NOT be split
    mid-attribute; the splitter falls back to a plain-text chunking
    and the caller is expected to send with ``parse_mode=None``.
    """
    # Build a payload that, even after ``to_plain_text`` strips every
    # ``<span>`` wrapper, is still well over ``max_len`` bytes. This
    # forces the chunker to actually split the plain version into
    # multiple pieces, which is the only way to verify the fallback
    # path is producing bounded chunks.
    inner = "abcdef " * 400  # ~2.8 KB per <span>...</span>
    text = ("<span class='x'>" + inner + "</span>\n") * 50  # ~140 KB raw
    max_len = 500
    chunks = split_html_text(text, max_len=max_len)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= max_len
    # No chunk should contain an unescaped "<span" — the fallback
    # path strips tags before chunking.
    for chunk in chunks:
        assert "<span" not in chunk


def test_malformed_html_does_not_crash():
    """Extra closing tags, mismatched pairs, and stray fragments must
    not raise; the splitter falls back to a plain-text chunking.
    """
    cases = [
        "</b>orphan",          # close with no opener
        "<b></i>",             # mismatched pair
        "<b><b></b>",          # unclosed outer
        "<<<>>>",              # not really HTML
        "<b" + "x" * 10,       # truncated open tag
    ]
    max_len = 200
    for text in cases:
        # Build a longer payload by repeating the malformed fragment
        # so the chunker is actually invoked.
        long_text = (text + " ") * 50
        chunks = split_html_text(long_text, max_len=max_len)
        assert chunks, f"empty result for {text!r}"
        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= max_len


def test_to_plain_text_strips_tags_and_unescapes_entities():
    """``to_plain_text`` must return text with all tags removed and
    all HTML entities decoded. This is the final fallback when HTML
    cannot be sent.
    """
    assert to_plain_text("<b>bold</b> and <i>italic</i>") == "bold and italic"
    assert to_plain_text("a &amp; b &lt; c &gt; d &quot;e&quot;") == 'a & b < c > d "e"'
    # None-ish input is tolerated.
    assert to_plain_text(None) == ""  # type: ignore[arg-type]
    assert to_plain_text("") == ""


# ─── split_html_text — defensive edges ─────────────────────────────────────


def test_none_input_returns_empty_chunk():
    """A None input is converted to a single empty chunk so callers
    can always iterate without checking for None.
    """
    assert split_html_text(None) == [""]  # type: ignore[arg-type]


def test_exact_boundary_does_not_split():
    """An input whose UTF-8 size equals max_len is returned as a
    single chunk — no premature split.
    """
    text = "a" * 3900
    assert len(text.encode("utf-8")) == 3900
    assert split_html_text(text, max_len=3900) == [text]


def test_unicode_text_respects_byte_budget():
    """Emoji and other multi-byte characters count as multiple bytes
    against the cap, so a Unicode-only input is still bounded.
    """
    text = "🐍" * 5000  # 4 bytes per char → ~20 KB
    max_len = 1000
    chunks = split_html_text(text, max_len=max_len)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= max_len
