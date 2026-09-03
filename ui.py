import re
from html import escape, unescape
from typing import Any, Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import BadRequest

from core.callbacks import cb_safe
from models import CallbackPrefix


def esc(text) -> str:
    return escape(str(text if text is not None else ""))


def _short_label(text: str, max_len: int = 64) -> str:
    text = str(text or "")
    if len(text) <= max_len:
        return text
    return text[:max_len - 3].rstrip() + "..."


def callback_button(
    text: str,
    prefix: CallbackPrefix,
    suffix: Any = "",
) -> InlineKeyboardButton:
    """Build an ``InlineKeyboardButton`` with a length-safe callback_data.

    The label is truncated to 64 characters (Telegram's display limit for
    button text), and the callback data is routed through :func:`cb_safe`
    so that an over-long payload — for example a pathological ``lesson_id``
    or an unbounded suffix — degrades to ``"noop"`` instead of crashing
    the keyboard at send-time with ``BadRequest: Button_data_invalid``.

    Use this helper for every dynamic inline button whose
    ``callback_data`` is composed from a :class:`CallbackPrefix` plus a
    variable suffix. Static-literal buttons may keep
    ``InlineKeyboardButton(text, callback_data="foo")``.
    """
    return InlineKeyboardButton(
        text=_short_label(text, 64),
        callback_data=cb_safe(prefix, suffix),
    )


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or ""))


ALLOWED_HTML_TAGS = {"b", "i", "u", "s", "code", "pre"}


def strip_html(text: str) -> str:
    """حذف کامل تگ‌های HTML و تبدیل entityها به متن ساده."""
    return unescape(_strip_html(text))


def to_plain_text(text: str) -> str:
    """Return plain text safe to send to Telegram without HTML parsing.

    Strips every HTML tag and decodes entities (``&amp;`` → ``&``,
    ``&lt;`` → ``<`` …) so the result is safe to send with
    ``parse_mode=None``. Use this as the final fallback when the message
    cannot be sent as HTML.
    """
    return strip_html(text)


# Allowed inline/block tags supported by Telegram's HTML parser that we
# know how to balance across chunk boundaries. Anything not in this set
# will trigger the plain-text fallback path in ``split_html_text``.
_TELEGRAM_ALLOWED_INLINE_TAGS = ("b", "i", "u", "s", "code", "pre")
# Matches raw ``<b>`` / ``</b>`` etc. *after* ``sanitize_html`` has
# run. ``sanitize_html`` HTML-escapes the input and then re-unescapes
# only the allowed tag names, so the markup the splitter sees is a
# mix of raw ``<tag>`` delimiters and ``&amp;`` / ``&lt;`` / ``&gt;``
# entities for everything else. The character class excludes ``>`` so
# we never span across tags.
_TAG_RE = re.compile(
    r"</?(" + "|".join(_TELEGRAM_ALLOWED_INLINE_TAGS) + r")>",
    re.IGNORECASE,
)
# Anything that *looks* like a tag but isn't in the allow-list. Used to
# detect malformed / unsupported HTML so we can fall back gracefully
# instead of producing an unbalanced chunk. Two alternatives:
#   * raw ``<foo>`` / ``</foo>`` markup (what ``sanitize_html``
#     produces for non-allowed tags is *not* this; but the splitter is
#     robust to receiving raw markup too), and
#   * the ``&lt;foo&gt;`` HTML-escaped form.
_ANY_TAG_RE = re.compile(
    r"(?:&lt;|<\s?)(/?)[a-zA-Z][a-zA-Z0-9]{0,32}(?:\s[^<>&]{0,80}?)?(?:&gt;|>)"
)


def sanitize_html(text: str) -> str:
    """
    امن‌سازی HTML برای Telegram.
    فقط تگ‌های ساده مجاز را نگه می‌دارد.
    """
    if text is None:
        return ""

    text = str(text)

    # حذف کامل script/style
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    escaped = escape(text)

    # برگرداندن فقط تگ‌های مجاز ساده
    for tag in ALLOWED_HTML_TAGS:
        escaped = re.sub(
            rf"&lt;{tag}&gt;",
            f"<{tag}>",
            escaped,
            flags=re.IGNORECASE,
        )
        escaped = re.sub(
            rf"&lt;/{tag}&gt;",
            f"</{tag}>",
            escaped,
            flags=re.IGNORECASE,
        )

    return escaped

