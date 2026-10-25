"""Load the normative RAG instruction block directly from the frozen specification."""

from __future__ import annotations

from pathlib import Path

from src.rag.artifacts import sha256_bytes, sha256_file
from src.rag.config import SPEC_RELATIVE_PATH, SPEC_SHA256


HEADING = "## 18. Frozen RAG reasoning prompt"


def load_frozen_prompt(root: Path) -> str:
    """Extract the sole text fence below Section 18 after verifying the spec identity."""
    spec_path = root / SPEC_RELATIVE_PATH
    observed = sha256_file(spec_path)
    if observed != SPEC_SHA256:
        raise RuntimeError(
            f"frozen RAG specification checksum mismatch: expected={SPEC_SHA256} observed={observed}"
        )
    source = spec_path.read_text(encoding="utf-8")
    try:
        section = source.split(HEADING, 1)[1].split("## 19.", 1)[0]
        prompt = section.split("```text\n", 1)[1].split("\n```", 1)[0]
    except (IndexError, ValueError) as exc:
        raise RuntimeError("unable to extract frozen RAG prompt from Section 18") from exc
    if not prompt or "Return exactly the structured output" not in prompt:
        raise RuntimeError("frozen RAG prompt extraction failed semantic sentinel")
    return prompt


def prompt_sha256(root: Path) -> str:
    return sha256_bytes(load_frozen_prompt(root))
