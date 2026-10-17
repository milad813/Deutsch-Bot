"""Preserve completed LTR work when navigating away from a session."""

from handlers.learning.ltr_session import LTRSessionManager


async def suspend_ltr(context):
    if not context.user_data.get("ltr_words"):
        return
    session = LTRSessionManager(context)
    if (
        not isinstance(context.user_data.get("ltr_words"), list)
        or not isinstance(context.user_data.get("ltr_words_learned", []), list)
        or not isinstance(context.user_data.get("ltr_word_results", {}), dict)
    ):
        # /cancel must also recover from malformed legacy persistence.
        session.clear_session()
        return
    await session.finalize_partial_session()
    session.clear_session()
