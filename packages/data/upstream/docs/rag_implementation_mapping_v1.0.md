# Frozen Standard RAG v1.0 — Implementation Mapping

| Frozen specification component | Implementation file/function | Status |
|---|---|---|
| Specification identity and sidecar | `src/rag/config.py`, `src/rag/audits.py::verify_frozen_spec` | Implemented; fail closed |
| Operational source identity | `src/rag/corpus.py::_source_manifest` | Implemented; exact 14-file SHA/count registry |
| Decision-time eligibility | `src/rag/corpus.py::_eligible_rows` | Implemented |
| One-row retrieval unit and canonical IDs | `src/rag/serialization.py` | Implemented |
| Canonical corpus ordering/text manifest | `src/rag/corpus.py::_documents` | Implemented |
| Corpus token safety | `src/rag/tokens.py`, `src/rag/corpus.py::corpus_token_audit` | Implemented with `cl100k_base` |
| Field/path/case-ID leakage controls | `src/rag/leakage.py`, `src/rag/audits.py` | Implemented and runtime audited |
| Three-field route isolation | `src/rag/routes.py` | Implemented |
| Frozen embedding configuration | `src/rag/config.py::EmbeddingConfig` | Implemented |
| Paid embedding boundary | `src/rag/cli.py::build_index` | Implemented; explicit `--execute-api` required |
| Embedding batches/retries/resume | `src/rag/embeddings.py::embed_corpus` | Implemented; append-only per-attempt ledger |
| Immutable normalized float32 vectors | `src/rag/embeddings.py::normalize_vectors/finalize_embedding_matrix` | Implemented |
| Exact global flat cosine index | `src/rag/index.py::ExactFlatCosineNumpyV1` | Implemented |
| Stable score-tie ranking | `src/rag/index.py::search` | Implemented; ascending record ID |
| Frozen anchor/query construction | `src/rag/query.py::build_query` | Implemented for all four anchor types |
| One-shot retrieval | `src/rag/retriever.py`, `src/rag/retrieval_runner.py` | Implemented; no filters/rerank/expansion |
| Validation Top-40 and prefix scoring | `src/rag/cli.py::validation_retrieve`, `src/rag/evaluation.py::evaluate_k_grid` | Implemented; execution awaits authorization/index |
| Frozen six-level K selection | `src/rag/evaluation.py::select_k` | Implemented and tie-level tested |
| Evaluation-only evidence resolution | `src/rag/evidence.py::resolve_evidence` | Implemented outside primary modules |
| Frozen prompt | `src/rag/prompt.py::load_frozen_prompt` | Extracted directly from checksum-verified spec |
| Structured RAG output contract | `src/rag/schemas.py::RAGPrediction` | Implemented with all cross-field invariants |
| Retrieved-only reasoner context | `src/rag/reasoner.py::build_reasoning_case` | Implemented |
| Context preflight/no truncation | `src/rag/reasoner.py::context_preflight` | Implemented |
| Frozen Responses API configuration | `src/rag/reasoner.py::OpenAIReasonerClient` | Implemented; exact returned model enforced |
| Reasoner mocks and terminal outcomes | `src/rag/reasoner.py::MockReasonerClient` | Implemented and tested |
| Request hashing | `src/rag/reasoner.py::reasoning_request_hash` | Implemented over every frozen component |
| Generation retries/checkpoints/resume | `src/rag/runner.py::run_reasoning_cases` | Implemented; valid model decisions never regenerated |
| Paid generation boundary | `src/rag/cli.py::run_primary` | Implemented; explicit two-stage `--execute-api` authorization |
| Raw request/response/usage preservation | `src/rag/retrieval_runner.py`, `src/rag/runner.py` | Implemented append-only |
| Classification metrics | `src/rag/evaluation.py::classification_metrics` | Implemented, including strict unresolved scoring |
| Retrieval metrics | `src/rag/evaluation.py::retrieval_case_metrics/aggregate_retrieval` | Implemented |
| Evidence metrics/two-reviewer boundary | `src/rag/evaluation.py::evidence_prediction_metrics/aggregate_evidence` | Deterministic checks implemented; semantic fields remain pending until human adjudication |
| Frozen stratification | `src/rag/evaluation.py::stratified_results` | Implemented with explicit empty bins |
| Retrieval-versus-reasoning attribution | `src/rag/evaluation.py::attribute_failure` | Implemented with frozen precedence |
| Oracle Evidence Context Diagnostic | `src/rag/oracle.py`, `src/rag/cli.py::oracle_diagnostic` | Implemented as separate post-primary paid command |
| Rules/SQL and ML paired comparisons | `src/rag/evaluation.py::paired_comparison`, offline CLI | Implemented against authoritative immutable artifacts |
| Direct LLM comparison boundary | offline CLI | Accuracy/latency/cost hard-coded PENDING until a complete held-out Direct LLM run exists |
| Direct packet context compression | `src/rag/costs.py::direct_packet_compression` | Implemented deterministically |
| Component cost/latency accounting | `src/rag/costs.py::end_to_end_accounting` | Implemented |
| No-graph audit | `src/rag/audits.py::no_graph_audit` | Implemented; PASS |
| Pre-embedding gate | `src/rag/cli.py::preflight` | Implemented and executed without API calls |
| Pre-live held-out gate | `src/rag/cli.py::run_primary` first stage | Implemented; awaits index, selected K, and authorized retrieval |
| Reproducible independent workflows | `src/rag/cli.py` | Implemented: `build-index`, `validation-retrieve`, `select-k`, `run`, `evaluate`, `oracle-diagnostic` |
| Immutable inventories and deviations | `src/rag/artifacts.py::write_checksum_manifest`, CLI manifests | Implemented |
