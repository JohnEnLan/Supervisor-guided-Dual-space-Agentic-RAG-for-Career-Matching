"""Shared pgvector text serialization."""
from __future__ import annotations


def to_pgvector(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in values) + "]"
