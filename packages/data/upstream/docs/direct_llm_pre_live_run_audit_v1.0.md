# Direct LLM Pre-Live-Run Audit — Version 1.0

## Frozen configuration

- Specification checksum: `fb71556291a92d96913b3a3d8b86b636a88b28569002751bcc6627ed2f487212`
- Prompt checksum: `e4fb908829f412eb0a3015a4d05f29c0603b12cac84ade166aff92b76c78278c`
- Packet-builder checksum: `7f38fd1efdf7ceb57818461b9b6a5a2fa567afa0507167f51f5f5024571a080a`
- Case-packet version: `direct_llm_case_packet_v1.0`
- Selected prompt: `direct_llm_v1.0` (single prompt locked a priori)
- Model ID: `gpt-5.6-sol`
- Provider: `OpenAI`
- Reasoning effort: `medium`
- Maximum output tokens: 1,000
- Verbosity: `low`
- Structured output: strict Pydantic/JSON Schema
- Retry-policy version: `direct_llm_retry_v1.0`
- Structured-output schema version: `direct_llm_output_schema_v1.0`
- Concurrency: 1
- Number of test cases: 439
- Authoritative preflight run: `phase4_direct_llm_preflight_v1_0_20260809T063242Z`
- Preserved superseded preflight: `phase4_direct_llm_preflight_v1_0_20260809T062454Z` (packet bytes are unchanged; replaced only to remove a generic Phase 2 normalization import)

## Audit results

- Frozen artifact checksums: PASS
- Case-packet leakage audit: PASS
- Validation-only annotated-evidence structural coverage: PASS — 416/416 cases; audit performed after packet construction
- Test-label isolation: PASS
- Context-size audit: PASS
- Test packet characters (min / median / p95 / max): 8,044 / 126,022 / 749,452.6 / 786,775
- Estimated input tokens (min / median / p95 / max): 4,723 / 44,049 / 251,858.9 / 264,300
- Estimated aggregate held-out input tokens: 33,711,485
- Packet truncation: NONE
- Semantic retrieval/ranking: NONE
- Mock/unit/integration tests: PASS — 30 tests
- Secret handling: PASS
- API credential present during preflight: NO
- Held-out API calls made: NO
- Validation-only prompt selection: NOT APPLICABLE — SINGLE PROMPT LOCKED BEFORE API USE
- Validation-only stability analysis: NOT RUN

The token values use the frozen conservative `ceil(characters/3)` estimator and are not billing counts. At the frozen USD 5.00 per million input-token rate, the held-out input-only projection is approximately USD 168.56 before cached-input discounts and output-token charges. The 32-case × 3 validation stability protocol projects approximately 28.25 million estimated input tokens, or USD 141.26 with no caching, before output charges. API-reported tokens and the run-level pricing configuration remain authoritative after execution.

## Unresolved protocol issues

- The pre-registered validation-only stability analysis requires 96 explicitly authorized paid API calls and has not been executed.

## Decision

The pre-live gate is not satisfied. The held-out runner will refuse to start without a later machine-readable READY manifest produced by the final audit command.

**PHASE 4 NOT READY FOR LIVE RUN**
