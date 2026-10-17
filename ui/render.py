"""Message sending with graceful HTML → plain-text fallback.

Extracted from the former root ``ui.py`` in Phase R3. :func:`render` is
the single entry point handlers use to edit/send a message; the chunk
splitting comes from :mod:`ui.text`.
"""

from telegram.error import BadRequest

from ui.text import split_html_text, to_plain_text


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

    async def send_chunks(target, original_text: str, parse_mode, with_markup: bool = True):
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
                await target.reply_text(chunk, reply_markup=markup, parse_mode=parse_mode)
            except BadRequest as e:
                if parse_mode is None or "too long" not in str(e).lower():
                    raise
                # HTML chunk still too long → fall back to plain text for
                # the remaining chunks (one-shot, no further retries).
                first_sent = False
                for remaining in chunks[i:]:
                    remaining_markup = reply_markup if (with_markup and not first_sent) else None
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
                    await send_chunks(query.message, plain, parse_mode=None, with_markup=True)
                else:
                    raise
        return

    message = getattr(update, "effective_message", None) or getattr(update, "message", None)

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
                    await message.reply_text(plain, reply_markup=reply_markup, parse_mode=None)
                except BadRequest as e2:
                    if "too long" in str(e2).lower():
                        await send_chunks(message, plain, parse_mode=None, with_markup=True)
                    else:
                        raise
            else:
                raise
