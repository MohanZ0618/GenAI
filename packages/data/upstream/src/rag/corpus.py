"""Frozen operational-corpus loading, eligibility, identity, and persistence."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from src.rag.artifacts import canonical_json, sha256_bytes, sha256_file, write_json, write_jsonl
from src.rag.config import (
    AVAILABILITY_FIELDS,
    CORPUS_VERSION,
    DECISION_CUTOFF,
    EMBEDDING_INPUT_LIMIT,
    EXPECTED_DOCUMENT_COUNT,
    EXPECTED_SOURCE_FILES,
    EXPECTED_SOURCE_MANIFEST_SHA256,
    EXPECTED_TEXT_MANIFEST_SHA256,
    RECORD_TYPES,
)
from src.rag.leakage import OpenedPathAudit, assert_payload_label_blind, assert_source_registry
from src.rag.serialization import canonical_record_id, serialize_record
from src.rag.tokens import embedding_token_count, percentile
from src.schema import PRIMARY_KEYS, TABLE_SCHEMAS


@dataclass(frozen=True)
class CorpusDocument:
    record_id: str
    record_type: str
    source_table: str
    source_file: str
    available_at: str
    source_system: str
    relational_ids: dict[str, str]
    ordinal: int
    text: str
    text_sha256: str
    row: dict[str, str]

    def metadata(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "source_table": self.source_table,
            "source_file": self.source_file,
            "available_at": self.available_at,
            "source_system": self.source_system,
            "primary_key": {field: self.row[field] for field in PRIMARY_KEYS[self.source_table]},
            "relational_ids": self.relational_ids,
            "corpus_version": CORPUS_VERSION,
            "document_sha256": self.text_sha256,
            "document_ordinal": self.ordinal,
        }

    def artifact_row(self) -> dict[str, Any]:
        return {**self.metadata(), "text": self.text}


@dataclass
class FrozenCorpus:
    documents: list[CorpusDocument]
    raw_tables: dict[str, list[dict[str, str]]]
    eligible_rows: dict[str, list[dict[str, str]]]
    source_audit: dict[str, Any]
    text_manifest_sha256: str
    opened_path_audit: OpenedPathAudit

    def by_record_id(self) -> dict[str, CorpusDocument]:
        return {document.record_id: document for document in self.documents}

    def primary_lookup(self, table: str, field: str, value: str) -> list[CorpusDocument]:
        return [document for document in self.documents if document.source_table == table and document.row[field] == value]


def _strict_available(value: str, *, table: str, field: str) -> bool:
    if not value:
        raise RuntimeError(f"empty availability value: table={table} field={field}")
    try:
        observed = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise RuntimeError(f"invalid availability value: table={table} field={field} value={value!r}") from exc
    return observed <= date.fromisoformat(DECISION_CUTOFF)


def _source_manifest(data_dir: Path, audit: OpenedPathAudit) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    rows_by_table: dict[str, list[dict[str, str]]] = {}
    file_rows: list[dict[str, Any]] = []
    manifest_lines: list[str] = []
    first_mismatch: dict[str, Any] | None = None
    observed_names = sorted(path.name for path in data_dir.glob("*.csv"))
    expected_names = sorted(f"{table}.csv" for table in TABLE_SCHEMAS)
    if observed_names != expected_names:
        raise RuntimeError(f"operational file registry mismatch: expected={expected_names!r}, observed={observed_names!r}")

    for table, fields in TABLE_SCHEMAS.items():
        path = data_dir / f"{table}.csv"
        audit.record(path)
        digest = sha256_file(path)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert_source_registry(table, reader.fieldnames)
            rows = [dict(row) for row in reader]
        rows_by_table[table] = rows
        expected_digest, expected_count = EXPECTED_SOURCE_FILES[path.name]
        status = "PASS" if digest == expected_digest and len(rows) == expected_count else "FAIL"
        if status == "FAIL" and first_mismatch is None:
            first_mismatch = {
                "affected_file": path.name,
                "affected_table": table,
                "expected_sha256": expected_digest,
                "observed_sha256": digest,
                "expected_rows": expected_count,
                "observed_rows": len(rows),
            }
        file_rows.append({
            "file": path.name, "table": table, "sha256": digest, "rows": len(rows), "status": status,
        })

    for file_name in sorted(EXPECTED_SOURCE_FILES):
        table = file_name.removesuffix(".csv")
        row = next(item for item in file_rows if item["table"] == table)
        manifest_lines.append(f"{file_name}\t{row['sha256']}\t{row['rows']}\n")
    manifest_sha = sha256_bytes("".join(manifest_lines))
    status = "PASS" if first_mismatch is None and manifest_sha == EXPECTED_SOURCE_MANIFEST_SHA256 else "FAIL"
    result = {
        "status": status,
        "expected_manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
        "observed_manifest_sha256": manifest_sha,
        "first_mismatch": first_mismatch,
        "files": sorted(file_rows, key=lambda row: row["file"]),
    }
    if status != "PASS":
        raise RuntimeError("operational source identity failure: " + canonical_json(result))
    return result, rows_by_table


def _eligible_rows(raw: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for table, rows in raw.items():
        field = AVAILABILITY_FIELDS[table]
        if field is None:
            continue
        result[table] = [row for row in rows if _strict_available(row[field], table=table, field=field)]

    eligible_pos = {row["po_id"] for row in result["purchase_orders"]}
    result["po_lines"] = [row for row in raw["po_lines"] if row["po_id"] in eligible_pos]
    eligible_invoices = {row["invoice_id"] for row in result["invoices"]}
    result["invoice_lines"] = [row for row in raw["invoice_lines"] if row["invoice_id"] in eligible_invoices]
    eligible_payments = {row["payment_id"] for row in result["payments"]}
    result["payment_allocations"] = [
        row for row in result["payment_allocations"]
        if row["payment_id"] in eligible_payments and row["invoice_id"] in eligible_invoices
    ]
    result["employees"] = list(raw["employees"])
    return {table: result[table] for table in TABLE_SCHEMAS}


def _available_at(table: str, row: dict[str, str]) -> str:
    field = AVAILABILITY_FIELDS[table]
    if field:
        return row[field]
    if table == "po_lines":
        return "INHERITED_FROM_PURCHASE_ORDER"
    if table == "invoice_lines":
        return "INHERITED_FROM_INVOICE"
    return "DELIVERED_CUTOFF_SNAPSHOT"


def _relational_ids(row: dict[str, str]) -> dict[str, str]:
    return {
        field: value for field, value in row.items()
        if value and (field.endswith("_id") or field in {"reference_number", "payment_reference", "bank_reference"})
    }


def _documents(eligible: dict[str, list[dict[str, str]]]) -> tuple[list[CorpusDocument], str]:
    pending: list[tuple[str, str, dict[str, str], str]] = []
    for table in TABLE_SCHEMAS:
        for row in eligible[table]:
            text = serialize_record(table, row)
            assert_payload_label_blind(text, name=f"document:{canonical_record_id(table, row)}")
            pending.append((canonical_record_id(table, row), table, row, text))
    pending.sort(key=lambda item: item[0])
    documents: list[CorpusDocument] = []
    manifest_lines: list[str] = []
    for ordinal, (record_id, table, row, text) in enumerate(pending):
        digest = sha256_bytes(text)
        manifest_lines.append(f"{record_id}\t{digest}\n")
        documents.append(CorpusDocument(
            record_id=record_id,
            record_type=RECORD_TYPES[table],
            source_table=table,
            source_file=f"data/benchmark/full/{table}.csv",
            available_at=_available_at(table, row),
            source_system=row.get("source_system", ""),
            relational_ids=_relational_ids(row),
            ordinal=ordinal,
            text=text,
            text_sha256=digest,
            row=row,
        ))
    return documents, sha256_bytes("".join(manifest_lines))


def build_frozen_corpus(data_dir: Path) -> FrozenCorpus:
    audit = OpenedPathAudit("corpus_build")
    source_audit, raw = _source_manifest(data_dir.resolve(), audit)
    eligible = _eligible_rows(raw)
    documents, text_hash = _documents(eligible)
    if len(documents) != EXPECTED_DOCUMENT_COUNT or text_hash != EXPECTED_TEXT_MANIFEST_SHA256:
        diagnostic = {
            "expected_document_count": EXPECTED_DOCUMENT_COUNT,
            "observed_document_count": len(documents),
            "expected_text_manifest_sha256": EXPECTED_TEXT_MANIFEST_SHA256,
            "observed_text_manifest_sha256": text_hash,
            "first_discovered_mismatch": {
                "affected_record_id": documents[0].record_id if documents else None,
                "affected_table": documents[0].source_table if documents else None,
                "reason": "canonical corpus manifest differs after source identity passed",
            },
        }
        raise RuntimeError("eligible corpus identity failure: " + canonical_json(diagnostic))
    return FrozenCorpus(documents, raw, eligible, source_audit, text_hash, audit)


def corpus_token_audit(documents: Iterable[CorpusDocument]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        count = embedding_token_count(document.text)
        rows.append({"record_id": document.record_id, "tokens": count, "oversized": count > EMBEDDING_INPUT_LIMIT})
    counts = [row["tokens"] for row in rows]
    oversized = [row for row in rows if row["oversized"]]
    return {
        "status": "PASS" if not oversized else "FAIL",
        "tokenizer": "cl100k_base",
        "embedding_input_limit": EMBEDDING_INPUT_LIMIT,
        "document_count": len(rows),
        "minimum_tokens": min(counts, default=0),
        "maximum_tokens": max(counts, default=0),
        "median_tokens": statistics.median(counts) if counts else 0,
        "p95_tokens": percentile([float(value) for value in counts], 0.95),
        "total_tokens": sum(counts),
        "oversized_count": len(oversized),
        "oversized_record_ids": [row["record_id"] for row in oversized],
    }


def persist_corpus(corpus: FrozenCorpus, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=False)
    documents_path = output_dir / "documents.jsonl"
    metadata_path = output_dir / "metadata.jsonl"
    record_ids_path = output_dir / "record_ids.txt"
    write_jsonl(documents_path, (document.artifact_row() for document in corpus.documents), exclusive=True)
    write_jsonl(metadata_path, (document.metadata() for document in corpus.documents), exclusive=True)
    record_ids_path.write_text("".join(f"{document.record_id}\n" for document in corpus.documents), encoding="utf-8", newline="\n")
    counts = {
        table: {"raw": len(corpus.raw_tables[table]), "eligible": len(corpus.eligible_rows[table])}
        for table in TABLE_SCHEMAS
    }
    write_json(output_dir / "corpus_source_audit.json", corpus.source_audit, exclusive=True)
    write_json(output_dir / "corpus_eligibility_counts.json", counts, exclusive=True)
    return {
        "documents_sha256": sha256_file(documents_path),
        "metadata_sha256": sha256_file(metadata_path),
        "record_ids_sha256": sha256_file(record_ids_path),
        "text_manifest_sha256": corpus.text_manifest_sha256,
    }


def load_persisted_documents(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_persisted_corpus(corpus_dir: Path) -> FrozenCorpus:
    """Reconstruct and verify the frozen corpus without reopening operational CSVs."""
    audit = OpenedPathAudit("primary_inference")
    documents_path = corpus_dir / "documents.jsonl"
    source_audit_path = corpus_dir / "corpus_source_audit.json"
    audit.record(documents_path)
    audit.record(source_audit_path)
    rows = load_persisted_documents(documents_path)
    documents: list[CorpusDocument] = []
    manifest_lines: list[str] = []
    grouped: dict[str, list[dict[str, str]]] = {table: [] for table in TABLE_SCHEMAS}
    for expected_ordinal, value in enumerate(rows):
        table = str(value["source_table"])
        text = str(value["text"])
        lines = text.split("\n")
        field_lines = lines[2:]
        fields = TABLE_SCHEMAS[table]
        if len(field_lines) != len(fields):
            raise RuntimeError(f"persisted document field count mismatch: {value['record_id']}")
        row: dict[str, str] = {}
        for field, line in zip(fields, field_lines):
            prefix = f"{field.upper()}: "
            if not line.startswith(prefix):
                raise RuntimeError(f"persisted document field order mismatch: {value['record_id']}")
            parsed = json.loads(line[len(prefix):])
            if not isinstance(parsed, str):
                raise RuntimeError(f"persisted source value is not a string: {value['record_id']}")
            row[field] = parsed
        record_id = str(value["record_id"])
        digest = sha256_bytes(text)
        if (
            int(value["document_ordinal"]) != expected_ordinal
            or str(value["document_sha256"]) != digest
            or canonical_record_id(table, row) != record_id
            or serialize_record(table, row) != text
        ):
            raise RuntimeError(f"persisted canonical document verification failed: {record_id}")
        document = CorpusDocument(
            record_id=record_id,
            record_type=str(value["record_type"]),
            source_table=table,
            source_file=str(value["source_file"]),
            available_at=str(value["available_at"]),
            source_system=str(value["source_system"]),
            relational_ids={str(k): str(v) for k, v in value["relational_ids"].items()},
            ordinal=expected_ordinal,
            text=text,
            text_sha256=digest,
            row=row,
        )
        documents.append(document)
        grouped[table].append(row)
        manifest_lines.append(f"{record_id}\t{digest}\n")
    manifest_sha = sha256_bytes("".join(manifest_lines))
    if len(documents) != EXPECTED_DOCUMENT_COUNT or manifest_sha != EXPECTED_TEXT_MANIFEST_SHA256:
        raise RuntimeError("persisted corpus count/text manifest identity failure")
    source_audit = json.loads(source_audit_path.read_text(encoding="utf-8"))
    if source_audit.get("status") != "PASS":
        raise RuntimeError("persisted corpus source audit is not PASS")
    return FrozenCorpus(documents, grouped, grouped, source_audit, manifest_sha, audit)
