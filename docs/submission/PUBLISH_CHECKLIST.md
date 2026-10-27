# Public repository and teammate handoff

The existing [MohanZ0618/GenAI repository](https://github.com/MohanZ0618/GenAI) is public. The Nightshift/USL code and materials were published as source commit `6986c0a` on 27 October 2026, then cloned directly from GitHub into a new directory and verified. Installation, type checking, build, 189 unit/API tests, three README examples and real-service connectivity passed; see [the verification record](VALIDATION.md#public-repository-fresh-clone-verification--27-october-2026). This did not change repository visibility.

## Use the prepared source package

Use `PUBLIC_FILES.txt` to review the source release. Its 390 source, test, synthetic sample, configuration-placeholder, license and submission-document files were checked before publication. The earlier ZIP validation covered 367 files; rebuild any ZIP from the current revision rather than using that old archive. The public repository's current source tree was tested independently by fresh clone. Exclude `.env.local`, raw runtime records, dependencies and build caches.

Synchronize the reviewed project files to the public repository, including `.gitignore` and `.env.example`. Judges need the source tree and readable README; a ZIP alone is insufficient. If creating a separate source-only repository, extract the current allowlisted package into a new folder and review any history before publishing it.

## Verify from the public repository

1. Open the repository signed out; confirm the README and source are accessible.
2. Clone into a fresh folder, install with `npm ci`, run `npm run build`, select `FINTRACE_MODE=fixture`, then run `npm run dev`.
3. Open the local app and run the three README examples. Offline behavior must be clearly labeled.
4. Follow the separate live integration instructions with locally supplied credentials. A clone alone does not install/configure Zetaris or Nightshift.
5. Confirm the docs/submission directory, new tests and all current UI source files were uploaded.
6. Review all public files for unapproved personal details, logs or credentials. Automated scans are bounded checks, not a guarantee.

## Send classmates these files

- `README.md`: product, architecture, usage and limits.
- `docs/submission/TEAM_HANDOFF.md`: eight-slide outline, narration and 3:40 recording sequence.
- `docs/submission/SPONSOR_EXPLANATION.md`: sponsor roles and actual evidence status.
- `docs/submission/VALIDATION.md`: checks and known issues they must represent accurately.
- `docs/submission/NIGHTSHIFT_SETUP.md`: reproduction setup for the verified Google `gemini-3.5-flash-lite` route through Nightshift and required screenshots; actual results are in [NIGHTSHIFT_ACCEPTANCE.md](NIGHTSHIFT_ACCEPTANCE.md).

The team lead uses `SUBMISSION_COPY.md` and `REQUIREMENTS.md`. Complete all placeholders, verify the roster before creating a submission, check the public deck/video links, and retain HackOS's submission confirmation.

## Stop conditions

Do not describe the project as submission-ready if Nightshift live acceptance, the public repository, final media, pre-existing-work disclosure or the HackOS submission is still missing. A clean source package is one deliverable, not evidence that every competition requirement has been fulfilled.
