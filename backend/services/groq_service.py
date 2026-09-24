"""
Groq AI Service for Discordbot1.

Provides high-level async client integration for Groq AI models
(openai/gpt-oss-120b, qwen/qwen3.8-27b, etc.) via OpenAI-compatible REST API.
"""

import httpx
import structlog
from typing import Any

from backend.config.settings import settings

logger = structlog.get_logger(__name__)


def clean_attendance_reason(reason_str: str | None) -> str:
    """Extract and format a clean, concise reason from user text or LLM output."""
    if not reason_str or str(reason_str).strip().lower() in ("null", "none", "not specified", "undefined"):
        return "Not specified"

    import re
    text = str(reason_str).strip()

    # Remove Discord mentions
    text = re.sub(r'<@!?\d+>', '', text)
    text = re.sub(r'@\w+', '', text)

    # Iteratively strip leading action / date / filler prefixes
    prefixes = [
        r'^(im|i\'m|i am|ill|i\'ll|i will be|i\'ll be|member|user)\s+',
        r'^(taking|take|applying for|applied for|requesting)\s+(a\s+)?(leave|lateness)\s*',
        r'^(on leave|absent|coming late|running late|be late|delayed|late|leave)\s*',
        r'^(today|tomorrow|yesterday|day after tomorrow)\s*',
        r'^(on\s+|for\s+|at\s+|in\s+)?\d{4}-\d{2}-\d{2}\s*',
        r'^(on\s+|for\s+|at\s+|in\s+)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*',
        r'^(by\s+\d+\s*(mins?|minutes?|hours?|hrs?)?\s*)',
        r'^(because of|because|coz of|coz|cause of|cause|due to|as i have|as i am|as i|as|owing to|reason:?|for my|for a|for an|for|on|at|in|of)\s+',
        r'^(i have|i am|im|i\'m|a|an|my|the)\s+',
    ]

    prev_text = None
    while text != prev_text:
        prev_text = text
        for p in prefixes:
            text = re.sub(p, '', text, flags=re.IGNORECASE).strip()

    suffixes = [
        r'\s+(today|tomorrow|yesterday|day after tomorrow)$',
        r'\s+(leave|lateness|late)$',
        r'\s+(by\s+\d+\s*(mins?|minutes?|hours?|hrs?)?)$',
    ]
    for s in suffixes:
        text = re.sub(s, '', text, flags=re.IGNORECASE).strip()

    text = text.strip(" .,:-_\"'")

    if not text or text.lower() in ("leave", "late", "because", "due", "for", "as", "to", "not specified"):
        return "Not specified"

    return text[0].upper() + text[1:]


