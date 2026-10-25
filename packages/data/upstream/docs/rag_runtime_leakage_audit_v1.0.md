# Standard RAG Runtime Leakage Audit — Version 1.0

## Frozen boundary

Primary Standard RAG uses only a three-field unlabeled route, the 14 cutoff-eligible operational tables, canonical record text, and retrieval outputs. Route preparation is isolated from primary inference and discards every benchmark-question field other than `case_id`, primary entity type, and primary entity ID. The case ID is retained for artifact identity but is never included in the embedded retrieval query.

## Enforced controls

- Operational CSV headers must exactly equal `src/schema.py::TABLE_SCHEMAS`, including order.
- Every route must have exactly the three permitted keys.
- Recursive and serialized-payload scanners reject target, evidence-contract, tier, hop, RCA, split, adjudication, and earlier-baseline fields.
- The corpus, query, retrieval, and primary reasoner paths cannot open ground truth, case-oracle packages, causal edges, mutation logs, dataset-quality findings, or prior predictions.
- Every corpus-build, route-preparation, and primary-inference data path is recorded in an opened-path audit.
- Canonical documents are scanned before embedding; queries and reasoner payloads are scanned before use.
- Model evidence citations must be unique members of the exact retrieved Top-K list.
- Repository secret scanning records only whether a credential exists and never reads, prints, or persists its value.
- Primary query/retrieval/reasoner modules do not import the evaluation-only evidence resolver.

## Reproducibility

The no-cost pre-embedding command writes the complete machine-readable opened-path, field-registry, payload, and secret findings into its immutable run directory:

```bash
python3 -m src.rag.cli preflight \
  --data-root data/benchmark \
  --output-root results/rag \
  --run-id phase5_rag_pre_embedding_v1_0_<UTC>
```

## Decision

The implementation-level leakage controls are present. The pre-embedding gate is authoritative for the concrete corpus/run and fails closed if any runtime check differs from `PASS`.
