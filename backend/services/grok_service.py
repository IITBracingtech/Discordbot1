"""
xAI Grok Service for Discordbot1.

Provides high-level async client integration for xAI Grok models
(grok-2-latest, grok-beta, grok-2-mini) via OpenAI-compatible REST API.
"""

import httpx
import structlog
from typing import Any

from backend.config.settings import settings

logger = structlog.get_logger(__name__)


class GrokService:
    """Async client service wrapper for xAI Grok LLM API."""

    def __init__(self) -> None:
        self.api_key = getattr(settings, "GROK_API_KEY", "")
        self.model = getattr(settings, "GROK_MODEL", "grok-2-latest")
        self.base_url = getattr(settings, "GROK_BASE_URL", "https://api.x.ai/v1").rstrip("/")

    @property
    def is_configured(self) -> bool:
        """Return True if GROK_API_KEY is configured in settings."""
        return bool(self.api_key and self.api_key != "mock-grok-key")

    async def ask(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> str:
        """
        Send a completion request to xAI Grok API.

        Args:
            prompt: User question or context prompt.
            system_prompt: Optional instructions for system persona.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens in response.

        Returns:
            String response content from Grok.
        """
        if not self.is_configured:
            raise ValueError(
                "xAI Grok API key is not configured. Please set GROK_API_KEY in environment variables."
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

        logger.info("Sending request to Grok API", model=self.model, prompt_length=len(prompt))

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        content = choices[0]["message"].get("content", "").strip()
                        return content
                    raise RuntimeError("Received invalid or empty response structure from Grok API.")

                elif response.status_code == 403:
                    err_msg = (
                        "⚠️ xAI Grok Team account has insufficient credits or license. "
                        "Please top up credits at https://console.x.ai"
                    )
                    logger.error("Grok API 403 Forbidden", details=response.text)
                    raise PermissionError(err_msg)

                elif response.status_code == 401:
                    err_msg = "⚠️ Invalid xAI Grok API Key. Please verify GROK_API_KEY in .env / Render."
                    logger.error("Grok API 401 Unauthorized", details=response.text)
                    raise ValueError(err_msg)

                elif response.status_code == 429:
                    err_msg = "⚠️ xAI Grok API rate limit reached. Please wait a moment and try again."
                    logger.warning("Grok API 429 Rate Limit", details=response.text)
                    raise RuntimeError(err_msg)

                else:
                    logger.error("Grok API error HTTP status", status=response.status_code, body=response.text)
                    raise RuntimeError(f"xAI Grok API returned HTTP status {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                logger.error("Grok API connection timed out")
                raise TimeoutError("Request to xAI Grok API timed out (45s). Please try again later.")
            except httpx.RequestError as re:
                logger.error("Grok API connection request error", error=str(re))
                raise ConnectionError(f"Network error communicating with xAI Grok API: {re}")


# Singleton instance
grok_service = GrokService()
