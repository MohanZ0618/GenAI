"""Apply one isolated primary injector per failure case."""

from __future__ import annotations

from typing import Any

from src.failures.base import InjectionContext
from src.failures.registry import FAILURE_INJECTORS
from src.generators.bank_generator import rebuild_bank_statements
from src.models import FinanceDataset
from src.utils.ids import IDFactory
from src.utils.random_utils import RandomSource


def inject_failures(
    dataset: FinanceDataset,
    config: dict[str, Any],
    causal_edges: list[dict[str, str]],
    ids: IDFactory,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], InjectionContext]:
    count = int(config["scale"]["cases_per_failure"])
    ctx = InjectionContext(dataset, config, RandomSource(int(config["seed"]) + 104729), ids, causal_edges)
    cases: list[dict[str, Any]] = []
    case_number = 0
    for injector_class in FAILURE_INJECTORS:
        injector = injector_class()
        for _ in range(count):
            case_number += 1
            case_id = f"RCA_{case_number:06d}"
            cases.append(injector.inject(ctx, case_id))
    rebuild_bank_statements(dataset, config, ids)
    return cases, ctx.mutation_log, ctx

