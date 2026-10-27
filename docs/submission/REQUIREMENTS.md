# Submission requirements and readiness

Prepared on 27 October 2026. Source: the team's supplied **Submission Requirements** document from [HackOS Resources](https://hackathon.genai.works/resources?id=01a08ff1-54c3-70c5-b262-31e75dfd1e60). This checklist summarizes that document, not an organizer approval of FinTrace. It supersedes older local interpretations that Nightshift was optional. The [Official Rules](https://hackathon.genai.works/event/open-agent-hackathon-2026#rules) govern conflicts.

The supplied document sets **27 October 2026, 23:45 UTC = 6:45 PM Chicago (CDT)**. The public landing page has displayed 23:59 UTC; use the earlier 6:45 PM deadline for preparation and verify the actual submission screen. Submit through HackOS; judging starts 28 October in the supplied document, with results on 6 November at 16:00 UTC.

## Required technology and evidence

| Requirement | FinTrace evidence / implementation | Remaining action |
|---|---|---|
| Zetaris as the data layer | Live evidence adapter queries registered PostgreSQL source views. Historical direct-OpenAI live tests passed on synthetic data. | Record a current investigation visibly querying Zetaris. Confirm actual source configuration. |
| At least one Meterless Engine in a working feature | H-MEM supports human-approved investigation procedures, scoped recall, provenance and deactivation. | Run engine conformance and application lifecycle tests; demonstrate the feature. |
| Nightshift as the primary AI provider | Existing `meterless` adapter covers investigation planning, memory suggestions and the optional model baseline. Contract tests are mocked. | **BLOCKER:** connect a real Runtime, route the final app through it, verify a returned result and the underlying model. |
| Real sponsor use in the demo | UI records evidence queries, model request metadata and recalled memories. | Show Zetaris, the H-MEM feature, and a real request through Nightshift. A provider label alone is not proof. |
| NVIDIA wherever it contributes | NVIDIA adapter exists; no verified use in the current submission route. | State no verified NVIDIA use. Do not claim the NVIDIA award. |
| NVIDIA award, if entered | Optional, outside the selected delivery scope. | Requires a working feature using a Nemotron model through Nightshift plus actual-model evidence. |
| Cursor | Optional under the supplied document. | Only describe actual team usage; this preparation uses Codex. |

Using OpenAI as the underlying model is the selected plan. The app must call Nightshift for the final runtime; a successful direct OpenAI request does not meet that requirement. The installed Runtime must actually support the chosen cloud route. If it cannot, record the blocker and obtain a revised model decision.

## Required submission components

| Component | Prepared handoff | Owner / remaining work |
|---|---|---|
| 1–4 minute demo | [TEAM_HANDOFF.md](TEAM_HANDOFF.md): shot list, narration and evidence gates | Classmates record/edit/upload the final video from real runs. |
| Slide deck | [TEAM_HANDOFF.md](TEAM_HANDOFF.md): eight-slide outline covering every required topic | Classmates build/export/share the deck. |
| Public GitHub repository | English README, source, tests, sample data, licenses and release allowlist | User creates a new public repository, uploads reviewed source, and checks anonymous access. Do not upload private Git history. |
| Sponsor technology explanation | [SPONSOR_EXPLANATION.md](SPONSOR_EXPLANATION.md) | Update Nightshift evidence only after the real test passes. |
| Project name and description | [SUBMISSION_COPY.md](SUBMISSION_COPY.md) | Copy into the actual form; adjust only for its field limits. |
| Exactly one primary track | Track 02 — The Agent That Can Explain Why | Team lead selects it in HackOS. |
| Pre-existing work disclosure | Draft with pinned upstream commits and explicit review items | Team confirms which original code/data predates the build window. |
| Team members | Not inferred from source code | Confirm all members before creating the first submission; membership then locks. Solo entrants also need a team. |

## Repository and quality checks

- [ ] Public source opens without an access request; required Colab links are included if applicable (FinTrace currently does not depend on Colab).
- [ ] README covers clean installation, usage, dependencies, actual Nightshift route and limitations.
- [ ] Three synthetic examples and expected outputs are available.
- [ ] Live model traces identify requested/returned models when available; Nightshift records independently identify the actual route.
- [ ] H-MEM test results and a working feature are included in the evidence package.
- [ ] `.env.example` contains placeholders only; no cloud/Runtime secrets, real personal records or local credentials are committed or shown.
- [ ] Offline fallback is documented as `FINTRACE_MODE=fixture`. The source document recommends `SAMPLE_MODE=true`; an additional switch is not needed for this existing fallback.
- [ ] A clean clone installs, builds and runs offline. Live setup requirements are explicitly documented, including instance-specific Zetaris registration and Nightshift configuration.
- [ ] Final video, slides and repository links work for a signed-out reviewer.
- [ ] The real submission screen shows success before the deadline; retain confirmation locally.

The submitted integration must work; mentioning a sponsor or including an unused dependency is insufficient. Updates are allowed before the deadline; do not rely on post-deadline fixes. Teams contain 1–5 builders and each participant belongs to one team/submission.

## What judges assess

Impact 30, Technical 20, Innovation 15, Demo 15, Product & UX 10, Sponsor Tech 10. At least three judges review each submission; ties use Impact, then submission timestamp. A judge must be able to open and run the project.

Emphasize a concrete finance-review problem, useful evidence-linked outputs, a working feedback loop and honest failure handling. Do not claim customer-validated time savings, production accuracy or model superiority. Wildcard is scored on new work; FinTrace's selected primary track is Track 02.

## Final technical gate

Run `npm run preflight:submission` to reject obviously incorrect runtime profiles without network calls. Use `npm run preflight:submission -- --live` for real service checks, then complete the business and UI workflows. The command always reports `submissionReady: false`: only the team can verify artifacts, public access, route evidence, disclosures and HackOS submission.

For rule clarification use the HackOS help desk or sponsor help channel. Do not invent a waiver for an unmet requirement.
