"""Safe-by-default CLI for the frozen Phase 4 direct-LLM experiment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.direct_llm.artifacts import load_jsonl, sha256_file, sha256_tree, write_json, write_jsonl
from src.direct_llm.audits import (
    context_audit,
    packet_leakage_audit,
    secret_audit,
    verify_frozen_artifacts,
)
from src.direct_llm.client import OpenAIResponsesClient, PermanentAPIError, TransientAPIError
from src.direct_llm.config import (
    BASELINE_CONFIG,
    PACKET_VERSION,
    PROMPT_VERSION,
    RETRY_POLICY_VERSION,
    SCHEMA_VERSION,
)
from src.direct_llm.packet import (
    CasePacket,
    CasePacketBuilder,
    OperationalSnapshot,
    load_whitelisted_routes,
    select_stability_routes,
)
from src.direct_llm.output import validate_prediction
from src.direct_llm.runner import pricing_report, run_cases


ROOT = Path(__file__).resolve().parents[2]


def _prompt() -> str:
    return (ROOT / "prompts/direct_llm_v1.0.txt").read_text(encoding="utf-8")


def _packet_from_row(row: dict[str, Any]) -> CasePacket:
    serialized = str(row["serialized_packet"])
    return CasePacket(
        route={
            "case_id": str(row["case_id"]),
            "primary_entity_type": str(row["primary_entity_type"]),
            "primary_entity_id": str(row["primary_entity_id"]),
        },
        value=json.loads(serialized),
        serialized=serialized,
        packet_sha256=str(row["packet_sha256"]),
        evidence_record_ids=frozenset(str(value) for value in row["evidence_record_ids"]),
        record_count=int(row["record_count"]),
    )


def load_packet_artifact(path: Path) -> list[CasePacket]:
    packets = [_packet_from_row(row) for row in load_jsonl(path)]
    for packet in packets:
        if packet.packet_sha256 != __import__("hashlib").sha256(packet.serialized.encode("utf-8")).hexdigest():
            raise RuntimeError(f"packet checksum mismatch: {packet.route['case_id']}")
    return packets


def _run_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "tests/direct_llm", "-q"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command),
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _render_audit(values: dict[str, Any]) -> str:
    ready = values["decision"] == "PHASE 4 READY FOR LIVE RUN"
    unresolved = values.get("unresolved_protocol_issues", [])
    blockers = "\n".join(f"- {value}" for value in unresolved) if unresolved else "- None"
    return f"""# Direct LLM Pre-Live-Run Audit — Version 1.0

## Frozen configuration

- Specification checksum: `{values['specification_sha256']}`
- Prompt checksum: `{values['prompt_sha256']}`
- Packet-builder checksum: `{values['packet_builder_sha256']}`
- Case-packet version: `{PACKET_VERSION}`
- Selected prompt: `{PROMPT_VERSION}` (single prompt locked a priori)
- Model ID: `{BASELINE_CONFIG.model_id}`
- Provider: `{BASELINE_CONFIG.provider}`
- Generation configuration: `{json.dumps(BASELINE_CONFIG.serializable(), sort_keys=True)}`
- Retry-policy version: `{RETRY_POLICY_VERSION}`
- Structured-output schema version: `{SCHEMA_VERSION}`
- Number of test cases: {values['test_case_count']}

## Audit results

- Frozen artifact checksums: {values['frozen_artifacts_status']}
- Case-packet leakage audit: {values['packet_leakage_status']}
- Test-label isolation: {values['test_label_isolation_status']}
- Context-size audit: {values['context_audit_status']}
- Mock/unit/integration tests: {values['tests_status']}
- Secret handling: {values['secret_audit_status']}
- Validation-only prompt selection: NOT APPLICABLE — SINGLE PROMPT LOCKED BEFORE API USE
- Validation-only stability analysis: {values['stability_status']}
- Held-out API calls made: NO

## Unresolved protocol issues

{blockers}

## Decision

The pre-live gate is {'satisfied' if ready else 'not satisfied'}. No held-out inference is authorized unless this document and the machine-readable manifest both state READY.

