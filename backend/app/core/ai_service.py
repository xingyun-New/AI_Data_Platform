"""Unified DashScope AI service — OpenAI-compatible wrapper with retry and chunking."""

import asyncio
import json
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

# Threshold for chunking large documents (characters)
LARGE_DOC_THRESHOLD = 10000
CHUNK_SIZE = 5000


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


def _split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks at paragraph/section boundaries.

    Tries to split at Markdown headings (##, ###) or blank lines to avoid
    breaking content in the middle of a sentence or code block.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > chunk_size:
        # Try to find a good split point near chunk_size
        search_start = max(0, chunk_size - 500)
        search_end = min(len(remaining), chunk_size + 500)

        split_pos = -1

        # Priority 1: Split at ## heading
        for m in re.finditer(r'\n## ', remaining[search_start:search_end]):
            split_pos = search_start + m.start() + 1
        if split_pos == -1:
            # Priority 2: Split at ### heading
            for m in re.finditer(r'\n### ', remaining[search_start:search_end]):
                split_pos = search_start + m.start() + 1
        if split_pos == -1:
            # Priority 3: Split at double newline
            for m in re.finditer(r'\n\n', remaining[search_start:search_end]):
                split_pos = search_start + m.start() + 1
        if split_pos == -1:
            # Fallback: split at single newline
            for m in re.finditer(r'\n', remaining[search_start:search_end]):
                split_pos = search_start + m.start() + 1

        if split_pos == -1:
            # Last resort: hard split at chunk_size
            split_pos = chunk_size

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:]

    if remaining:
        chunks.append(remaining)

    return chunks


async def call_ai(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries: int = 3,
    response_format: dict | None = None,
) -> str:
    """Send a request to the DashScope AI model with exponential backoff retry.

    Args:
        prompt_file: Filename in prompts/ used as the system message.
        user_content: The user message (e.g. document text).
        extra_system: Additional system instructions appended after the prompt.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.
        retries: Number of retry attempts on transient failures.
        response_format: Optional response format (e.g. {"type": "json_object"}).

    Returns:
        The raw text response from the model.
    """
    system_prompt = load_prompt(prompt_file)
    if extra_system:
        system_prompt = f"{system_prompt}\n\n{extra_system}"

    client = _get_client()
    last_error = None

    # Calculate dynamic max_tokens based on input length (1 token ≈ 4 chars)
    estimated_input_tokens = len(user_content) // 4
    effective_max_tokens = max(max_tokens, estimated_input_tokens * 2)

    for attempt in range(retries):
        try:
            logger.info(
                "Calling AI model=%s prompt=%s content_len=%d max_tokens=%d attempt=%d/%d",
                settings.dashscope_model, prompt_file, len(user_content),
                effective_max_tokens, attempt + 1, retries,
            )

            kwargs = {
                "model": settings.dashscope_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = await client.chat.completions.create(**kwargs)
            result = response.choices[0].message.content or ""
            logger.info("AI response length=%d", len(result))
            return result

        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                wait_time = 2 ** attempt
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


def _extract_json_from_response(raw: str) -> dict:
    """Extract and parse JSON from AI response with multiple fallback strategies."""

    # Strategy 1: Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code block
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

    # Strategy 3: Find JSON between first { and last }
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_str = raw[first_brace:last_brace + 1]
        # Clean up common issues: remove control characters from string values
        json_str = re.sub(r'[\x00-\x1f\x7f]', '', json_str)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Strategy 4: Try to repair escaped newlines in string values
    if first_brace != -1 and last_brace != -1:
        json_str = raw[first_brace:last_brace + 1]
        try:
            # Replace literal newlines inside JSON strings with \n
            in_string = False
            result_chars = []
            i = 0
            while i < len(json_str):
                ch = json_str[i]
                if ch == '"' and (i == 0 or json_str[i - 1] != '\\'):
                    in_string = not in_string
                if in_string and ch == '\n':
                    result_chars.append('\\n')
                elif in_string and ch == '\r':
                    result_chars.append('\\r')
                elif in_string and ch == '\t':
                    result_chars.append('\\t')
                else:
                    result_chars.append(ch)
                i += 1
            repaired = ''.join(result_chars)
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Failed to parse AI response as JSON (length={len(raw)}, "
        f"preview={raw[:200]})"
    )


async def call_ai_json(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.05,
    max_tokens: int = 4096,
) -> dict:
    """Call AI and parse the response as JSON.

    For large documents (>=10KB), splits into chunks and processes them
    sequentially (desensitization is order-dependent).
    """
    content_len = len(user_content)

    # For large documents, use chunked processing
    if content_len >= LARGE_DOC_THRESHOLD:
        return await _call_ai_json_chunked(
            prompt_file, user_content,
            extra_system=extra_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Small document: single call with JSON mode
    raw = await call_ai(
        prompt_file,
        user_content,
        extra_system=extra_system,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return _extract_json_from_response(raw)


async def _call_ai_json_chunked(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.05,
    max_tokens: int = 4096,
) -> dict:
    """Process large document in chunks for desensitization.

    Each chunk is processed independently, and the results are merged.
    The report aggregates changes from all chunks.
    """
    chunks = _split_into_chunks(user_content)
    logger.info("Large document (%d chars) split into %d chunks", len(user_content), len(chunks))

    all_results = []
    total_changes = 0
    all_changes = []

    for i, chunk in enumerate(chunks):
        logger.info("Processing chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))

        raw = await call_ai(
            prompt_file,
            chunk,
            extra_system=extra_system,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        result = _extract_json_from_response(raw)
        all_results.append(result.get("redacted_content", chunk))

        report = result.get("report", {})
        chunk_changes = report.get("changes", [])
        total_changes += report.get("total_changes", 0)
        all_changes.extend(chunk_changes)

    merged_content = "".join(all_results)
    logger.info("Chunked processing complete: total_changes=%d", total_changes)

    return {
        "redacted_content": merged_content,
        "report": {
            "total_changes": total_changes,
            "changes": all_changes,
        },
    }