class GroqService:
    """Async client service wrapper for Groq AI API."""

    def __init__(self) -> None:
        self.api_key = getattr(settings, "GROQ_API_KEY", "")
        self.model = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
        self.base_url = getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")

    @property
    def is_configured(self) -> bool:
        """Return True if GROQ_API_KEY is configured in settings."""
        return bool(self.api_key and self.api_key != "mock-groq-key")

    async def ask(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> str:
        """
        Send a completion request to Groq AI API.

        Args:
            prompt: User question or context prompt.
            system_prompt: Optional instructions for system persona.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens in response.

        Returns:
            String response content from Groq.
        """
        if not self.is_configured:
            raise ValueError(
                "Groq API key is not configured. Please set GROQ_API_KEY in environment variables."
            )

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        logger.info("Sending request to Groq API", model=self.model, prompt_length=len(prompt))

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        content = choices[0]["message"].get("content", "").strip()
                        return content
                    raise RuntimeError("Received invalid or empty response structure from Groq API.")

                elif response.status_code == 401:
                    err_msg = "⚠️ Invalid Groq API Key. Please verify GROQ_API_KEY in .env / Render."
                    logger.error("Groq API 401 Unauthorized", details=response.text)
                    raise ValueError(err_msg)

                elif response.status_code == 429:
                    err_msg = "⚠️ Groq API rate limit reached. Please wait a moment and try again."
                    logger.warning("Groq API 429 Rate Limit", details=response.text)
                    raise RuntimeError(err_msg)

                else:
                    logger.error("Groq API error HTTP status", status=response.status_code, body=response.text)
                    raise RuntimeError(f"Groq API returned HTTP status {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                logger.error("Groq API connection timed out")
                raise TimeoutError("Request to Groq API timed out (45s). Please try again later.")
            except httpx.RequestError as re:
                logger.error("Groq API connection request error", error=str(re))
                raise ConnectionError(f"Network error communicating with Groq API: {re}")

    def _rule_based_parse_attendance_intent(self, user_text: str) -> dict[str, Any]:
        """Rule-based fallback parser for attendance (leave / late) requests when AI API is unconfigured or fails."""
        from datetime import date, timedelta
        import re

        text_lower = user_text.lower()
        today_date = date.today()
        today_iso = today_date.isoformat()

        # Keywords for lateness
        late_keywords = ["late", "delayed", "delay", "coming late", "running late", "reach late", "be late"]
        is_late = any(kw in text_lower for kw in late_keywords)

        # Keywords for leaves / absence
        leave_keywords = [
            "leave", "absent", "off", "sick", "out of station", "unable to attend",
            "not coming", "can't come", "wont come", "won't come", "cannot come",
            "holiday", "taking off", "take off", "unwell", "fever", "exam", "health"
        ]
        is_leave = any(kw in text_lower for kw in leave_keywords)

        is_req = is_late or is_leave

        # CRITICAL: Lateness takes precedence over leave!
        entry_type = "late" if is_late else "leave"

        # Date parsing
        target_date_iso = today_iso
        if "tomorrow" in text_lower:
            target_date_iso = (today_date + timedelta(days=1)).isoformat()
        elif "yesterday" in text_lower:
            target_date_iso = (today_date - timedelta(days=1)).isoformat()
        elif "day after tomorrow" in text_lower:
            target_date_iso = (today_date + timedelta(days=2)).isoformat()
        else:
            match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', user_text)
            if match:
                target_date_iso = match.group(1)
            else:
                match_dm = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b', user_text)
                if match_dm:
                    d, m, y = match_dm.groups()
                    if len(y) == 2:
                        y = f"20{y}"
                    try:
                        target_date_iso = date(int(y), int(m), int(d)).isoformat()
                    except ValueError:
                        target_date_iso = today_iso

        reason = clean_attendance_reason(user_text) if is_req else "Not specified"

        return {
            "is_attendance_request": is_req,
            "is_leave_request": is_req,
            "entry_type": entry_type,
            "date": target_date_iso,
            "leave_date": target_date_iso,
            "reason": reason,
        }

    async def parse_attendance_intent(self, user_text: str) -> dict[str, Any]:
        """
        Use Groq LLM to parse natural language leave/absence OR late requests.
        Falls back to rule-based parser if Groq API key is not configured or request fails.

        Returns dict:
          {
            "is_attendance_request": bool,
            "entry_type": "leave" | "late",
            "date": "YYYY-MM-DD" | None,
            "reason": str | None
          }
        """
        if not self.is_configured:
            logger.info("Groq API key not configured, using rule-based attendance parser")
            return self._rule_based_parse_attendance_intent(user_text)

        import json
        from datetime import date

        today = date.today().isoformat()
        system_prompt = (
            f"You are an AI assistant for a Discord Bot. "
            f"Your task is to analyze user messages mentioning the bot and extract attendance/leave/late details. "
            f"Today's date is {today}.\n\n"
            f"Return ONLY a raw JSON object with NO markdown codeblocks or extra text:\n"
            f"{{\n"
            f'  "is_attendance_request": true or false,\n'
            f'  "entry_type": "leave" or "late",\n'
            f'  "date": "YYYY-MM-DD" or null,\n'
            f'  "reason": "concise reason" or null\n'
            f"}}\n\n"
            f"Classification & Extraction Rules:\n"
            f"1. ENTRY TYPE PRIORITY:\n"
            f"   - Set entry_type='late' if user states they will be late, coming late, delayed, or running late (EVEN IF the reason is illness, exam, or fever).\n"
            f"   - Set entry_type='leave' ONLY if the user is taking a full leave / absent for the day.\n"
            f"2. ATTENDANCE REQUEST FLAG:\n"
            f"   - Set is_attendance_request=true if the user is requesting leave or reporting lateness.\n"
            f"   - Set is_attendance_request=false if it is a general chat, greeting, or non-attendance question.\n"
            f"3. REASON EXTRACTION (CRITICAL):\n"
            f"   - Extract ONLY the precise, core reason in 1-3 words (e.g., 'Fever', 'Doctor appointment', 'Exam', 'Traffic delay', 'Personal work').\n"
            f"   - DO NOT include action phrases ('im taking a leave', 'taking leave', 'i am absent'), dates ('today', 'tomorrow'), or connectors ('due to', 'because of', 'coz').\n"
            f"   - If no specific reason is given (e.g., 'im taking a leave today'), set reason=null.\n\n"
            f"Examples:\n"
            f"- Input: 'im taking a leave today due to fever'\n"
            f'  Output: {{"is_attendance_request": true, "entry_type": "leave", "date": "{today}", "reason": "Fever"}}\n'
            f"- Input: 'taking leave tomorrow for doctor appointment'\n"
            f'  Output: {{"is_attendance_request": true, "entry_type": "leave", "date": "...", "reason": "Doctor appointment"}}\n'
            f"- Input: 'im taking a leave today'\n"
            f'  Output: {{"is_attendance_request": true, "entry_type": "leave", "date": "{today}", "reason": null}}\n'
        )

        try:
            raw_response = await self.ask(
                prompt=user_text,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=300,
            )
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if len(lines) >= 2 and lines[0].startswith("```"):
                    cleaned = "\n".join(lines[1:-1]).strip()

            parsed = json.loads(cleaned)
            is_req = bool(parsed.get("is_attendance_request", False) or parsed.get("is_leave_request", False))
            entry_type = str(parsed.get("entry_type", "leave")).lower()
            if entry_type not in ("leave", "late"):
                entry_type = "leave"

            # CRITICAL: Lateness takes precedence over leave!
            text_lower = user_text.lower()
            late_keywords = ["late", "delayed", "delay", "coming late", "running late", "reach late", "be late"]
            if any(kw in text_lower for kw in late_keywords):
                entry_type = "late"

            date_val = str(parsed.get("date") or parsed.get("leave_date") or "")
            if not date_val:
                date_val = today

            raw_reason = parsed.get("reason")
            cleaned_reason = clean_attendance_reason(raw_reason if raw_reason else user_text)

            return {
                "is_attendance_request": is_req,
                "is_leave_request": is_req,  # backward compatibility alias
                "entry_type": entry_type,
                "date": date_val,
                "leave_date": date_val,       # backward compatibility alias
                "reason": cleaned_reason,
            }
        except Exception as e:
            logger.error("Failed to parse attendance intent with Groq LLM, falling back to rule parser", error=str(e), text=user_text)
            return self._rule_based_parse_attendance_intent(user_text)

    # Alias for backward compatibility
    parse_leave_intent = parse_attendance_intent


# Singleton instance
groq_service = GroqService()

