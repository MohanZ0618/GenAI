"""No-cost packet, context, secret, and frozen-artifact audits."""

from __future__ import annotations

import math
import os
import re
import statistics
from pathlib import Path
from typing import Any, Iterable

from src.direct_llm.artifacts import sha256_file
from src.direct_llm.config import (
    BASELINE_CONFIG,
    FORBIDDEN_PACKET_KEYS,
    PACKET_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
)
from src.direct_llm.output import canonical_output_schema
from src.direct_llm.packet import CasePacket, estimated_tokens, forbidden_key_paths


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower))


def context_audit(packets: Iterable[CasePacket], prompt: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    schema = canonical_output_schema()
    for packet in packets:
        chars = len(packet.serialized)
        tokens = estimated_tokens(prompt, schema, packet.serialized)
        rows.append({
            "case_id": packet.route["case_id"],
            "packet_characters": chars,
            "estimated_input_tokens": tokens,
            "record_count": packet.record_count,
            "fits_context": tokens + BASELINE_CONFIG.reserved_output_tokens <= BASELINE_CONFIG.context_window_tokens,
        })
    chars = [float(row["packet_characters"]) for row in rows]
    tokens = [float(row["estimated_input_tokens"]) for row in rows]
    failures = [row["case_id"] for row in rows if not row["fits_context"]]
    return {
        "status": "PASS" if not failures else "FAIL",
        "packet_count": len(rows),
        "token_estimator": BASELINE_CONFIG.token_estimator,
        "model_context_window_tokens": BASELINE_CONFIG.context_window_tokens,
        "reserved_output_tokens": BASELINE_CONFIG.reserved_output_tokens,
        "characters": {
            "minimum": min(chars, default=0),
            "median": statistics.median(chars) if chars else 0,
            "p95": percentile(chars, 0.95),
            "maximum": max(chars, default=0),
        },
        "estimated_input_tokens": {
            "minimum": min(tokens, default=0),
            "median": statistics.median(tokens) if tokens else 0,
            "p95": percentile(tokens, 0.95),
            "maximum": max(tokens, default=0),
            "total": sum(tokens),
        },
        "overflow_case_ids": failures,
        "truncation_applied": False,
        "semantic_retrieval_applied": False,
        "rows": rows,
    }


def packet_leakage_audit(packets: Iterable[CasePacket], snapshot_audit: dict[str, Any]) -> dict[str, Any]:
    packet_list = list(packets)
    violations = {
        packet.route["case_id"]: forbidden_key_paths(packet.value)
        for packet in packet_list
        if forbidden_key_paths(packet.value)
    }
    return {
        "status": "PASS" if not violations and snapshot_audit["status"] == "PASS" else "FAIL",
        "packet_version": PACKET_VERSION,
        "packet_count": len(packet_list),
        "forbidden_key_registry": sorted(FORBIDDEN_PACKET_KEYS),
        "violations": violations,
        "snapshot_source_audit": snapshot_audit,
        "oracle_case_entity_records_used": False,
        "ground_truth_used_by_packet_builder": False,
        "rules_or_ml_outputs_used_by_packet_builder": False,
        "semantic_retrieval_or_ranking_used": False,
    }


def secret_audit(repo_root: Path) -> dict[str, Any]:
    inspected: list[str] = []
    findings: list[str] = []
    secret_pattern = re.compile(r"(?:sk|sess)-[A-Za-z0-9_-]{12,}")
    for relative in ("src/direct_llm", "tests/direct_llm", "docs", "prompts", ".env.example"):
        base = repo_root / relative
        paths = [base] if base.is_file() else list(base.rglob("*")) if base.exists() else []
        for path in paths:
            if not path.is_file() or path.suffix in {".pyc", ".npz", ".joblib"}:
                continue
            inspected.append(str(path.relative_to(repo_root)))
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if secret_pattern.search(text):
                findings.append(str(path.relative_to(repo_root)))
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    checks = {
        "env_example_placeholder_only": env_example == "OPENAI_API_KEY=\n",
        "env_ignored": ".env\n" in gitignore and ".env.*\n" in gitignore,
        "api_key_not_required_for_preflight": True,
        "api_key_environment_name": "OPENAI_API_KEY",
        "api_key_present_in_current_environment": bool(os.environ.get("OPENAI_API_KEY")),
        "secret_like_literals_found": findings,
    }
    return {
        "status": "PASS" if checks["env_example_placeholder_only"] and checks["env_ignored"] and not findings else "FAIL",
        "checks": checks,
        "inspected_files": sorted(inspected),
    }


def verify_frozen_artifacts(repo_root: Path) -> dict[str, Any]:
    pairs = (
        (repo_root / "docs/frozen_direct_llm_baseline_spec_v1.0.md", repo_root / "docs/frozen_direct_llm_baseline_spec_v1.0.sha256"),
        (repo_root / "prompts/direct_llm_v1.0.txt", repo_root / "prompts/direct_llm_v1.0.sha256"),
    )
    rows = []
    for artifact, checksum_path in pairs:
        expected, named = checksum_path.read_text(encoding="utf-8").split()
        actual = sha256_file(artifact)
        rows.append({
            "artifact": str(artifact.relative_to(repo_root)),
            "checksum_file": str(checksum_path.relative_to(repo_root)),
            "checksum_named_file": named,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if expected == actual and named == artifact.name else "FAIL",
        })
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "artifacts": rows,
    }
