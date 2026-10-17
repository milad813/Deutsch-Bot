# LTR learning flow

LTR now uses a bounded practice sequence rather than random repeated questions.

- Choose 3, 5 (recommended), or 10 words. Due unfinished words have priority;
  new words are limited by the remaining daily goal.
- New words show the article, translation and one example. Forms, collocations
  and English meanings are available under the optional details button.
- Confirming “ready to practise” records an observation without inventing a
  successful answer. Due review words are tested before revealing their answer.
- Recognition is followed by independent typed German recall. Nouns require
  the article. Reply to the current ForceReply prompt; stale replies are ignored.
  Case, whitespace and terminal punctuation are tolerated; umlaut and ß spelling
  remain significant.
- Showing options switches to assisted reverse recognition. This is logged as
  assisted practice and cannot fulfil the independent recall requirement.
- Feedback remains visible until Continue. Seeing details, continuing and
  opening hints do not artificially advance the spacing counter.
- If a valid option set cannot be built, the card is an observation, not a test.

## Parameters

`handlers/learning/ltr_session.py` owns the defaults:

| Parameter | Value | Meaning |
| --- | --- | --- |
| WORDS_PER_BATCH | 5 | Recommended session size |
| DELAY_AFTER_LEARN | 2 | Other completed learning activities before first test |
| SUCCESS_DELAY | 3 | Other completed learning activities before another successful retrieval |
| RETRY_DELAY | 2 | Other completed learning activities before retrying a mistake |
| MAX_RETRIES | 2 | Two retries after the first incorrect answer |
| MAX_ATTEMPTS_PER_WORD | 5 | Hard cap, including repeated or guided correct answers |
| MIN_SUCCESS_TYPES | 2 | Two independent successful types, including typed recall |

One activity means confirming a new word or submitting a valid test answer.
A newly scheduled question is never forced early to empty the queue. With a
short session, some words deliberately need a later session to finish practice.
Unfinished words are due within 10 minutes (an earlier existing due date is
preserved). Previously successful recognition can carry across sessions; guided
answers and successes before the latest error do not carry forward.

## Scoring and persistence

Same-session LTR success is capped at SRS Good, including for familiar words.
Completion means initial practice, not long-term mastery. The summary separates
attempt accuracy, first-answer accuracy, completed words and pending review.

Schema version 5 introduced `ltr_attempts` (question type, timestamp, answer,
correctness, guidance and unique attempt ID) and `ltr_finalizations` (durable
idempotency for SRS/XP finalization). Existing tables and vocabulary are retained.
Each attempt is committed together with its skill and mistake records. Each
word's final SRS/XP update and finalization marker share a transaction.

These defaults are an initial design, not empirically optimized coefficients.
Evaluate independent recall after one day and one week, together with session
completion and time spent; same-session accuracy alone cannot validate them.

## Validation

`tests/test_ltr_learning_experience.py` exercises complete 3/5/10-word sessions,
spacing, all-wrong sessions, hints, typed replies through the text handler,
stale callbacks, insufficient options, partial exits, resuming due words after
the daily goal, single-word review, transactional failures and duplicate
finalization after cached session-state loss.

Manual Telegram check after restarting the bot:

1. Open daily learning and choose five words.
2. Open details, play pronunciation, and confirm readiness.
3. Answer recognition questions; verify feedback waits for Continue.
4. Reply to the current recall prompt with article plus noun.
5. Try a previous reply and a previous answer button; neither should score.
6. Use the hint and verify it is identified as assisted practice.
7. Exit partway through; confirmed words should remain scheduled.
8. Return after the due time and select a session; unfinished words should be
   tested before their answers are revealed, including a single pending word.

Automated tests use Telegram doubles. Live Telegram rendering still needs the
manual check above; no live bot was started as part of this change.

Schema version 6 adds atomic version-tracked upgrades without changing these
LTR tables. Shared navigation now finalizes LTR work before clearing the session.
