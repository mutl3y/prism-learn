"""Shared helpers for prism_learn reporting modules."""

from __future__ import annotations

import json
import re
from typing import Any


def require_psycopg():
    """Import psycopg lazily with a clear dependency error message."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for reporting helpers. Install it with `pip install psycopg[binary]`."
        ) from exc
    return psycopg


def coerce_json_document(value: Any) -> dict[str, Any]:
    """Return a JSON document dict from dict-or-JSON-string input."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}


def normalize_style_heading(heading: str) -> str:
    """Normalize heading text to a stable comparison key."""
    normalized = re.sub(r"[^a-z0-9()]+", " ", heading.lower()).strip()
    return re.sub(r"\s+", " ", normalized)