def _chunk_html_text(text: str, max_len: int = 3900) -> List[str]:
    # Replaced by tag-aware splitter below. See split_html_text.
    return split_html_text(text, max_len)


def _chunk_plain_text(text: str, max_len: int = 3900) -> List[str]:
    """Length-safe line/space splitter for plain text.

    Used as the fallback path inside :func:`split_html_text` when the
    input cannot be split as HTML. Behaviour is identical to the
    pre-existing line-based splitter, minus the tag balancing.
    """
    if text is None:
        return [""]
    if not isinstance(text, str):
        text = str(text)
    if len(text.encode("utf-8")) <= max_len:
        return [text]

    def _split_long_line(line: str) -> List[str]:
        """Cut a single line that's longer than ``max_len``.

        Prefers splitting on a space, falling back to a UTF-8-safe
        byte boundary if no space exists in the budget.
        """
        if len(line.encode("utf-8")) <= max_len:
            return [line]
        out: List[str] = []
        rest = line
        while rest and len(rest.encode("utf-8")) > max_len:
            encoded = rest.encode("utf-8")
            cut_point = max_len
            # Back up to the previous space.
            while cut_point > 0 and encoded[cut_point - 1 : cut_point] != b" ":
                cut_point -= 1
            if cut_point == 0:
                # No space within the budget — cut at a UTF-8 char
                # boundary at or just below ``max_len``.
                cut_point = max_len
                while (
                    cut_point > 0
                    and cut_point < len(encoded)
                    and (encoded[cut_point] & 0xC0) == 0x80
                ):
                    cut_point -= 1
                if cut_point <= 0:
                    cut_point = max_len
            out.append(encoded[:cut_point].decode("utf-8", errors="ignore"))
            rest = rest[len(out[-1]) :]
        if rest:
            out.append(rest)
        return out

    chunks: List[str] = []
    current = ""

    for line in text.split("\n"):
        # If the line itself is too long, split it first so the
        # per-line accumulator stays under budget at every step.
        for piece in _split_long_line(line):
            candidate = current + ("\n" if current else "") + piece
            if len(candidate.encode("utf-8")) <= max_len:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = piece

    if current:
        chunks.append(current)
    return chunks


