"""Canonical direct-LLM request hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.direct_llm.config import PROMPT_VERSION, SCHEMA_VERSION, BaselineConfig
from src.direct_llm.output import canonical_output_schema


def request_hash(config: BaselineConfig, serialized_packet: str) -> str:
    value: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "model_configuration": config.serializable(),
        "serialized_case_packet": serialized_packet,
        "structured_output_schema_version": SCHEMA_VERSION,
        "structured_output_schema": json.loads(canonical_output_schema()),
    }
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
