"""Group-aware case splitting with held-out vendor groups."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from typing import Any


SPLIT_NAMES = ("train", "validation", "test", "challenge_test")


def assign_splits(cases: list[dict[str, Any]], config: dict[str, Any]) -> None:
    """Assign every case by vendor group; cases for a vendor never cross splits."""
    split_cfg = config["splits"]
    challenge = float(split_cfg.get("challenge_fraction", 0.0))
    train = float(split_cfg["train"])
    validation = float(split_cfg["validation"])
    seed = int(config["seed"])
    for case in cases:
        group = str(case.get("group_vendor_id") or case["primary_entity"]["id"])
        digest = sha256(f"{seed}|{group}".encode()).digest()
        bucket = int.from_bytes(digest[:8], "big") / 2**64
        if bucket < challenge:
            split = "challenge_test"
        else:
            normalized = (bucket - challenge) / (1.0 - challenge)
            if normalized < train:
                split = "train"
            elif normalized < train + validation:
                split = "validation"
            else:
                split = "test"
        case["split"] = split


def leakage_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    cases_by_split: dict[str, set[str]] = defaultdict(set)
    vendors_by_split: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        cases_by_split[str(case["split"])].add(str(case["case_id"]))
        vendors_by_split[str(case["split"])].add(str(case["group_vendor_id"]))
    case_overlaps: dict[str, int] = {}
    vendor_overlaps: dict[str, int] = {}
    for index, left in enumerate(SPLIT_NAMES):
        for right in SPLIT_NAMES[index + 1:]:
            case_overlaps[f"{left}__{right}"] = len(cases_by_split[left] & cases_by_split[right])
            vendor_overlaps[f"{left}__{right}"] = len(vendors_by_split[left] & vendors_by_split[right])
    return {
        "passed": not any(case_overlaps.values()) and not any(vendor_overlaps.values()),
        "case_id_overlaps": case_overlaps,
        "primary_vendor_group_overlaps": vendor_overlaps,
        "case_counts": {name: len(cases_by_split[name]) for name in SPLIT_NAMES},
        "vendor_group_counts": {name: len(vendors_by_split[name]) for name in SPLIT_NAMES},
    }

