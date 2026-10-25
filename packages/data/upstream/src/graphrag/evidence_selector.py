"""Path-complete selection, global record deduplication, and frozen cap enforcement."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def select_paths_and_records(
    anchor_ids: Iterable[str], ranked_paths: list[dict[str, Any]], *, cap: int = 40,
) -> dict[str, Any]:
    selected_records: list[str] = []
    selected_set: set[str] = set()
    memberships: dict[str, set[str]] = defaultdict(set)
    for record_id in anchor_ids:
        if record_id not in selected_set:
            selected_records.append(record_id)
            selected_set.add(record_id)
    if len(selected_records) > cap:
        raise RuntimeError("resolved anchors exceed frozen 40-record cap")
    selected_paths: list[str] = []
    path_status: dict[str, tuple[bool, str | None]] = {}
    dropped: set[str] = set()
    for path in ranked_paths:
        additional = [value for value in path["records"] if value not in selected_set]
        if len(selected_records) + len(additional) <= cap:
            selected_paths.append(path["path_id"])
            for record_id in path["records"]:
                memberships[record_id].add(path["path_id"])
                if record_id not in selected_set:
                    selected_records.append(record_id)
                    selected_set.add(record_id)
            path_status[path["path_id"]] = (True, None)
        else:
            dropped.update(additional)
            path_status[path["path_id"]] = (False, "COMPLETE_PATH_EXCEEDS_REMAINING_40_RECORD_BUDGET")
    record_rows = [
        {
            "record_id": record_id,
            "selected_rank": rank,
            "supporting_path_ids": sorted(memberships.get(record_id, set())),
        }
        for rank, record_id in enumerate(selected_records, start=1)
    ]
    candidate_records = sorted(set(anchor_ids) | {record_id for path in ranked_paths for record_id in path["records"]})
    return {
        "candidate_record_ids": candidate_records,
        "record_memberships": record_rows,
        "records_dropped_due_to_40_record_budget": sorted(dropped),
        "selected_path_ids": selected_paths,
        "selected_record_ids": selected_records,
        "path_status": path_status,
    }
