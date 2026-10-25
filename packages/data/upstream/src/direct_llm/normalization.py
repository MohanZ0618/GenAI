"""Minimal frozen normalization for structural cross-system relationships."""

from __future__ import annotations

import re
import unicodedata


_REFERENCE_DROP = re.compile(r"[^A-Z0-9]")


def trim_id(value: object | None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def norm_reference(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).upper()
    result = _REFERENCE_DROP.sub("", normalized)
    return result or None


def norm_status(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    if not normalized:
        return None
    return " ".join(normalized.split()).upper().replace(" ", "_").replace("-", "_")
