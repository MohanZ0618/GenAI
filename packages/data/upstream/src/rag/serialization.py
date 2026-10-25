"""Byte-stable financial-record serialization frozen in specification Section 8."""

from __future__ import annotations

import json
from typing import Mapping

from src.rag.config import RECORD_TYPES
from src.schema import PRIMARY_KEYS, TABLE_SCHEMAS


def canonical_record_id(table: str, row: Mapping[str, str]) -> str:
    try:
        values = [str(row[field]) for field in PRIMARY_KEYS[table]]
    except KeyError as exc:
        raise ValueError(f"missing primary-key field for {table}: {exc.args[0]}") from exc
    if any(not value for value in values):
        raise ValueError(f"empty primary-key component for {table}: {values!r}")
    return f"{table}:{'|'.join(values)}"


def json_string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False, separators=(",", ":"))


def serialize_record(table: str, row: Mapping[str, str]) -> str:
    expected = TABLE_SCHEMAS.get(table)
    if expected is None:
        raise KeyError(f"unknown operational table: {table}")
    if list(row) != expected:
        raise ValueError(
            f"source field order mismatch for {table}: expected={expected!r}, observed={list(row)!r}"
        )
    lines = [
        f"RECORD_TYPE: {RECORD_TYPES[table]}",
        f"RECORD_ID: {canonical_record_id(table, row)}",
    ]
    lines.extend(f"{field.upper()}: {json_string(row[field])}" for field in expected)
    return "\n".join(lines)

