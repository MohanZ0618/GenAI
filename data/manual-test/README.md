# Synthetic manual import samples

These samples derive from the shipped FinRCA `Review packet 001`; upstream license and provenance remain as documented in `docs/DATA.md`. They contain synthetic financial records and no evaluator labels. Focus payment: `PAY_0426017`. Expected investigation: duplicate disbursement (F06).

- `valid-bundle.json`: select this one file in the import dialog.
- `csv/`: select `manifest.json` and all nine CSV files together. Its content matches the valid bundle, so importing both formats reuses the same immutable dataset.
- `invalid-missing-payments.json`: must be rejected with a missing `payments.csv` error.
- `revised-bundle.json`: same name, with clearingDays increased by one. Import creates a new version while preserving the original dataset/run. The duplicate-payment finding should remain.

Regenerate with `npx tsx scripts/prepare_manual_samples.ts`. These files are populated examples; the app's downloaded template has headers only and intentionally contains no payment cases.
