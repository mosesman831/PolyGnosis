"""OpenAI-compatible chat completions client (AI Gateway / LexGateway / OpenAI)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from polygnosis_api.config import Settings

logger = logging.getLogger("polygnosis_api.llm")


def extract_json(text: str) -> str:
    """Salvage JSON from text that may contain markdown fences or prose."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


class LLMClient:
    """Thin async/sync chat client against an OpenAI-compatible /chat/completions API."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        if not self.settings.api_key:
            logger.warning("POLYGNOSIS_API_KEY is empty — LLM calls will fail until set")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        base = self.settings.api_base_url.rstrip("/")
        return f"{base}/chat/completions"

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        *,
        temperature: float = 0.3,
        timeout: float = 300.0,
        label: str = "llm",
    ) -> str:
        """Synchronous chat completion. Returns assistant text or empty string."""
        model_id = model or self.settings.default_model
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        try:
            logger.info("[%s] calling %s", label, model_id)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(self._url(), headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return (content or "").strip()
        except Exception as exc:  # noqa: BLE001 — pipeline must degrade gracefully
            logger.error("[%s] LLM error: %s", label, exc)
            return ""

    async def acomplete(
        self,
        prompt: str,
        model: str | None = None,
        *,
        temperature: float = 0.3,
        timeout: float = 300.0,
        label: str = "llm",
    ) -> str:
        model_id = model or self.settings.default_model
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        try:
            logger.info("[%s] calling %s", label, model_id)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    self._url(), headers=self._headers(), json=payload
                )
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return (content or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] LLM error: %s", label, exc)
            return ""