def split_html_text(text: str, max_len: int = 3900) -> List[str]:
    """Split an HTML string into Telegram-safe chunks.

    The bot's :func:`render` sends long messages as several pieces,
    leaving a few hundred bytes of headroom under Telegram's 4096-byte
    cap. The previous splitter cut on newlines only, which could slice a
    chunk right in the middle of a tag pair like ``<b>foo</b>`` and
    make Telegram raise ``BadRequest: can't parse entities``.

    This splitter is tag-aware:

    * The allow-list is the same set :func:`sanitize_html` keeps:
      ``b i u s code pre``.
    * When a chunk would end while one or more allowed tags are still
      open, those tags are *closed* at the end of the chunk and
      *reopened* at the start of the next chunk, in the correct order,
      so the rendered message is identical to the unsplit original.
    * Chunks are bounded by *UTF-8 byte length*, not character length,
      to match what Telegram actually counts against its 4096-byte cap.
    * If the text contains a tag outside the allow-list, is structurally
      malformed, or the re-open sequence would itself overflow the
      budget, we fall back to chunking the *plain-text* version of the
      input. The caller is then expected to send with
      ``parse_mode=None``. The fallback never crashes and never produces
      a chunk larger than ``max_len`` bytes.

    When the HTML path succeeds, ``"".join(split_html_text(t))`` is
    always exactly ``t``.
    """
    if text is None:
        return [""]
    if not isinstance(text, str):
        text = str(text)
    if len(text.encode("utf-8")) <= max_len:
        return [text]

    # Fast pre-check: if the text contains no HTML tags at all, treat
    # it as plain text. This matches the behaviour the bot had before
    # the tag-aware rewrite and avoids running the streaming
    # accumulator for large plain payloads.
    if not _TAG_RE.search(text) and not _ANY_TAG_RE.search(text):
        return _chunk_plain_text(text, max_len)

    # Fast pre-check: detect unsupported / malformed tags so we can
    # fall back without doing any further work. The captured opener
    # tells us whether the match used ``<`` or ``&lt;`` so we can
    # strip the right prefix length.
    unsupported = False
    for match in _ANY_TAG_RE.finditer(text):
        raw = match.group(0)
        # ``raw`` is either ``&lt;...&gt;`` or ``<...>``. Strip both
        # leading opener and trailing closer, then take the first
        # identifier as the tag name.
        if raw.startswith("&lt;"):
            inner = raw[4:-4]  # strip "&lt;" / "&gt;"
        else:
            inner = raw[1:-1]  # strip "<" / ">"
        name = inner.lstrip("/").split(":", 1)[0].split(" ", 1)[0]
        if name.lower() not in _TELEGRAM_ALLOWED_INLINE_TAGS:
            unsupported = True
            break
    if unsupported:
        return _chunk_plain_text(to_plain_text(text), max_len)

    # Tokenize: alternate runs of plain text and raw allowed tags.
    # Each tag token is one of ``<tag>`` or ``</tag>``.
    tokens: List[Tuple[str, str]] = []  # (kind, value)
    pos = 0
    for m in _TAG_RE.finditer(text):
        if m.start() > pos:
            tokens.append(("text", text[pos : m.start()]))
        is_close = m.group(0).startswith("</")
        tag_name = m.group(1).lower()
        tokens.append(("close" if is_close else "open", tag_name))
        pos = m.end()
    if pos < len(text):
        tokens.append(("text", text[pos:]))

    # Structural sanity check: closing tags must match earlier opens.
    depth_counter: Dict[str, int] = {}
    unbalanced = False
    for kind, value in tokens:
        if kind == "open":
            depth_counter[value] = depth_counter.get(value, 0) + 1
        elif kind == "close":
            depth_counter[value] = depth_counter.get(value, 0) - 1
            if depth_counter[value] < 0:
                unbalanced = True
                break
    if unbalanced or any(v != 0 for v in depth_counter.values()):
        return _chunk_plain_text(to_plain_text(text), max_len)

    # Greedy accumulator. When appending the next token would overflow
    # the budget, we close any open tags, flush, and reopen them.
    chunks: List[str] = []
    open_stack: List[str] = []  # outer-most first, inner-most last
    current = ""
    current_len = 0  # bytes of `current`

    def reopen_prefix(stack: List[str]) -> Tuple[str, int]:
        prefix = "".join(f"<{t}>" for t in stack)
        return prefix, len(prefix.encode("utf-8"))

    def close_suffix(stack: List[str]) -> Tuple[str, int]:
        suffix = "".join(f"</{t}>" for t in reversed(stack))
        return suffix, len(suffix.encode("utf-8"))

    def _split_oversized_text(piece: str, reserve: int = 0) -> List[str]:
        """Break an oversized text piece at safe boundaries.

        Used when a single text token is itself larger than ``max_len``,
        e.g. a long ``<pre>...</pre>`` body. We try to cut on newlines
        first (because Telegram renders them as line breaks and
        splitting there keeps the visual structure intact), then on
        spaces, and as a last resort on raw byte boundaries aligned to
        UTF-8 character starts.

        ``reserve`` is the number of bytes the caller intends to wrap
        each fragment with (open + close tags). We use
        ``max_len - reserve`` as the effective byte budget so the
        resulting fragment + wrapper is still bounded.
        """
        effective = max(1, max_len - reserve)
        if len(piece.encode("utf-8")) <= effective:
            return [piece]
        fragments: List[str] = []
        rest = piece
        while rest and len(rest.encode("utf-8")) > effective:
            # Walk back from the byte budget to a UTF-8 character
            # start. The resulting *character* index is what we use
            # for ``rfind`` and slicing.
            encoded = rest.encode("utf-8")
            char_budget = effective
            # If the byte at ``char_budget`` is a UTF-8 continuation
            # byte (0b10xxxxxx), back up to the leading byte of the
            # same character.
            while (
                char_budget > 0
                and char_budget < len(encoded)
                and (encoded[char_budget] & 0xC0) == 0x80
            ):
                char_budget -= 1
            # Prefer newline.
            nl = rest.rfind("\n", 0, char_budget)
            if nl > 0:
                fragments.append(rest[: nl + 1])
                rest = rest[nl + 1 :]
                continue
            # Then space.
            sp = rest.rfind(" ", 0, char_budget)
            if sp > 0:
                fragments.append(rest[: sp + 1])
                rest = rest[sp + 1 :]
                continue
            # No safe boundary — cut at the character index, which
            # preserves UTF-8 boundaries.
            fragments.append(rest[:char_budget])
            rest = rest[char_budget:]
        if rest:
            fragments.append(rest)
        return fragments

    for kind, value in tokens:
        if kind == "text":
            piece = value
        else:
            piece = f"</{value}>" if kind == "close" else f"<{value}>"
        # A close tag with an empty stack is an orphan: the matching
        # opener was already balanced by the oversized-text branch
        # above. Drop it so we don't emit a stray ``</b>``.
        if kind == "close" and not open_stack:
            continue
        piece_len = len(piece.encode("utf-8"))

        # Oversized text token: split it and wrap each fragment with
        # the open tags. This is what keeps ``<pre>...</pre>`` bodies
        # safe even when the body is longer than the per-chunk budget.
        if kind == "text" and piece_len >= max_len:
            # Reserve bytes for the open + close tag wrapping so each
            # fragment + wrapper still fits under ``max_len``.
            _, reserve_close = close_suffix(open_stack)
            reserve_reopen, _ = reopen_prefix(open_stack)
            reserve = len(reserve_reopen.encode("utf-8")) + reserve_close
            fragments = _split_oversized_text(piece, reserve=reserve)
            if not fragments:
                continue
            # First fragment: append to whatever is already in
            # ``current`` (typically the opening tags from earlier
            # tokens). Subsequent fragments are emitted as fresh
            # chunks wrapped with the open/close tags.
            first = fragments[0]
            reopen_str, reopen_len = reopen_prefix(open_stack)
            close_str, _ = close_suffix(open_stack)
            wrapped_first = current + first + close_str
            wrapped_first_len = current_len + len(first.encode("utf-8")) + len(
                close_str.encode("utf-8")
            )
            if wrapped_first_len <= max_len:
                chunks.append(wrapped_first)
            else:
                # Even the first fragment overflows after wrapping.
                # Close off whatever tags are already in ``current``
                # and emit the fragment as its own balanced chunk.
                if current:
                    prior_close, _ = close_suffix(open_stack)
                    chunks.append(current + prior_close)
                chunks.append(reopen_str + first + close_str)
            # Remaining fragments: each is a balanced chunk.
            for frag in fragments[1:]:
                wrapped = reopen_str + frag + close_str
                if len(wrapped.encode("utf-8")) > max_len:
                    chunks.append(frag)
                else:
                    chunks.append(wrapped)
            current = ""
            current_len = 0
            # Each wrapped fragment already closes the surrounding
            # tags, so the structural open ``<b>`` (and any other
            # tags in the stack) is now balanced. Clear the stack so
            # the next ``</b>`` close tag doesn't double-close.
            open_stack = []
            continue

        # Non-text piece larger than the budget: legacy fallback,
        # emit it alone. (Single tag is at most a few bytes, so this
        # branch is essentially unreachable for well-formed input.)
        if piece_len >= max_len:
            if current:
                close_str, _ = close_suffix(open_stack)
                chunks.append(current + close_str)
                current = ""
                current_len = 0
            chunks.append(piece)
            if kind == "open":
                open_stack.append(value)
            elif kind == "close" and open_stack and open_stack[-1] == value:
                open_stack.pop()
            continue

        # Predict the open_stack *after* consuming this piece so we can
        # account for the re-open overhead at the next chunk boundary.
        next_stack = list(open_stack)
        if kind == "open":
            next_stack.append(value)
        elif kind == "close" and next_stack and next_stack[-1] == value:
            next_stack.pop()

        close_str, close_len = close_suffix(open_stack)
        reopen_str, reopen_len = reopen_prefix(next_stack)

        if current_len + piece_len + close_len > max_len or reopen_len >= max_len:
            # Flush current with closing tags, then start a new chunk
            # with the reopen prefix and append the piece.
            chunks.append(current + close_str)
            current = reopen_str + piece
            current_len = reopen_len + piece_len
            open_stack = next_stack
            continue

        current += piece
        current_len += piece_len
        if kind == "open":
            open_stack.append(value)
        elif kind == "close" and open_stack and open_stack[-1] == value:
            open_stack.pop()

    if current:
        if open_stack:
            close_str, _ = close_suffix(open_stack)
            chunks.append(current + close_str)
        else:
            chunks.append(current)
    return chunks


def progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(ratio * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _bold_word_in_sentence(sentence: str, word: str) -> str:
    """بولد کردن تمام رخدادهای یک کلمه در جمله."""
    if not sentence or not word:
        return esc(sentence or "")

    # پشتیبانی از پسوندهای صرف (مثل schlechten برای schlecht)
    pattern = re.compile(r"\b(" + re.escape(word) + r"[a-zäöüß]*)\b", re.IGNORECASE)

    result = []
    last_end = 0
    for match in pattern.finditer(sentence):
        result.append(esc(sentence[last_end : match.start()]))
        result.append(f"<b>{esc(match.group())}</b>")
        last_end = match.end()
    result.append(esc(sentence[last_end:]))

    return "".join(result)


def main_menu_keyboard(
    due_count: int = 0, streak: int = 0, hard_count: int = 0, is_admin: bool = False
) -> ReplyKeyboardMarkup:
    keyboard = []

    # ─── ردیف اول: برنامه‌ی تطبیقی روز (اقدام پیشنهادی) ───
    keyboard.append(["🚀 تمرین هوشمند"])

    # ─── ردیف اقدام فوری (میان‌بر مستقیم) ───
    if hard_count > 0:
        keyboard.append([f"🔥 مرور کلمات سخت ({hard_count})"])
    elif due_count > 0:
        keyboard.append([f"📅 مرور امروز ({due_count} کلمه)"])

    # ─── ردیف یادگیری ───
    keyboard.append(["📚 کتاب و درس‌ها", "🎴 فلش‌کارت"])

    # ─── ردیف تمرین و آمار ───
    keyboard.append(["🤖 کوییز", "📊 داشبورد"])

    # ─── ردیف تنظیمات و مدیریت ───
    if is_admin:
        keyboard.append(["⚙️ تنظیمات", "🛡️ پنل مدیریت"])
    else:
        keyboard.append(["⚙️ تنظیمات"])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def back_inline_keyboard(
    text: str = "🏠 منوی اصلی",
    callback_data: str = "back_to_main_menu",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=callback_data)]]
    )


