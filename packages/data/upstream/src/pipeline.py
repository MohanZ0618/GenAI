"""End-to-end FinRCA-Bench generation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.failures.hard_negatives import generate_hard_negatives
from src.failures.pipeline import inject_failures
from src.generators import generate_clean_dataset
from src.ground_truth.causal_graph_builder import build_causal_graph
from src.ground_truth.question_generator import generate_questions
from src.ground_truth.rca_builder import validate_ground_truth
from src.ground_truth.splits import assign_splits
from src.io import write_benchmark
from src.models import GenerationArtifacts
from src.reporting import build_quality_report, build_statistics_markdown
from src.validation import validate_dataset


def generate_benchmark(config: dict[str, Any], write_output: bool = True) -> tuple[GenerationArtifacts, dict[str, Any]]:
    clean, causal_edges, ids = generate_clean_dataset(config)
    clean_validation = validate_dataset(clean, clean=True)
    if not clean_validation.passed:
        sample = clean_validation.issues[:10]
        raise RuntimeError(f"Clean-data validation failed with {clean_validation.issue_count} issues: {sample}")

    benchmark = clean.clone()
    failure_cases, _, injection_context = inject_failures(benchmark, config, causal_edges, ids)
    non_failure_cases = generate_hard_negatives(injection_context, len(failure_cases) + 1)
    cases = failure_cases + non_failure_cases
    assign_splits(cases, config)
    questions = generate_questions(cases)
    causal_graph = build_causal_graph(causal_edges)
    ground_truth_validation = validate_ground_truth(benchmark, cases)
    if not ground_truth_validation.passed:
        raise RuntimeError(f"Ground-truth validation failed: {ground_truth_validation.issues[:10]}")
    quality_report = build_quality_report(clean, benchmark, cases, clean_validation, ground_truth_validation)
    statistics = build_statistics_markdown(quality_report)
    artifacts = GenerationArtifacts(
        dataset=benchmark,
        clean_dataset=clean,
        cases=cases,
        causal_edges=causal_graph,
        mutation_log=injection_context.mutation_log,
        questions=questions,
    )
    if write_output:
        write_benchmark(
            Path(str(config["output_dir"])), clean, benchmark, cases, questions, causal_graph,
            injection_context.mutation_log, quality_report, statistics, config,
        )
    return artifacts, quality_report

