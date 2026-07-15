"""Deterministic user-prompt compaction at the provider boundary."""

from __future__ import annotations

import json
from typing import Any


def fit_user_prompt_to_budget(user: str, *, max_chars: int) -> str:
    """Keep an LLM user message valid and bounded without hiding truncation."""
    budget = max(256, int(max_chars))
    if len(user) <= budget:
        return user

    metadata = {
        "truncated": True,
        "original_chars": len(user),
        "max_chars": budget,
    }
    try:
        parsed = json.loads(user)
    except (json.JSONDecodeError, TypeError):
        return _preview_envelope(user, metadata=metadata, budget=budget)

    if not isinstance(parsed, dict):
        return _preview_envelope(user, metadata=metadata, budget=budget)

    limits = (
        (max(256, budget // 2), 30),
        (max(192, budget // 3), 20),
        (max(128, budget // 5), 12),
        (96, 6),
    )
    for string_limit, list_limit in limits:
        compacted = _compact_value(
            parsed,
            string_limit=string_limit,
            list_limit=list_limit,
        )
        compacted["_context_budget"] = metadata
        serialized = _serialize(compacted)
        if len(serialized) <= budget:
            return serialized

    return _preview_envelope(user, metadata=metadata, budget=budget)


def _compact_value(value: Any, *, string_limit: int, list_limit: int) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, string_limit)
    if isinstance(value, list):
        return [
            _compact_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
            )
            for item in value[:list_limit]
        ]
    if isinstance(value, dict):
        return {
            str(key): _compact_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
            )
            for key, item in value.items()
        }
    return value


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = f"…[truncated {len(value) - limit} chars]"
    prefix_length = max(0, limit - len(marker))
    return f"{value[:prefix_length]}{marker}"


def _preview_envelope(
    user: str,
    *,
    metadata: dict[str, int | bool],
    budget: int,
) -> str:
    envelope: dict[str, Any] = {
        "_context_budget": metadata,
        "payload_preview": "",
    }
    empty_length = len(_serialize(envelope))
    preview_limit = max(0, budget - empty_length)
    envelope["payload_preview"] = _truncate_text(user, preview_limit)
    serialized = _serialize(envelope)
    while len(serialized) > budget and envelope["payload_preview"]:
        overflow = len(serialized) - budget
        envelope["payload_preview"] = envelope["payload_preview"][: -overflow - 1]
        serialized = _serialize(envelope)
    return serialized[:budget]


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