def quiz_answer_keyboard(options: List[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for i, opt in enumerate(options or []):
        keyboard.append(
            [
                callback_button(
                    _short_label(opt, 64),
                    CallbackPrefix.QUIZ_ANS,
                    i,
                )
            ]
        )
    return InlineKeyboardMarkup(keyboard)


# در تابع render، جایگزین کردن _chunk_plain_text با _chunk_html_text
async def render(update, text: str, reply_markup=None):
    """Render ``text`` to ``update`` with a graceful HTML→plain-text fallback.

    Sending order:

    1. Try HTML (the default ``ParseMode`` for the bot).
    2. On ``BadRequest`` whose message contains "parse", "entities", or
       "unsupported", retry *once* as plain text (``parse_mode=None``).
    3. On ``BadRequest`` whose message contains "too long", chunk the
       message and send the pieces.  Chunks are sent as HTML, but if a
       chunk itself fails parsing we immediately fall back to plain text
       for that chunk.  There is no further retry beyond that — we never
       loop, so this cannot get stuck.
    4. The reply markup (if any) is attached to the *first* outgoing
       message only, including the first plain-text chunk.
    """
    query = getattr(update, "callback_query", None)
    if query is None and hasattr(update, "edit_message_text"):
        query = update

    async def send_chunks(
        target, original_text: str, parse_mode, with_markup: bool = True
    ):
        """Send ``original_text`` in 3900-byte chunks.

        ``parse_mode`` is forwarded verbatim (``None`` = plain text,
        ``"HTML"`` = HTML).  Markup is attached only to the first chunk
        when ``with_markup`` is true.
        """
        chunks = split_html_text(original_text, 3900)
        if not chunks:
            chunks = ["..."]

        for i, chunk in enumerate(chunks):
            markup = reply_markup if (with_markup and i == 0) else None
            try:
                await target.reply_text(
                    chunk, reply_markup=markup, parse_mode=parse_mode
                )
            except BadRequest as e:
                if parse_mode is None or "too long" not in str(e).lower():
                    raise
                # HTML chunk still too long → fall back to plain text for
                # the remaining chunks (one-shot, no further retries).
                first_sent = False
                for remaining in chunks[i:]:
                    remaining_markup = (
                        reply_markup if (with_markup and not first_sent) else None
                    )
                    try:
                        await target.reply_text(
                            remaining,
                            reply_markup=remaining_markup,
                            parse_mode=None,
                        )
                        first_sent = True
                    except BadRequest:
                        # Final guard: never let a single bad chunk loop.
                        pass
                return

    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            msg = str(e).lower()

            if "message is not modified" in msg:
                return

            if "too long" in msg:
                chunks = split_html_text(text, 3900)
                if not chunks:
                    chunks = ["..."]

                if getattr(query, "message", None):
                    try:
                        await query.edit_message_text(
                            chunks[0],
                            reply_markup=reply_markup,
                        )
                    except Exception:
                        await query.message.reply_text(
                            chunks[0],
                            reply_markup=reply_markup,
                        )

                    for chunk in chunks[1:]:
                        try:
                            await query.message.reply_text(chunk)
                        except BadRequest as chunk_err:
                            # HTML parse error in a tail chunk → plain text.
                            if any(
                                kw in str(chunk_err).lower()
                                for kw in ("parse", "entities", "unsupported")
                            ):
                                await query.message.reply_text(
                                    to_plain_text(chunk), parse_mode=None
                                )
                            else:
                                raise
                return

            # Non-length BadRequest → try a single plain-text retry.
            parse_err = any(kw in msg for kw in ("parse", "entities", "unsupported"))
            if not parse_err:
                raise

            plain = to_plain_text(text)
            try:
                if getattr(query, "message", None):
                    await query.message.reply_text(
                        plain, reply_markup=reply_markup, parse_mode=None
                    )
                else:
                    raise
            except BadRequest as e2:
                if "too long" in str(e2).lower():
                    await send_chunks(
                        query.message, plain, parse_mode=None, with_markup=True
                    )
                else:
                    raise
        return

    message = getattr(update, "effective_message", None) or getattr(
        update, "message", None
    )

    if message is None and hasattr(update, "reply_text"):
        message = update

    if message:
        try:
            await message.reply_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            msg = str(e).lower()
            if "too long" in msg:
                await send_chunks(message, text, parse_mode="HTML", with_markup=True)
                return
            if any(kw in msg for kw in ("parse", "entities", "unsupported")):
                plain = to_plain_text(text)
                try:
                    await message.reply_text(
                        plain, reply_markup=reply_markup, parse_mode=None
                    )
                except BadRequest as e2:
                    if "too long" in str(e2).lower():
                        await send_chunks(
                            message, plain, parse_mode=None, with_markup=True
                        )
                    else:
                        raise
            else:
                raise