import asyncio
import json
import logging
import random
import re
from typing import Dict, List, Optional

import config
from ui import esc

logger = logging.getLogger(__name__)

MODEL = config.GROQ_MODEL


class LLMService:
    def __init__(self, db=None):
        self.db = db
        self.clients = []
        self._rr_index = 0

        if config.is_llm_available():
            try:
                from groq import Groq

                for key in config.GROQ_API_KEYS:
                    try:
                        self.clients.append(Groq(api_key=key))
                    except Exception as e:
                        logger.error("خطا در ساخت client برای یک کلید: %s", e)
                if self.clients:
                    logger.info("Groq: %d کلید آماده شد", len(self.clients))
            except ImportError:
                logger.error("groq نصب نیست")
        else:
            logger.warning("LLM در حالت آفلاین است.")

    def is_available(self) -> bool:
        return bool(self.clients) and config.is_llm_available()

    def _next_client(self):
        """Round-robin: هر بار کلید بعدی."""
        if not self.clients:
            return None
        client = self.clients[self._rr_index % len(self.clients)]
        self._rr_index += 1
        return client

    @staticmethod
    def _clean_json(content: str) -> str:
        if not content:
            return ""

        content = re.sub(
            r"^\s*```(?:json)?\s*", "", content, flags=re.IGNORECASE | re.MULTILINE
        )
        content = re.sub(r"\s*```\s*$", "", content, flags=re.MULTILINE)
        content = re.sub(r"[\uFEFF\u200B]", "", content)

        lines = content.split("\n")

        while lines and not lines[0].strip():
            lines.pop(0)

        while lines and not lines[-1].strip():
            lines.pop()

        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_quiz(
        result: dict, fallback_question: str, fallback_correct: str
    ) -> Optional[Dict]:
        if not isinstance(result, dict):
            return None

        question = str(result.get("question") or fallback_question).strip()
        question = esc(question)

        correct = str(result.get("correct_answer") or fallback_correct).strip()
        if not correct:
            return None

        raw_options = result.get("options") or []
        options = []

        for opt in raw_options:
            opt = str(opt or "").strip()
            if opt and opt not in options:
                options.append(opt)

        if correct not in options:
            options.append(correct)

        if len(options) < 4:
            return None

        if len(options) > 4:
            wrongs = [o for o in options if o != correct]
            random.shuffle(wrongs)
            options = [correct] + wrongs[:3]

        random.shuffle(options)
        return {
            "question": question,
            "options": options,
            "correct_index": options.index(correct),
            "correct_answer": correct,
        }


    async def _chat(self, system, user, temperature=None, max_tokens=None):
        if not self.clients:
            raise RuntimeError("LLM در دسترس نیست")
        temp = temperature if temperature is not None else config.GROQ_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else config.GROQ_MAX_TOKENS
        
        # 🎯 شناسایی مدل‌های Reasoning (مثل Qwen)
        is_reasoning_model = any(m in MODEL.lower() for m in ["qwen", "qwq", "deepseek"])
        
        # 🧠 ترفند پرامپت برای اطمینان از خروجی مستقیم
        if is_reasoning_model:
            user = f"/no_think\n{user}"
            system = "You output ONLY the requested content directly. Do NOT use <think> tags. " + system

        for attempt in range(len(self.clients)):
            client = self._next_client()
            if client is None:
                break
            try:
                kwargs = {
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temp,
                    "max_tokens": tokens,
                }
                
                # ✅ پارامتر رسمی Groq برای مخفی کردن <think> در Qwen 3.6
                if is_reasoning_model:
                    kwargs["extra_body"] = {"reasoning_format": "hidden"}

                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.chat.completions.create,
                        **kwargs
                    ),
                    timeout=30.0,
                )
                return response.choices[0].message.content
                
            except asyncio.TimeoutError:
                logger.warning("Groq timeout (کلید %d)، تلاش بعدی", attempt + 1)
                continue
            except Exception as e:
                error_str = str(e).lower()
                # 🛡️ لایه دفاعی ۱: اگر SDK گروک extra_body را رد کرد
                if is_reasoning_model and ("extra_body" in error_str or "unexpected keyword" in error_str or "reasoning_format" in error_str or "400" in error_str):
                    logger.info("تلاش مجدد با پاس دادن مستقیم reasoning_format (Fallback)...")
                    try:
                        kwargs.pop("extra_body", None)
                        kwargs["reasoning_format"] = "hidden"
                        response = await asyncio.wait_for(
                            asyncio.to_thread(
                                client.chat.completions.create,
                                **kwargs
                            ),
                            timeout=30.0,
                        )
                        return response.choices[0].message.content
                    except Exception as e2:
                        logger.warning("Groq خطا در تلاش دوم (کلید %d): %s", attempt + 1, e2)
                        
                        # 🛡️ لایه دفاعی ۲: حذف کامل پارامتر و پاکسازی دستی <think>
                        try:
                            kwargs.pop("reasoning_format", None)
                            response = await asyncio.wait_for(
                                asyncio.to_thread(
                                    client.chat.completions.create,
                                    **kwargs
                                ),
                                timeout=30.0,
                            )
                            content = response.choices[0].message.content
                            if content and "<think>" in content:
                                import re
                                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                            return content
                        except Exception as e3:
                            logger.warning("Groq خطا در تلاش سوم (کلید %d): %s", attempt + 1, e3)
                
                logger.warning("Groq خطا (کلید %d): %s — تلاش بعدی", attempt + 1, e)
                continue
                
        logger.warning("همه‌ی کلیدهای Groq شکست خوردند")
        return None

                   
    async def generate_quiz_question(
        self,
        word: str,
        meaning: str,
        level: str = "A1",
        user_id: int = None,
        word_id: int = None,
    ) -> Optional[Dict]:
        if not self.is_available():
            return None

        fallback_question = f"معنی کلمه '{word}' چیست؟"

        prompt = f"""Create a multiple-choice question for the German word "{word}" (meaning: {meaning}) at level {level}.
Generate 4 options in Persian. The wrong options should be semantically related.
Return ONLY valid JSON:
{{
  "question": "معنی کلمه '{word}' چیست؟",
  "options": ["گزینه صحیح", "غلط ۱", "غلط ۲", "غلط ۳"],
  "correct_answer": "گزینه صحیح"
}}"""

        try:
            content = await self._chat("You generate JSON only.", prompt)
            result = json.loads(self._clean_json(content))
            normalized = self._normalize_quiz(result, fallback_question, meaning)

            if normalized:
                normalized["type"] = "meaning"
                return normalized
        except Exception as e:
            logger.warning("خطا در تولید کوییز معنی: %s", e)

        return None

    async def generate_reverse_quiz(
        self,
        word: str,
        meaning: str,
        level: str = "A1",
        user_id: int = None,
        word_id: int = None,
    ) -> Optional[Dict]:
        if not self.is_available():
            return None

        fallback_question = f"معادل آلمانی کلمه‌ی '{meaning}' چیست؟"

        prompt = f"""Create a multiple-choice question for the Persian word "{meaning}" (German: {word}) at level {level}.
Generate 4 options in GERMAN.
Return ONLY valid JSON:
{{
  "question": "معادل آلمانی کلمه‌ی '{meaning}' چیست؟",
  "options": ["{word}", "غلط ۱", "غلط ۲", "غلط ۳"],
  "correct_answer": "{word}"
}}"""

        try:
            content = await self._chat("You generate JSON only.", prompt)
            result = json.loads(self._clean_json(content))
            normalized = self._normalize_quiz(result, fallback_question, word)

            if normalized:
                normalized["type"] = "reverse"
                return normalized
        except Exception as e:
            logger.warning("خطا در تولید کوییز معکوس: %s", e)

        return None

    async def generate_cloze_options(
        self,
        correct_word: str,
        sentence: str,
        count: int = 3,
        user_id: int = None,
        word_id: int = None,
    ) -> List[str]:
        if not self.is_available():
            return []

        prompt = f"""Generate {count} German words or short phrases that could grammatically fit into the blank in this sentence, but are WRONG in meaning.

Sentence: "{sentence}"
Correct answer: "{correct_word}"

Important:
- The wrong options should have the same grammatical form as the correct answer as much as possible.
- If the correct answer is inflected, try to produce similarly inflected wrong options.
- Keep options short.
- Do NOT include the correct answer.
- Return ONLY a JSON array of strings.

Example output:
["Option1", "Option2", "Option3"]
"""

        try:
            content = await self._chat("You generate JSON only.", prompt)
            result = json.loads(self._clean_json(content))

            if not isinstance(result, list):
                return []

            cleaned = []
            correct_lower = str(correct_word or "").strip().lower()

            for item in result:
                s = str(item or "").strip()
                if not s:
                    continue

                if s.lower() == correct_lower:
                    continue

                if s not in cleaned:
                    cleaned.append(s)

                if len(cleaned) == count:
                    break

            return cleaned

        except Exception as e:
            logger.warning("خطا در تولید گزینه‌های cloze: %s", e)
            return []

    async def generate_example_sentence(
        self, word: str, level: str = "A1"
    ) -> Optional[str]:
        if not self.is_available():
            return None

        prompt = f"""Create a simple German sentence at level {level} using the word "{word}".
Return ONLY the German sentence."""

        try:
            content = await self._chat(
                "You create simple German sentences for language learners.",
                prompt,
                temperature=0.7,
                max_tokens=100,
            )
            if not content:
                return None
            return content.strip()
        except Exception as e:
            logger.warning("خطا در تولید جمله مثال: %s", e)
            return None

    async def generate_contextual_example(
        self,
        word: str,
        article: Optional[str] = None,
        meaning: str = "",
        level: str = "A1",
    ) -> Optional[Dict]:
        if not self.is_available():
            return None
        word_display = f"{article} {word}".strip() if article else word

        interests = config.USER_INTERESTS.strip()
        interest_hint = ""
        if interests:
            interest_hint = (
                f"\n- Try to relate the sentence to these topics: {interests}"
            )

        prompt = f"""Create ONE simple German sentence at level {level} using the word "{word_display}" (meaning: {meaning}).
Requirements:
- Use a different context each time
- Keep it short
- Use correct grammatical form{interest_hint}
Return ONLY JSON:
{{
"de": "German sentence",
"fa": "Persian translation"
}}"""
        try:
            content = await self._chat(
                "You create diverse natural German sentences with Persian translations.",
                prompt,
                temperature=0.95,
                max_tokens=150,
            )
            result = json.loads(self._clean_json(content))
            if not isinstance(result, dict):
                return None
            de = str(result.get("de") or "").strip()
            fa = str(result.get("fa") or "").strip()
            if not de:
                return None
            return {"de": de, "fa": fa}
        except Exception as e:
            logger.warning("خطا در تولید مثال بافت‌مند: %s", e)
            return None

    async def explain_mistake(
        self,
        word: str,
        user_answer: str,
        correct_answer: str,
        quiz_type: str,
    ) -> str:
        if not self.is_available():
            return f"❌ جواب درست: {correct_answer}"

        prompt = f"""The user made a mistake in a German quiz. Explain briefly in Persian.
Quiz type: {quiz_type}
Word: {word}
User answer: {user_answer}
Correct answer: {correct_answer}
Return a short friendly explanation."""

        try:
            content = await self._chat(
                "You are a helpful German teacher. Explain in Persian.",
                prompt,
                temperature=0.5,
                max_tokens=150,
            )
            if not content:
                return f"❌ جواب درست: {correct_answer}"
            return content.strip()
        except Exception as e:
            logger.warning("خطا در تولید توضیح خطا: %s", e)
            return f"❌ جواب درست: {correct_answer}"
