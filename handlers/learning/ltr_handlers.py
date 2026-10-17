"""LTR learning, spaced recognition and independent typed recall."""

import unicodedata
from contextlib import suppress
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from core.answer_tokens import new_answer_token, answer_index
from core.locks import callback_guard
from handlers.learning.ltr_session import (
    LTRSessionManager,
    WORDS_PER_BATCH,
    MAX_RETRIES,
    _ltr_answer_keyboard,
    _ltr_learn_keyboard,
)
from option_generator import get_wrong_options, make_options
from services import db, run_db
from ui import back_inline_keyboard, esc, render


def _actions(context, actions):
    token = context.user_data["ltr_token"]
    rows = [
        [InlineKeyboardButton(label, callback_data=f"ltr_action:{token}:{action}")]
        for label, action in actions
    ]
    rows.append([InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")])
    return InlineKeyboardMarkup(rows)


async def _choose_size(query, context, lesson_id=None):
    old = LTRSessionManager(context)
    if context.user_data.get("ltr_words"):
        await old.finalize_partial_session()
    old.clear_session()
    token = new_answer_token()
    context.user_data.update(ltr_token=token, ltr_pending_lesson=lesson_id, ltr_phase="choose")
    rows = [
        [
            InlineKeyboardButton(
                f"{n} واژه" + (" — پیشنهادی" if n == WORDS_PER_BATCH else ""),
                callback_data=f"ltr_size:{token}:{n}",
            )
            for n in (3, 5, 10)
        ],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ]
    await render(
        query,
        "📚 <b>اندازهٔ جلسه را انتخاب کن</b>\n"
        "پیشنهاد: ۵ واژه؛ ابتدا آموزش، سپس تمرین با فاصله و یادآوری بدون گزینه.\n"
        "هر زمان خواستی می‌توانی جلسه را تمام کنی.",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_study_lesson(query, context, suffix: str):
    try:
        lesson_id = int(suffix)
    except ValueError:
        return
    await _choose_size(query, context, lesson_id)


async def handle_daily_learning(query, context):
    await _choose_size(query, context)


@callback_guard("ltr_transition_lock")
async def handle_ltr_size(query, context, suffix):
    try:
        token, size = suffix.split(":")
        size = int(size)
    except ValueError:
        return
    if (
        size not in (3, 5, 10)
        or token != context.user_data.get("ltr_token")
        or context.user_data.get("ltr_phase") != "choose"
    ):
        return
    uid = query.from_user.id
    lesson = context.user_data.get("ltr_pending_lesson")
    weak = await run_db(db.words.get_ltr_due, uid, limit=size, lesson_id=lesson)
    due_ids = [word.id for word in weak]
    if lesson is None:
        goal = await run_db(db.learning.get_daily_goal, uid)
        done = await run_db(db.learning.get_today_new_words_count, uid)
        new_limit = min(size - len(weak), max(0, goal - done))
        new = (
            await run_db(db.words.get_next_unseen_words, uid, limit=new_limit) if new_limit else []
        )
    else:
        additional = (
            await run_db(
                db.words.get_weak_by_lesson,
                uid,
                lesson,
                limit=size - len(weak),
                exclude_ids=[w.id for w in weak],
            )
            if len(weak) < size
            else []
        )
        weak += additional
        new = (
            await run_db(
                db.words.get_new_word_objects,
                uid,
                lesson_id=lesson,
                limit=size - len(weak),
                exclude_ids=[w.id for w in weak],
            )
            if len(weak) < size
            else []
        )
    ltr = LTRSessionManager(context)
    if not ltr.initialize(uid, lesson, weak, new):
        await render(
            query,
            "✅ برای این انتخاب واژهٔ جدید یا نیازمند تمرینی باقی نمانده؛ "
            "می‌توانی مرورهای امروز را انجام بدهی.",
            reply_markup=back_inline_keyboard(),
        )
        return
    for word in weak + new:
        success = await run_db(db.learning.get_ltr_success_types, uid, word.id)
        # Re-establish recall in this session even for previously successful words.
        context.user_data["ltr_word_success_types"][word.id] = [
            s for s in success if s == "meaning"
        ]
    # Time has already elapsed for due words. Test them before showing their
    # answers again, even when only one word remains in the library.
    context.user_data["ltr_words_learned"] = due_ids
    context.user_data["ltr_learn_index"] = len(due_ids)
    for word_id in due_ids:
        ltr._schedule_test(word_id, due_after_progress=0)
    await _route_next_action(query, context)


async def _show_learn_word(query, context, details=False):
    ltr = LTRSessionManager(context)
    word = await ltr.get_next_word_to_learn()
    if not word:
        await _route_next_action(query, context)
        return
    if not details:
        context.user_data["ltr_token"] = new_answer_token()
    context.user_data["ltr_phase"] = "learn"
    context.user_data["current_tts_text"] = word.display_german
    progress = ltr.get_progress_info()
    parts = [
        f"📚 <b>آموزش واژهٔ {progress['learned'] + 1} از {progress['total']}</b>",
        f"آموزش: {progress['learned']}/{progress['total']} — پاسخ‌های تمرینی: {progress['attempts']}",
        "",
        f"🇩🇪 <b>{esc(word.display_german)}</b>",
        f"🇮🇷 {esc(word.persian)}",
    ]
    if word.example_de:
        parts.extend(["", f"📝 {esc(word.example_de)}"])
        if word.example_fa:
            parts.append(esc(word.example_fa))
    if details:
        if word.extra_forms_line:
            parts.append(f"📖 {esc(word.extra_forms_line)}")
        if word.collocation_line:
            parts.append(f"🔗 {esc(word.collocation_line)}")
        if word.english_meaning:
            parts.append(f"🇬🇧 {esc(word.english_meaning)}")
        if not (word.extra_forms_line or word.collocation_line or word.english_meaning):
            parts.append("جزئیات بیشتری برای این واژه ثبت نشده است.")
    await render(
        query,
        "\n".join(parts),
        reply_markup=_ltr_learn_keyboard(word.id, context.user_data["ltr_token"]),
    )


@callback_guard("ltr_learned_lock")
async def handle_ltr_learned(query, context, suffix=""):
    if context.user_data.get("ltr_phase") != "learn" or suffix != context.user_data.get(
        "ltr_token"
    ):
        return
    ltr = LTRSessionManager(context)
    word = await ltr.get_next_word_to_learn()
    if word:
        await run_db(db.learning.observe_ltr_word, query.from_user.id, word.id)
        ltr.mark_word_learned(word.id)
    await _route_next_action(query, context)


async def handle_ltr_details(query, context, suffix):
    if context.user_data.get("ltr_phase") == "learn" and suffix == context.user_data.get(
        "ltr_token"
    ):
        await _show_learn_word(query, context, details=True)


async def _show_test_question(query, context, word_id: int):
    word = await run_db(db.words.get_by_id, word_id)
    if not word:
        LTRSessionManager(context).defer_word(word_id)
        await _route_next_action(query, context)
        return
    context.user_data.update(
        ltr_current_question=word_id,
        ltr_token=new_answer_token(),
        ltr_phase="test",
        ltr_assisted=False,
        ltr_assessment=True,
    )
    context.user_data.pop(
        "current_tts_text", None
    )  # Do not expose the answer through pronunciation.
    success = context.user_data.get("ltr_word_success_types", {}).get(word_id, [])
    q_type = "recall" if "meaning" in success else "meaning"
    context.user_data["ltr_question_type"] = q_type
    if q_type == "recall":
        await _render_recall_question(query, context, word)
    else:
        await _render_meaning_question(query, context, word)


async def _render_recall_question(query, context, word):
    context.user_data["ltr_question_type"] = "recall"
    context.user_data["ltr_current_correct_text"] = word.display_german
    context.user_data["ltr_current_options"] = []
    await render(
        query,
        f"🧠 <b>بدون گزینه به یاد بیاور</b>\n🇮🇷 {esc(word.persian)}\n"
        "معادل آلمانی را بنویس؛ برای اسم، آرتیکل را هم بنویس.\n"
        "برای پاسخ، روی پیام درخواست پاسخ زیر Reply کن.",
        reply_markup=_actions(context, [("💡 نمایش گزینه‌ها", "hint"), ("نمی‌دانم", "unknown")]),
    )
    message = getattr(query, "message", None) or query.effective_message
    prompt = await message.reply_text(
        "✍️ پاسخ آلمانی را در پاسخ به همین پیام بنویس.", reply_markup=ForceReply(selective=True)
    )
    context.user_data["ltr_prompt_id"] = prompt.message_id


async def _render_meaning_question(query, context, word):
    context.user_data["ltr_question_type"] = "meaning"
    wrong = await run_db(get_wrong_options, db, word, count=3, attr_getter=lambda w: w.persian)
    options = make_options(word.persian, wrong, total=4, min_options=2)
    if not options or len(options) < 2 or word.persian not in options:
        await _render_final_fallback_question(query, context, word)
        return
    context.user_data.update(
        ltr_current_options=options,
        ltr_current_correct_index=options.index(word.persian),
        ltr_current_correct_text=word.persian,
    )
    await render(
        query,
        f"🧠 <b>معنی این واژه چیست؟</b>\n🇩🇪 <b>{esc(word.display_german)}</b>",
        reply_markup=_ltr_answer_keyboard(options, context.user_data.get("ltr_token", "")),
    )


async def _render_reverse_question(query, context, word):
    context.user_data.update(ltr_question_type="reverse", ltr_assisted=True)
    wrong = await run_db(
        get_wrong_options, db, word, count=3, attr_getter=lambda w: w.display_german
    )
    options = make_options(word.display_german, wrong, total=4, min_options=2)
    if not options or len(options) < 2:
        await _render_final_fallback_question(query, context, word)
        return
    context.user_data.update(
        ltr_current_options=options,
        ltr_current_correct_index=options.index(word.display_german),
        ltr_current_correct_text=word.display_german,
    )
    await render(
        query,
        f"💡 <b>تمرین با راهنما</b>\n🇮🇷 {esc(word.persian)}\n"
        "این پاسخ به‌عنوان یادآوری مستقل حساب نمی‌شود.",
        reply_markup=_ltr_answer_keyboard(options, context.user_data["ltr_token"]),
    )


async def _render_final_fallback_question(query, context, word):
    context.user_data.update(
        ltr_assessment=False,
        ltr_phase="observation",
        ltr_current_question=word.id,
        ltr_current_options=[],
        ltr_token=context.user_data.get("ltr_token") or new_answer_token(),
    )
    await render(
        query,
        "📖 <b>مرور آموزشی</b>\n"
        f"🇩🇪 {esc(word.display_german)} — {esc(word.persian)}\n"
        "گزینهٔ کافی برای آزمون نداریم؛ این مشاهده امتیاز یا پاسخ درست محسوب نمی‌شود. "
        "واژه برای مرور بعدی نگه داشته می‌شود.",
        reply_markup=_actions(context, [("ادامه", "observe")]),
    )


def _normalise_answer(text):
    # Preserve umlaut/ß distinctions; ignore casing, extra spaces and terminal punctuation.
    return " ".join(unicodedata.normalize("NFC", str(text)).strip().rstrip(".!?").lower().split())


_ltr_submission_guard = callback_guard("ltr_answer_lock")


@_ltr_submission_guard
async def handle_ltr_answer(query, context, suffix: str):
    if context.user_data.get("ltr_phase") != "test" or not context.user_data.get(
        "ltr_assessment", True
    ):
        return
    try:
        index = answer_index(suffix, {"answer_token": context.user_data.get("ltr_token")})
    except (ValueError, TypeError):
        await query.answer("این سؤال منقضی شده است.", show_alert=True)
        return
    options = context.user_data.get("ltr_current_options", [])
    if index < 0 or index >= len(options):
        return
    await _submit_answer(
        query, context, index == context.user_data["ltr_current_correct_index"], options[index]
    )


@_ltr_submission_guard
async def handle_ltr_typed(update, context):
    if (
        context.user_data.get("ltr_phase") != "test"
        or context.user_data.get("ltr_question_type") != "recall"
    ):
        return
    reply = update.message.reply_to_message
    if not reply or reply.message_id != context.user_data.get("ltr_prompt_id"):
        await update.message.reply_text(
            "لطفاً روی آخرین پیام درخواست پاسخ Reply کن؛ یا از دکمهٔ راهنما استفاده کن."
        )
        return
    correct = _normalise_answer(update.message.text) == _normalise_answer(
        context.user_data["ltr_current_correct_text"]
    )
    await _submit_answer(update, context, correct, update.message.text)


async def _submit_answer(target, context, correct, answer):
    ltr = LTRSessionManager(context)
    word_id = context.user_data.get("ltr_current_question")
    if not word_id:
        return
    uid = context.user_data["ltr_user_id"]
    word = await run_db(db.words.get_by_id, word_id)
    q_type = context.user_data["ltr_question_type"]
    assisted = context.user_data.get("ltr_assisted", False)
    correct_text = context.user_data["ltr_current_correct_text"]
    token = context.user_data["ltr_token"]

    def save():
        with db.transaction():
            # Unique attempt ID also prevents persistence/retry from duplicating writes.
            inserted = db.learning.record_ltr_attempt(
                uid, word_id, token, q_type, correct, assisted, answer, correct_text
            )
            if not inserted:
                return False
            db.learning.record_skill(uid, word_id, f"ltr_{q_type}", correct)
            if not correct:
                db.learning.record_mistake(
                    user_id=uid,
                    word_id=word_id,
                    skill_type=f"ltr_{q_type}",
                    quiz_type=q_type,
                    user_answer=answer,
                    correct_answer=correct_text,
                )
            return True

    if not await run_db(save):
        return
    ltr.record_test_result(word_id, correct, q_type, independent=not assisted)
    context.user_data["ltr_phase"] = "feedback"
    context.user_data.pop("ltr_prompt_id", None)
    context.user_data["ltr_token"] = new_answer_token()
    feedback = (
        "✅ درست بود!"
        if correct
        else f"🌱 هنوز نیاز به تمرین دارد.\nپاسخ درست: <b>{esc(correct_text)}</b>"
    )
    if assisted:
        feedback += "\n💡 پاسخ با راهنما؛ در مرور بعدی بدون گزینه امتحان می‌کنیم."
    if word and word.example_de:
        feedback += f"\n📝 {esc(word.example_de)}"
        if word.example_fa:
            feedback += f"\n{esc(word.example_fa)}"
    if word and word.collocation_line:
        feedback += f"\n🔗 {esc(word.collocation_line)}"
    if not correct:
        feedback += f"\nتا {MAX_RETRIES} تلاش مجدد با فاصله؛ سپس مرور بعدی."
    progress = ltr.get_progress_info()
    feedback += f"\n\nآموزش: {progress['learned']}/{progress['total']} واژه | پاسخ‌ها: {progress['attempts']}"
    if hasattr(target, "answer"):
        with suppress(Exception):
            await target.answer("درست بود!" if correct else "پاسخ درست را در پیام ببین.")
    await render(target, feedback, reply_markup=_actions(context, [("ادامهٔ تمرین", "continue")]))


@_ltr_submission_guard
async def handle_ltr_action(query, context, suffix):
    try:
        token, action = suffix.split(":")
    except ValueError:
        return
    if token != context.user_data.get("ltr_token"):
        return
    phase = context.user_data.get("ltr_phase")
    if action == "continue" and phase == "feedback":
        context.user_data["ltr_phase"] = "routing"
        await _route_next_action(query, context)
    elif action == "observe" and phase == "observation":
        LTRSessionManager(context).defer_word(context.user_data["ltr_current_question"])
        await _route_next_action(query, context)
    elif phase == "test" and context.user_data.get("ltr_question_type") == "recall":
        if action == "unknown":
            await _submit_answer(query, context, False, "(unknown)")
        elif action == "hint":
            word = await LTRSessionManager(context).get_current_question_word()
            if word:
                context.user_data.pop("ltr_prompt_id", None)
                context.user_data["ltr_token"] = new_answer_token()
                await _render_reverse_question(query, context, word)


async def _route_next_action(query, context, feedback: str = ""):
    ltr = LTRSessionManager(context)
    action = await ltr.get_next_action()
    if action == "test":
        task = ltr.get_due_test()
        await _show_test_question(query, context, task["word_id"])
    elif action == "learn":
        await _show_learn_word(query, context)
    else:
        await _show_ltr_summary(query, context)


async def _show_ltr_summary(query, context, feedback: str = ""):
    ltr = LTRSessionManager(context)
    await ltr.finalize_all_passed_words()
    summary = ltr.get_session_summary()
    parts = [
        "📊 <b>تمرین اولیهٔ این جلسه تمام شد</b>",
        f"📚 واژه‌های جلسه: {summary['total_words']}",
        f"✅ تمرین اولیهٔ کامل: {summary['passed_words']}",
        f"🌱 نیازمند ادامهٔ مرور: {summary['failed_words']}",
        f"✍️ پاسخ‌های ثبت‌شده: {summary['attempts']}",
    ]
    if summary["attempts"]:
        parts.append(f"🎯 دقت پاسخ‌ها: {summary['accuracy']}٪")
        parts.append(
            f"🎯 دقت اولین پاسخ هر واژه: {summary['first_accuracy']}٪ ({summary['first_count']} واژه)"
        )
    else:
        parts.append("هنوز آزمون معتبری انجام نشده است؛ دقت قابل محاسبه نیست.")
    parts.append("تثبیت واژه‌ها در مرورهای بعدی بررسی می‌شود.")
    if summary["failed_words"]:
        parts.append(
            "واژه‌های ناتمام حداکثر تا ۱۰ دقیقهٔ دیگر برای مرور زمان‌بندی شدند؛ "
            "اگر سررسید قبلی نزدیک‌تر باشد، همان حفظ می‌شود."
        )
    times = context.user_data.get("ltr_review_times", {})
    if times:
        next_time = min(times.values())
        remaining = max(
            0,
            (
                datetime.fromisoformat(next_time).replace(tzinfo=timezone.utc)
                - datetime.now(timezone.utc)
            ).total_seconds(),
        )
        parts.append(f"📅 نزدیک‌ترین مرور: حدود {max(1, round(remaining / 60))} دقیقهٔ دیگر")
    for wid in summary["failed_ids"][:5]:
        word = await run_db(db.words.get_by_id, wid)
        if word:
            parts.append(f"• {esc(word.display_german)} — {esc(word.persian)}")
    ltr.clear_session()
    await render(
        query,
        "\n".join(parts),
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📅 مرورهای سررسیدشده", callback_data="flashcard_due")],
                [
                    InlineKeyboardButton(
                        "🧠 یادآوری با فاصله / جلسهٔ جدید", callback_data="daily_learning"
                    )
                ],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
            ]
        ),
    )


async def handle_ltr_summary(query, context):
    if context.user_data.get("ltr_words"):
        await _show_ltr_summary(query, context)


async def handle_ltr_exit(query, context):
    ltr = LTRSessionManager(context)
    await ltr.finalize_partial_session()
    ltr.clear_session()
    await render(
        query,
        "✅ جلسه پایان یافت؛ واژه‌های دیده‌شده برای مرور بعدی ذخیره شدند.",
        reply_markup=back_inline_keyboard(),
    )


async def handle_ltr_ready(query, context):
    if context.user_data.get("ltr_words") and context.user_data.get("ltr_phase") == "learn":
        await _show_learn_word(query, context)


async def handle_ltr_review_weak(query, context):
    # Old summary buttons lead to scheduled reviews rather than immediate repetition.
    from handlers.learning.flashcard_session import start_flashcard_session

    await start_flashcard_session(query, context, only_due=True)
