"""In-memory dataset and serializable benchmark artifacts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.schema import TABLE_SCHEMAS, assert_row_schema


@dataclass
class FinanceDataset:
    """A schema-checked collection of row dictionaries."""

    tables: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {name: [] for name in TABLE_SCHEMAS}
    )

    def add(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if table not in self.tables:
            raise KeyError(f"Unknown table: {table}")
        assert_row_schema(table, row)
        self.tables[table].append(row)
        return row

    def extend(self, table: str, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.add(table, row)

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.tables[table]

    def find_one(self, table: str, field: str, value: Any) -> dict[str, Any] | None:
        return next((row for row in self.tables[table] if row.get(field) == value), None)

    def find_all(self, table: str, field: str, value: Any) -> list[dict[str, Any]]:
        return [row for row in self.tables[table] if row.get(field) == value]

    def clone(self) -> "FinanceDataset":
        return FinanceDataset(tables=deepcopy(self.tables))


@dataclass
class GenerationArtifacts:
    dataset: FinanceDataset
    clean_dataset: FinanceDataset
    cases: list[dict[str, Any]]
    causal_edges: list[dict[str, str]]
    mutation_log: list[dict[str, Any]]
    questions: list[dict[str, Any]]

