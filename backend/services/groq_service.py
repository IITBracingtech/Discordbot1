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
        entry_type = "late" if is_late and not is_leave else "leave"

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

        return {
            "is_attendance_request": is_req,
            "is_leave_request": is_req,
            "entry_type": entry_type,
            "date": target_date_iso,
            "leave_date": target_date_iso,
            "reason": user_text.strip() if is_req else "Not specified",
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
            f'  "reason": "string reason" or null\n'
            f"}}\n\n"
            f"Rules:\n"
            f"1. Set is_attendance_request=true and entry_type='leave' if user expresses intention to take a leave, day off, or be absent.\n"
            f"2. Set is_attendance_request=true and entry_type='late' if user states they will be late, coming late, or running late.\n"
            f"3. Interpret relative dates: 'today' -> {today}, 'tomorrow' -> next calendar day, 'yesterday' -> previous day, specific dates -> YYYY-MM-DD format.\n"
            f"4. If no specific date is mentioned, default date to {today}.\n"
            f"5. Extract a concise reason. Default reason to 'Not specified' if unmentioned.\n"
            f"6. If message is not requesting a leave or reporting lateness (e.g. general greeting or question), set is_attendance_request=false."
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

            date_val = str(parsed.get("date") or parsed.get("leave_date") or "")
            if not date_val:
                date_val = today

            return {
                "is_attendance_request": is_req,
                "is_leave_request": is_req,  # backward compatibility alias
                "entry_type": entry_type,
                "date": date_val,
                "leave_date": date_val,       # backward compatibility alias
                "reason": str(parsed.get("reason")) if parsed.get("reason") else "Not specified",
            }
        except Exception as e:
            logger.error("Failed to parse attendance intent with Groq LLM, falling back to rule parser", error=str(e), text=user_text)
            return self._rule_based_parse_attendance_intent(user_text)

    # Alias for backward compatibility
    parse_leave_intent = parse_attendance_intent


# Singleton instance
groq_service = GroqService()

