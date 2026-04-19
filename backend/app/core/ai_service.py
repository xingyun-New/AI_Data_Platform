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
    max_tokens: int = 8192,
    retries: int = 3,
    response_format: dict | None = None,
    model: str | None = None,
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
        model: Optional per-call model override. Defaults to ``settings.dashscope_model``.

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

    active_model = model or settings.dashscope_model

    for attempt in range(retries):
        try:
            logger.info(
                "Calling AI model=%s prompt=%s content_len=%d max_tokens=%d attempt=%d/%d",
                active_model, prompt_file, len(user_content),
                effective_max_tokens, attempt + 1, retries,
            )

            kwargs = {
                "model": active_model,
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

    # Strategy 2: Extract from markdown code block (most common)
    # Match ```json ... ``` or ``` ... ```
    code_block_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', raw, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find the outermost { ... } pair that forms valid JSON
    # Walk through the string tracking brace depth to find the complete top-level JSON
    depth = 0
    in_string = False
    escape_next = False
    start_pos = -1

    for i, ch in enumerate(raw):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            if depth == 0:
                start_pos = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start_pos >= 0:
                json_str = raw[start_pos:i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    start_pos = -1
                    continue

    # Strategy 4: Try to repair common issues in the raw string
    # Replace literal newlines in string values with \n
    if start_pos >= 0:
        json_str = raw[start_pos:]
    else:
        first_brace = raw.find("{")
        json_str = raw[first_brace:] if first_brace >= 0 else raw

    try:
        # Fix unescaped newlines/tabs inside JSON strings
        repaired = []
        in_str = False
        esc = False
        for ch in json_str:
            if esc:
                repaired.append(ch)
                esc = False
                continue
            if ch == '\\' and in_str:
                repaired.append(ch)
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
            if in_str and ch in ('\n', '\r', '\t'):
                repaired.append('\\' + ch)
            else:
                repaired.append(ch)
        return json.loads(''.join(repaired))
    except json.JSONDecodeError:
        pass

    raise ValueError(
        f"Failed to parse AI response as JSON (length={len(raw)}, "
        f"preview={raw[:300]})"
    )


async def call_ai_json(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.05,
    max_tokens: int = 4096,
    model: str | None = None,
    chunk_strategy: str = "concat",
) -> dict:
    """Call AI and parse the response as JSON.

    ``chunk_strategy`` controls what happens when the document exceeds
    ``LARGE_DOC_THRESHOLD``:

    * ``"concat"`` (default): fan-out to N parallel AI calls and concat the
      ``redacted_content`` string fields — the historical behavior tuned for
      the desensitization prompt, which is order-preserving and chunk-local.
    * ``"none"``: skip chunking entirely; send the full document in one call.
      Use this for prompts that need *global* context (e.g. index generation
      where ``summary``/``purpose`` only make sense over the entire doc).
    * ``"graph_merge"``: fan-out to N parallel AI calls and merge per-chunk
      ``entities`` / ``document_relations`` arrays with dedup, so the
      knowledge-graph extraction prompt can scale to large documents without
      losing entity coverage.

    Picking the wrong strategy is a correctness bug — the old code hard-coded
    ``concat`` so any large document routed through ``index_generate.txt`` or
    ``graph_extract.txt`` silently lost all their structured output (the
    merge function only looked for ``redacted_content`` and threw everything
    else away).
    """
    content_len = len(user_content)

    # Short-circuit: force single-call mode regardless of document size. This
    # is safe for prompts whose inputs fit comfortably into the model's
    # context window (index generation, query-side NER).
    if chunk_strategy == "none" or content_len < LARGE_DOC_THRESHOLD:
        raw = await call_ai(
            prompt_file,
            user_content,
            extra_system=extra_system,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            model=model,
        )
        return _extract_json_from_response(raw)

    if chunk_strategy == "concat":
        return await _call_ai_json_chunked_concat(
            prompt_file, user_content,
            extra_system=extra_system,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    if chunk_strategy == "graph_merge":
        return await _call_ai_json_chunked_graph(
            prompt_file, user_content,
            extra_system=extra_system,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    raise ValueError(
        f"Unknown chunk_strategy={chunk_strategy!r}. "
        "Expected one of: 'concat', 'none', 'graph_merge'."
    )


async def _process_chunks_parallel(
    prompt_file: str,
    chunks: list[str],
    *,
    extra_system: str,
    temperature: float,
    max_tokens: int,
    model: str | None,
) -> list[dict | Exception]:
    """Fan out one AI call per chunk via asyncio.gather.

    Returns a list aligned with ``chunks`` where each entry is either the
    parsed-JSON dict or the Exception raised for that chunk. Callers decide
    how to merge / fall back.
    """
    logger.info(
        "Large document (%d chars) split into %d chunks, processing in parallel",
        sum(len(c) for c in chunks), len(chunks),
    )

    async def _one(index: int, chunk: str) -> dict:
        logger.info("Processing chunk %d/%d (%d chars)", index + 1, len(chunks), len(chunk))
        raw = await call_ai(
            prompt_file,
            chunk,
            extra_system=extra_system,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            model=model,
        )
        return _extract_json_from_response(raw)

    tasks = [_one(i, chunk) for i, chunk in enumerate(chunks)]
    return await asyncio.gather(*tasks, return_exceptions=True)


async def _call_ai_json_chunked_concat(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.05,
    max_tokens: int = 4096,
    model: str | None = None,
) -> dict:
    """Chunked strategy for the desensitization prompt.

    Each chunk returns ``{redacted_content, report: {total_changes, changes}}``;
    we concat the content strings in original order and sum the reports.
    """
    chunks = _split_into_chunks(user_content)
    results = await _process_chunks_parallel(
        prompt_file, chunks,
        extra_system=extra_system, temperature=temperature,
        max_tokens=max_tokens, model=model,
    )

    merged: list[tuple[int, str, int, list]] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(
                "Chunk %d processing failed (%s), using original content as fallback",
                i, str(r)[:200],
            )
            merged.append((i, chunks[i], 0, []))
        else:
            merged.append((
                i,
                r.get("redacted_content", chunks[i]),
                r.get("report", {}).get("total_changes", 0),
                r.get("report", {}).get("changes", []),
            ))

    merged.sort(key=lambda x: x[0])
    total_changes = sum(m[2] for m in merged)
    all_changes = [c for m in merged for c in m[3]]
    merged_content = "".join(m[1] for m in merged)

    logger.info(
        "Chunked parallel processing complete (strategy=concat): %d chunks, total_changes=%d",
        len(merged), total_changes,
    )
    return {
        "redacted_content": merged_content,
        "report": {
            "total_changes": total_changes,
            "changes": all_changes,
        },
    }


def _merge_graph_chunk_results(results: list[dict | Exception]) -> dict:
    """Union-merge per-chunk {entities, document_relations} payloads.

    * Entities deduped on ``(name_casefold, type)`` with alias-union on hits;
      ``mention_count`` is intentionally *not* summed here — that counter is
      owned by ``kg_service.save_graph`` once the entity is matched against
      the canonical DB row. Keeping this merge dedup-only preserves the
      semantic "one observation per document" invariant.
    * document_relations are deduped on ``(entity_name_casefold, relation)``.
    * Failed chunks are logged and silently dropped — for graph extraction a
      partial graph is strictly better than an empty one, and falling back to
      raw text (the old behavior) was meaningless here.
    """
    merged_entities: dict[tuple[str, str], dict] = {}
    merged_rels: dict[tuple[str, str], dict] = {}

    ok_chunks = 0
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(
                "Graph chunk %d failed (%s); skipping (partial graph)",
                i, str(r)[:200],
            )
            continue
        ok_chunks += 1

        for ent in r.get("entities") or []:
            name = (ent.get("name") or "").strip()
            etype = (ent.get("type") or "other").strip().lower() or "other"
            if not name:
                continue
            key = (name.casefold(), etype)
            existing = merged_entities.get(key)
            if existing is None:
                merged_entities[key] = {
                    "name": name,
                    "type": etype,
                    "aliases": list(dict.fromkeys(ent.get("aliases") or [])),
                }
            else:
                for a in ent.get("aliases") or []:
                    if a and a not in existing["aliases"]:
                        existing["aliases"].append(a)

        for rel in r.get("document_relations") or []:
            ent_name = (rel.get("entity_name") or "").strip()
            rtype = (rel.get("relation") or "mentions").strip().lower() or "mentions"
            if not ent_name:
                continue
            key = (ent_name.casefold(), rtype)
            if key not in merged_rels:
                merged_rels[key] = {
                    "entity_name": ent_name,
                    "relation": rtype,
                }

    logger.info(
        "Chunked parallel processing complete (strategy=graph_merge): "
        "%d/%d chunks ok, entities=%d, document_relations=%d",
        ok_chunks, len(results), len(merged_entities), len(merged_rels),
    )
    return {
        "entities": list(merged_entities.values()),
        "document_relations": list(merged_rels.values()),
    }


async def _call_ai_json_chunked_graph(
    prompt_file: str,
    user_content: str,
    *,
    extra_system: str = "",
    temperature: float = 0.05,
    max_tokens: int = 4096,
    model: str | None = None,
) -> dict:
    """Chunked strategy for the graph-extract prompt.

    Each chunk returns ``{entities, document_relations}``; we union-merge
    these across chunks with dedup so large documents keep full coverage.
    """
    chunks = _split_into_chunks(user_content)
    results = await _process_chunks_parallel(
        prompt_file, chunks,
        extra_system=extra_system, temperature=temperature,
        max_tokens=max_tokens, model=model,
    )
    return _merge_graph_chunk_results(results)
