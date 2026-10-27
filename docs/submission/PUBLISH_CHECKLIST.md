# Public repository and teammate handoff

The user will create the GitHub repository. No public upload or remote visibility change is performed by this preparation pass.

## Use the prepared source package

The prepared ZIP is built from `PUBLIC_FILES.txt`. It contains source, tests, synthetic samples, configuration placeholders, licenses and English submission documents. It excludes `.git`, `.env.local`, runtime records, dependencies and build caches. Extract the ZIP into a new folder before publishing; do not copy the entire private working directory or its Git history.

Upload the extracted project files to the new **public** repository. Confirm hidden files such as `.gitignore` and `.env.example` are included. Do not upload the ZIP as the only repository file: judges need the source tree and readable README. Do not use a private history as the basis of a new public repository without separately auditing that history.

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
- `docs/submission/NIGHTSHIFT_SETUP.md`: remaining live route setup and required screenshots.

The team lead uses `SUBMISSION_COPY.md` and `REQUIREMENTS.md`. Complete all placeholders, verify the roster before creating a submission, check the public deck/video links, and retain HackOS's submission confirmation.

## Stop conditions

Do not describe the project as submission-ready if Nightshift live acceptance, the public repository, final media, pre-existing-work disclosure or the HackOS submission is still missing. A clean source package is one deliverable, not evidence that every competition requirement has been fulfilled.