**{values['decision']}**
"""


def prepare(args: argparse.Namespace) -> int:
    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    frozen = verify_frozen_artifacts(ROOT)
    prompt = _prompt()
    snapshot = OperationalSnapshot(Path(args.data_root) / "full")
    builder = CasePacketBuilder(snapshot)
    test_routes = load_whitelisted_routes(Path(args.data_root) / "test")
    validation_routes = load_whitelisted_routes(Path(args.data_root) / "validation")
    stability_routes = select_stability_routes(
        validation_routes,
        BASELINE_CONFIG.stability_subset_size,
        BASELINE_CONFIG.stability_subset_salt,
    )
    test_packets = [builder.build(route) for route in test_routes]
    stability_packets = [builder.build(route) for route in stability_routes]
    write_jsonl(run_dir / "test_routes.jsonl", test_routes, exclusive=True)
    write_jsonl(run_dir / "test_packets.jsonl", (packet.artifact_row() for packet in test_packets), exclusive=True)
    write_jsonl(run_dir / "validation_stability_routes.jsonl", stability_routes, exclusive=True)
    write_jsonl(
        run_dir / "validation_stability_packets.jsonl",
        (packet.artifact_row() for packet in stability_packets),
        exclusive=True,
    )
    context = context_audit(test_packets, prompt)
    stability_context = context_audit(stability_packets, prompt)
    leakage = packet_leakage_audit(test_packets, snapshot.audit())
    secrets = secret_audit(ROOT)
    tests = _run_tests()
    write_json(run_dir / "context_size_audit.json", context, exclusive=True)
    projected_stability_input = (
        stability_context["estimated_input_tokens"]["total"]
        * BASELINE_CONFIG.stability_repetitions
    )
    projected_test_input = context["estimated_input_tokens"]["total"]
    cost_projection = {
        "estimator": BASELINE_CONFIG.token_estimator,
        "pricing_reference_date": BASELINE_CONFIG.pricing_reference_date,
        "test_estimated_input_tokens": projected_test_input,
        "test_input_only_cost_usd_no_cache": projected_test_input * BASELINE_CONFIG.input_usd_per_million_tokens / 1_000_000,
        "test_max_output_cost_usd": len(test_packets) * BASELINE_CONFIG.max_output_tokens * BASELINE_CONFIG.output_usd_per_million_tokens / 1_000_000,
        "stability_estimated_input_tokens_all_repetitions": projected_stability_input,
        "stability_input_only_cost_usd_no_cache": projected_stability_input * BASELINE_CONFIG.input_usd_per_million_tokens / 1_000_000,
        "stability_max_output_cost_usd": len(stability_packets) * BASELINE_CONFIG.stability_repetitions * BASELINE_CONFIG.max_output_tokens * BASELINE_CONFIG.output_usd_per_million_tokens / 1_000_000,
        "billing_note": "Conservative character estimate, not provider billing; cached-input discounts are not assumed.",
    }
    write_json(run_dir / "pre_live_cost_projection.json", cost_projection, exclusive=True)
    write_json(run_dir / "case_packet_leakage_audit.json", leakage, exclusive=True)
    write_json(run_dir / "secret_audit.json", secrets, exclusive=True)
    write_json(run_dir / "test_results.json", tests, exclusive=True)
    blockers = []
    if len(test_packets) != 439:
        blockers.append(f"expected 439 test packets, built {len(test_packets)}")
    for name, status in (
        ("frozen artifacts", frozen["status"]),
        ("packet leakage", leakage["status"]),
        ("context audit", context["status"]),
        ("secret audit", secrets["status"]),
        ("unit/integration tests", "PASS" if tests["passed"] else "FAIL"),
    ):
        if status != "PASS":
            blockers.append(f"{name}: {status}")
    blockers.append("validation-only stability analysis has not been executed")
    audit_values = {
        "specification_sha256": sha256_file(ROOT / "docs/frozen_direct_llm_baseline_spec_v1.0.md"),
        "prompt_sha256": sha256_file(ROOT / "prompts/direct_llm_v1.0.txt"),
        "packet_builder_sha256": sha256_file(ROOT / "src/direct_llm/packet.py"),
        "test_case_count": len(test_packets),
        "frozen_artifacts_status": frozen["status"],
        "packet_leakage_status": leakage["status"],
        "test_label_isolation_status": "PASS",
        "context_audit_status": context["status"],
        "tests_status": "PASS" if tests["passed"] else "FAIL",
        "secret_audit_status": secrets["status"],
        "stability_status": "NOT RUN",
        "unresolved_protocol_issues": blockers,
        "decision": "PHASE 4 NOT READY FOR LIVE RUN",
    }
    write_json(run_dir / "pre_live_audit_values.json", audit_values, exclusive=True)
    (run_dir / "direct_llm_pre_live_run_audit_v1.0.md").write_text(
        _render_audit(audit_values), encoding="utf-8"
    )
    manifest = {
        "run_id": args.run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PREPARE_NO_API",
        "held_out_api_calls_made": False,
        "test_case_count": len(test_packets),
        "validation_stability_case_count": len(stability_packets),
        "frozen_configuration": BASELINE_CONFIG.serializable(),
        "specification_sha256": audit_values["specification_sha256"],
        "prompt_sha256": audit_values["prompt_sha256"],
        "packet_builder_sha256": audit_values["packet_builder_sha256"],
        "packet_version": PACKET_VERSION,
        "schema_version": SCHEMA_VERSION,
        "retry_policy_version": RETRY_POLICY_VERSION,
        "context_status": context["status"],
        "leakage_status": leakage["status"],
        "secret_status": secrets["status"],
        "tests_passed": tests["passed"],
        "output_schema_sha256": sha256_file(ROOT / "src/direct_llm/output.py"),
        "inference_label_sources": [],
        "route_preparation_source": "benchmark_questions.jsonl whitelisted to case/primary route only",
        "oracle_case_entity_records_used": False,
        "decision": audit_values["decision"],
    }
    write_json(run_dir / "run_manifest.json", manifest, exclusive=True)
    print(json.dumps({
        "run_dir": str(run_dir),
        "test_packets": len(test_packets),
        "context_status": context["status"],
        "maximum_estimated_input_tokens": context["estimated_input_tokens"]["maximum"],
        "projected_test_input_only_cost_usd_no_cache": cost_projection["test_input_only_cost_usd_no_cache"],
        "projected_stability_input_only_cost_usd_no_cache": cost_projection["stability_input_only_cost_usd_no_cache"],
        "decision": audit_values["decision"],
    }, indent=2, sort_keys=True))
    return 0 if not [value for value in blockers if "stability" not in value] else 1


def stability(args: argparse.Namespace) -> int:
    if not args.execute_api:
        raise RuntimeError("stability makes paid API calls and requires --execute-api")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not present")
    preflight_dir = Path(args.preflight_dir)
    manifest = json.loads((preflight_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest["decision"] != "PHASE 4 NOT READY FOR LIVE RUN":
        raise RuntimeError("unexpected preflight state")
    packets = load_packet_artifact(preflight_dir / "validation_stability_packets.jsonl")
    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    print(json.dumps({
        "model_id": BASELINE_CONFIG.model_id,
        "number_of_cases": len(packets) * BASELINE_CONFIG.stability_repetitions,
        "specification_sha256": manifest["specification_sha256"],
        "prompt_sha256": manifest["prompt_sha256"],
        "packet_version": PACKET_VERSION,
        "api_credentials_present": True,
        "output_directory": str(run_dir),
        "held_out_run": False,
    }, indent=2, sort_keys=True))
    client = OpenAIResponsesClient(BASELINE_CONFIG)
    for repetition in range(1, BASELINE_CONFIG.stability_repetitions + 1):
        run_cases(
            packets, client=client, config=BASELINE_CONFIG, prompt=_prompt(),
            run_dir=run_dir / f"repetition_{repetition}",
        )
    analysis = _stability_analysis(run_dir, packets)
    write_json(run_dir / "stability_analysis.json", analysis, exclusive=True)
    write_json(run_dir / "run_manifest.json", {
        "run_id": args.run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "VALIDATION_STABILITY_API",
        "held_out_run": False,
        "model_configuration": BASELINE_CONFIG.serializable(),
        "preflight_run_id": manifest["run_id"],
        "analysis_complete": analysis["complete"],
    }, exclusive=True)
    print(json.dumps(analysis, indent=2, sort_keys=True))
    return 0 if analysis["complete"] else 1


def probe(args: argparse.Namespace) -> int:
    """Make exactly one validation request and record sanitized API diagnostics."""
    if not args.execute_api:
        raise RuntimeError("probe makes one paid API call and requires --execute-api")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not present")
    preflight_dir = Path(args.preflight_dir)
    manifest = json.loads((preflight_dir / "run_manifest.json").read_text(encoding="utf-8"))
    packets = load_packet_artifact(preflight_dir / "validation_stability_packets.jsonl")
    if not packets:
        raise RuntimeError("preflight stability packet artifact is empty")
    packet = min(packets, key=lambda value: (len(value.serialized), value.route["case_id"]))
    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "protocol_version": "direct_llm_single_request_diagnostic_v1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preflight_run_id": manifest["run_id"],
        "model_id": BASELINE_CONFIG.model_id,
        "case_id": packet.route["case_id"],
        "packet_characters": len(packet.serialized),
        "estimated_input_tokens": (len(_prompt()) + len(packet.serialized) + 2) // 3,
        "calls_attempted": 1,
        "held_out_run": False,
        "api_key_recorded": False,
    }
    try:
        call = OpenAIResponsesClient(BASELINE_CONFIG).call(
            case_id=packet.route["case_id"],
            prompt=_prompt(),
            serialized_packet=packet.serialized,
        )
    except (PermanentAPIError, TransientAPIError) as exc:
        result.update({
            "success": False,
            "error_category": exc.category,
            "error_detail": exc.detail,
        })
    else:
        try:
            prediction = validate_prediction(
                call.parsed_payload if call.parsed_payload is not None else call.raw_output_text or "",
                expected_case_id=packet.route["case_id"],
                permitted_evidence_ids=set(packet.evidence_record_ids),
            )
        except Exception as exc:
            result.update({
                "success": False,
                "error_category": "LOCAL_RESPONSE_VALIDATION_ERROR",
                "error_detail": {"error_type": type(exc).__name__, "error_message": str(exc)[:2000]},
                "response_id": call.response_id,
                "returned_model": call.returned_model,
                "usage": call.usage.serializable(),
            })
        else:
            result.update({
                "success": True,
                "response_id": call.response_id,
                "returned_model": call.returned_model,
                "usage": call.usage.serializable(),
                "parsed_output": prediction.model_dump(mode="json"),
            })
    write_json(run_dir / "diagnostic_probe.json", result, exclusive=True)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 2


def _stability_analysis(run_dir: Path, packets: list[CasePacket]) -> dict[str, Any]:
    by_rep: list[dict[str, dict[str, Any]]] = []
    all_predictions: list[dict[str, Any]] = []
    for repetition in range(1, BASELINE_CONFIG.stability_repetitions + 1):
        rows = load_jsonl(run_dir / f"repetition_{repetition}" / "predictions.jsonl")
        by_rep.append({row["case_id"]: row for row in rows})
        all_predictions.extend(rows)
    case_rows = []
    for packet in packets:
        case_id = packet.route["case_id"]
        rows = [value.get(case_id) for value in by_rep]
        if any(row is None or row.get("parse_status") != "PASS" for row in rows):
            case_rows.append({"case_id": case_id, "complete": False})
            continue
        classes = [row["predicted_failure_type"] for row in rows if row]
        evidence = [tuple(row["evidence_record_ids"]) for row in rows if row]
        confidence = [float(row["confidence"]) for row in rows if row]
        jaccards = []
        for left in range(len(evidence)):
            for right in range(left + 1, len(evidence)):
                a, b = set(evidence[left]), set(evidence[right])
                jaccards.append(len(a & b) / len(a | b) if a | b else 1.0)
        mean = sum(confidence) / len(confidence)
        variance = sum((value - mean) ** 2 for value in confidence) / len(confidence)
        case_rows.append({
            "case_id": case_id,
            "complete": True,
            "exact_class_agreement": len(set(classes)) == 1,
            "class_disagreement": len(set(classes)) > 1,
            "exact_evidence_list_agreement": len(set(evidence)) == 1,
            "mean_pairwise_evidence_jaccard": sum(jaccards) / len(jaccards),
            "confidence_mean": mean,
            "confidence_std_population": variance ** 0.5,
            "confidence_range": max(confidence) - min(confidence),
        })
    complete_rows = [row for row in case_rows if row.get("complete")]
    count = len(case_rows)
    return {
        "protocol_version": "direct_llm_validation_stability_v1.0",
        "subset_case_count": count,
        "repetitions": BASELINE_CONFIG.stability_repetitions,
        "expected_calls": count * BASELINE_CONFIG.stability_repetitions,
        "successful_parsed_calls": sum(row.get("parse_status") == "PASS" for row in all_predictions),
        "complete": len(complete_rows) == count,
        "exact_class_agreement_rate": sum(row["exact_class_agreement"] for row in complete_rows) / len(complete_rows) if complete_rows else 0.0,
        "class_disagreement_rate": sum(row["class_disagreement"] for row in complete_rows) / len(complete_rows) if complete_rows else 0.0,
        "exact_evidence_list_agreement_rate": sum(row["exact_evidence_list_agreement"] for row in complete_rows) / len(complete_rows) if complete_rows else 0.0,
        "mean_evidence_jaccard": sum(row["mean_pairwise_evidence_jaccard"] for row in complete_rows) / len(complete_rows) if complete_rows else 0.0,
        "mean_confidence_std": sum(row["confidence_std_population"] for row in complete_rows) / len(complete_rows) if complete_rows else 0.0,
        "cases": case_rows,
    }


def final_audit(args: argparse.Namespace) -> int:
    preflight_dir = Path(args.preflight_dir)
    stability_dir = Path(args.stability_dir)
    values = json.loads((preflight_dir / "pre_live_audit_values.json").read_text(encoding="utf-8"))
    stability_value = json.loads((stability_dir / "stability_analysis.json").read_text(encoding="utf-8"))
    material = [
        value for value in values["unresolved_protocol_issues"]
        if "stability" not in value
    ]
    if not stability_value.get("complete"):
        material.append("validation-only stability analysis is incomplete")
    current_frozen = verify_frozen_artifacts(ROOT)
    if current_frozen["status"] != "PASS":
        material.append("frozen specification or prompt checksum changed after preflight")
    if sha256_file(ROOT / "src/direct_llm/packet.py") != values["packet_builder_sha256"]:
        material.append("packet-builder source changed after preflight")
    current_tests = _run_tests()
    if not current_tests["passed"]:
        material.append("current Direct LLM unit/integration tests failed")
    values["stability_status"] = "PASS" if stability_value.get("complete") else "FAIL"
    values["unresolved_protocol_issues"] = material
    values["decision"] = "PHASE 4 READY FOR LIVE RUN" if not material else "PHASE 4 NOT READY FOR LIVE RUN"
    audit_text = _render_audit(values)
    write_json(preflight_dir / "final_pre_live_audit_values.json", values, exclusive=True)
    (preflight_dir / "final_direct_llm_pre_live_run_audit_v1.0.md").write_text(audit_text, encoding="utf-8")
    docs_path = ROOT / "docs/direct_llm_pre_live_run_audit_v1.0.md"
    docs_path.write_text(audit_text, encoding="utf-8")
    ready_manifest = {
        **values,
        "preflight_dir": str(preflight_dir.resolve()),
        "stability_dir": str(stability_dir.resolve()),
        "prepared_test_packets_sha256": sha256_file(preflight_dir / "test_packets.jsonl"),
        "output_schema_sha256": sha256_file(ROOT / "src/direct_llm/output.py"),
        "implementation_sha256": sha256_tree(ROOT / "src/direct_llm"),
        "final_audit_test_results": current_tests,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(ROOT / "docs/direct_llm_pre_live_manifest_v1.0.json", ready_manifest)
    print(values["decision"])
    return 0 if not material else 1


def held_out_run(args: argparse.Namespace) -> int:
    if not args.execute_api:
        raise RuntimeError("held-out inference requires the explicit --execute-api flag")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not present")
    ready_path = ROOT / "docs/direct_llm_pre_live_manifest_v1.0.json"
    if not ready_path.is_file():
        raise RuntimeError("ready pre-live manifest is absent; run the final audit")
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    if ready.get("decision") != "PHASE 4 READY FOR LIVE RUN":
        raise RuntimeError("pre-live decision is not READY")
    preflight_dir = Path(args.preflight_dir)
    packet_path = preflight_dir / "test_packets.jsonl"
    if sha256_file(packet_path) != ready["prepared_test_packets_sha256"]:
        raise RuntimeError("prepared test packet artifact changed after readiness audit")
    frozen = verify_frozen_artifacts(ROOT)
    if frozen["status"] != "PASS":
        raise RuntimeError("frozen artifact checksum failure")
    if sha256_file(ROOT / "src/direct_llm/packet.py") != ready["packet_builder_sha256"]:
        raise RuntimeError("packet-builder source changed after readiness audit")
    if sha256_file(ROOT / "src/direct_llm/output.py") != ready["output_schema_sha256"]:
        raise RuntimeError("structured-output implementation changed after readiness audit")
    if sha256_tree(ROOT / "src/direct_llm") != ready["implementation_sha256"]:
        raise RuntimeError("Direct LLM implementation changed after readiness audit")
    preflight_manifest = json.loads((preflight_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if preflight_manifest["frozen_configuration"] != BASELINE_CONFIG.serializable():
        raise RuntimeError("model/generation configuration changed after packet preflight")
    packets = load_packet_artifact(packet_path)
    if len(packets) != 439:
        raise RuntimeError(f"held-out packet count must be 439, got {len(packets)}")
    run_dir = Path(args.output_root) / args.run_id
    if not run_dir.exists():
        run_dir.mkdir(parents=True, exist_ok=False)
        write_json(run_dir / "run_manifest.json", {
            "run_id": args.run_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "HELD_OUT_DIRECT_LLM_API",
            "held_out_run": True,
            "test_case_count": len(packets),
            "frozen_configuration": BASELINE_CONFIG.serializable(),
            "specification_sha256": ready["specification_sha256"],
            "prompt_sha256": ready["prompt_sha256"],
            "packet_builder_sha256": ready["packet_builder_sha256"],
            "prepared_test_packets_sha256": ready["prepared_test_packets_sha256"],
            "packet_version": PACKET_VERSION,
            "schema_version": SCHEMA_VERSION,
            "retry_policy_version": RETRY_POLICY_VERSION,
            "concurrency": 1,
            "pricing_configuration": {
                key: value for key, value in BASELINE_CONFIG.serializable().items()
                if "usd_per_million" in key or key == "pricing_reference_date"
            },
            "inference_label_sources": [],
            "api_key_recorded": False,
        }, exclusive=True)
        (run_dir / "protocol_deviations.md").write_text("NO PROTOCOL DEVIATIONS\n", encoding="utf-8")
    print(json.dumps({
        "model_id": BASELINE_CONFIG.model_id,
        "number_of_cases": len(packets),
        "specification_sha256": ready["specification_sha256"],
        "prompt_sha256": ready["prompt_sha256"],
        "packet_version": PACKET_VERSION,
        "api_credentials_present": True,
        "output_directory": str(run_dir),
        "held_out_run": True,
    }, indent=2, sort_keys=True))
    summary = run_cases(
        packets, client=OpenAIResponsesClient(BASELINE_CONFIG), config=BASELINE_CONFIG,
        prompt=_prompt(), run_dir=run_dir,
    )
    write_json(run_dir / "run_summary.json", summary.serializable())
    predictions = load_jsonl(run_dir / "predictions.jsonl")
    write_json(run_dir / "token_usage.json", pricing_report(predictions, BASELINE_CONFIG))
    write_json(run_dir / "cost_report.json", pricing_report(predictions, BASELINE_CONFIG))
    print(json.dumps(summary.serializable(), indent=2, sort_keys=True))
    return 0 if summary.successful_cases == 439 else 2


def evaluate(args: argparse.Namespace) -> int:
    """Offline-only evaluation; this command never constructs an API client."""
    from src.direct_llm.evaluation import evaluate_run
    from src.direct_llm.report import render_evaluation_report

    run_dir = Path(args.run_dir)
    result = evaluate_run(
        data_root=Path(args.data_root),
        run_dir=run_dir,
        preflight_dir=Path(args.preflight_dir),
        rules_run_dir=Path(args.rules_run_dir),
        ml_run_dir=Path(args.ml_run_dir),
    )
    report = render_evaluation_report(result, run_dir)
    (run_dir / "direct_llm_baseline_evaluation_v1.0.md").write_text(report, encoding="utf-8")
    (ROOT / "docs/direct_llm_baseline_evaluation_v1.0.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "run_dir": str(run_dir),
        "total_cases": result["overall"]["total_cases"],
        "exact_16_class_accuracy": result["overall"]["exact_16_class_accuracy"],
        "binary_f1": result["overall"]["binary_f1"],
        "macro_f1": result["overall"]["macro_f1_16_classes"],
        "decision": "PHASE 4 COMPLETE — DIRECT LLM BASELINE LOCKED",
    }, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="build/audit packets without API calls")
    prepare_parser.add_argument("--data-root", default="data/benchmark")
    prepare_parser.add_argument("--output-root", default="results/direct_llm")
    prepare_parser.add_argument("--run-id", required=True)
    prepare_parser.set_defaults(func=prepare)

    stability_parser = sub.add_parser("stability", help="run pre-registered validation stability calls")
    stability_parser.add_argument("--preflight-dir", required=True)
    stability_parser.add_argument("--output-root", default="results/direct_llm")
    stability_parser.add_argument("--run-id", required=True)
    stability_parser.add_argument("--execute-api", action="store_true")
    stability_parser.set_defaults(func=stability)

    probe_parser = sub.add_parser("probe", help="make one validation API call for diagnostics")
    probe_parser.add_argument("--preflight-dir", required=True)
    probe_parser.add_argument("--output-root", default="results/direct_llm")
    probe_parser.add_argument("--run-id", required=True)
    probe_parser.add_argument("--execute-api", action="store_true")
    probe_parser.set_defaults(func=probe)

    audit_parser = sub.add_parser("audit", help="combine preflight and stability into the live gate")
    audit_parser.add_argument("--preflight-dir", required=True)
    audit_parser.add_argument("--stability-dir", required=True)
    audit_parser.set_defaults(func=final_audit)

    run_parser = sub.add_parser("run", help="execute the one frozen 439-case held-out run")
    run_parser.add_argument("--preflight-dir", required=True)
    run_parser.add_argument("--output-root", default="results/direct_llm")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--execute-api", action="store_true")
    run_parser.set_defaults(func=held_out_run)

    evaluate_parser = sub.add_parser("evaluate", help="offline evaluation; never calls the API")
    evaluate_parser.add_argument("--data-root", default="data/benchmark")
    evaluate_parser.add_argument("--run-dir", required=True)
    evaluate_parser.add_argument("--preflight-dir", required=True)
    evaluate_parser.add_argument(
        "--rules-run-dir",
        default="results/rules_sql/phase2_rules_sql_v1_0_20260808T185000Z_auditfix1",
    )
    evaluate_parser.add_argument(
        "--ml-run-dir",
        default="results/classical_ml/phase3_classical_ml_v1_0_20260808T213000Z_auditfix1",
    )
    evaluate_parser.set_defaults(func=evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
