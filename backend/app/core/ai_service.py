"""Unified DashScope AI service — OpenAI-compatible wrapper with retry logic."""

import asyncio
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
    return _client


def load_prompt(prompt_filename: str) -> str:
    """Load a system prompt from the prompts/ directory."""
    path = Path(settings.prompts_dir) / prompt_filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


async def call_ai(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 8192,
    retries: int = 3,
) -> str:
    """Send a request to the DashScope AI model with exponential backoff retry.

    Args:
        prompt_file: Filename in prompts/ used as the system message.
        user_content: The user message (e.g. document text).
        extra_system: Additional system instructions appended after the prompt
                      (e.g. department-specific desensitization rules).
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.
        retries: Number of retry attempts on transient failures.

    Returns:
        The raw text response from the model.
    """
    system_prompt = load_prompt(prompt_file)
    if extra_system:
        system_prompt = f"{system_prompt}\n\n{extra_system}"

    client = _get_client()
    last_error = None

    for attempt in range(retries):
        try:
            logger.info(
                "Calling AI model=%s prompt=%s content_len=%d attempt=%d/%d",
                settings.dashscope_model, prompt_file, len(user_content),
                attempt + 1, retries,
            )

            response = await client.chat.completions.create(
                model=settings.dashscope_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            result = response.choices[0].message.content or ""
            logger.info("AI response length=%d", len(result))
            return result

        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    "AI call failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1, retries, exc, wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "AI call failed after %d attempts: %s", retries, exc,
                )

    raise last_error or RuntimeError("AI call failed after retries")


async def call_ai_json(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 8192,
) -> dict:
    """call_ai but parse the response as JSON."""
    raw = await call_ai(
        prompt_file,
        user_content,
        extra_system=extra_system,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Robust JSON extraction
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        try:
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            return json.loads(cleaned)
        except (ValueError, json.JSONDecodeError):
            pass

    # Try to find JSON-like content between first { and last }
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(raw[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to parse AI response as JSON (length={len(raw)})")
