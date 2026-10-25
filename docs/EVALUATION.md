# Evaluation

Run `npm run evaluate` for the prepared reference cases, or append `-- development`, `-- heldout`, or `-- stress`. Fixture reports are deterministic financial verification results with measured runtime variability. The report records provider, model, mode, query counts, source citation validity, reference evidence recall/precision and technical failures.

The last completed offline run matched 39/40 development outcomes, 20/20 held-out outcomes and 10/10 derived coverage-stress outcomes. There were no technical failures, no normal-case false positives in the 12 normal reference cases, and all displayed citations resolved to retrieved records. One development case remained unresolved; it is retained in the results rather than discarded.

These numbers do not prove performance on real business data or unseen financial workflows. The sample is small, deterministic, selected from supported categories and shares generator assumptions with the verifier. The ten stress cases are correlated transformations, not ten independent natural incidents. Root-cause accuracy is category-level, not a judgement of prose quality.

The fixed rules baseline receives the complete visible packet. Fixture orchestration uses those same verification rules, so identical outcomes are expected and cannot demonstrate an AI advantage. The live evaluation additionally executes a one-pass response with the same configured model, the full visible packet, no remembered case answer, and strict citation validation. It has not been run because sponsor services are not configured.

Citation precision counts cited records against the benchmark's minimal required record IDs; useful supporting records outside that minimal set can lower this number. Evidence recall counts required source IDs present in cited records, including journal aliases. The evaluator does not reward fabricated records or failed-query absence claims.

Unit and integration tests cover schema validation, exact monetary parsing, referential integrity, immutable versions, source gaps, currency boundaries, constrained model tools, transient model failures, namespace-isolated persistent H-MEM, run lifecycle, review and exports. Browser tests cover the desktop workflow, refresh recovery, mobile overflow, and import errors. Live release gates remain open until actual services are connected.
