# Release validation

Validation date: 2026-10-24 (America/Chicago).

This source package preserves the existing repository history. Runtime code was not changed for publication. README and architecture documentation were rewritten from the current implementation; selected manual guides were made portable. Original local materials remain outside this release folder.

## Checks performed

| Check | Result |
|---|---|
| `npm run typecheck` | Passed |
| `npm test` | 82 tests passed across 6 files; network calls mocked |
| `npm run build` | Passed; TypeScript and Vite production build |
| `npm run evaluate` with `FINTRACE_MODE=fixture` | Development 39/40, held-out 20/20, derived stress 10/10; citation integrity passed; zero technical failures |
| Browser regression | 29 Playwright tests passed in 2.1 minutes on isolated port 54319 |
| Release/source hash comparison | All 255 included application, package, third-party and test files identical to validated working sources |
| Release scope | 316 explicitly allowlisted files; source, synthetic examples, tests, documentation and licenses |
| Focused privacy scan | No detected personal identity strings, machine-specific user/workspace paths, common secret formats or excluded binaries; `.env.local` never copied |
| Project Markdown links | Checked against files in the release package |

The default browser-test port 4311 was occupied. The browser suite uses the existing tests and a temporary configuration selecting port 54319, with a separate fixture state directory. This local configuration and test outputs are not release files.

## Evidence boundaries

All current release checks run offline or use mocked model requests. No new billable model or sponsor-service validation was performed. A historical local record from 2026-10-22 documents one real OpenAI normal-case investigation with four successful HTTP requests; raw request identifiers and runtime traces are excluded from this package.

The fixture result is deterministic verification over small synthetic reference sets. It does not establish production accuracy, independent statistical generalization, or an advantage of model planning over rules. PostgreSQL/Zetaris and NVIDIA/Meterless Runtime end-to-end operation remain unverified.

## Included and excluded material

`PUBLIC_FILES.txt` is the exact publication manifest. The package retains upstream license notices and pinned source revisions. The broad name of this file does not change GitHub repository visibility; the target remains private.

Excluded: real credentials, `.env.local`, `.local/`, dependency/build caches, raw evaluation results and screenshots, API smoke traces, personal research/onboarding materials, presentations and recordings. Historical audit snapshots with obsolete architecture descriptions are not included; use `docs/AGENT_ARCHITECTURE.zh-CN.md` for current behavior.
