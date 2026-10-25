# Third-party notices

## FinRCA-Bench

- Source: https://github.com/PratikGhawate/FinRCA-AI-Bench
- Revision: `76c93ec32536e29826e2ab9e68b58e0351410bc7`
- License: MIT; original text in `packages/data/upstream/LICENSE`.
- Use: generator source, source schemas, synthetic financial records and evaluator expectations. Review packet extraction and coverage transformations are FinTrace additions. Upstream generator quality checks passed before extraction.

## Meterless H-MEM

- Source: https://github.com/Meterless/Meterless
- Revision: `1742dec56a66e58eef9dda2d2b865823758ca8cd`
- License: Apache-2.0; original texts in `third_party/meterless/LICENSE` and `third_party/meterless/engines/hmem/LICENSE`.
- Use: vendored TypeScript reference memory engine, conformance vectors and runner. The app wrapper provides explicit approval and physical namespace isolation. The reference embedder remains a deterministic mock. Automatic dreaming is not called by the application.

## Zetaris integration reference

- Source: https://github.com/zetaris/getting-started
- Revision inspected: `98a2d30603c6e2c001ce3e6e1d43798f1d6c75c9`
- Use: documented UI-proxy request route, body, and authentication contract. The FinTrace TypeScript adapter is an application-specific implementation; the upstream helper itself is not vendored.

Other runtime and development dependencies are pinned in `package-lock.json` and retain their respective package licenses. This source package does not redistribute PostgreSQL, Zetaris, NVIDIA models, Cursor, or the Meterless Runtime installer.
