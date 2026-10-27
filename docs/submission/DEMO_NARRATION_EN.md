# FinTrace demo narration

Target duration: **3 minutes 40 seconds**, spoken at a steady pace with short pauses for clicks. The screen directions are in [DEMO_GUIDE_ZH.md](DEMO_GUIDE_ZH.md). Read only the paragraphs labelled **Say**. The default recording revisits saved, verified live investigations; it does not pretend to start new inference during playback.

## 1. Problem and audience · 0:00–0:20

**Screen:** Investigation history. Caption: **Synthetic demonstration data**.

**Say:**

> This is FinTrace, an investigation workspace for accounts-payable teams. When a payment does not reconcile, a missing match is only the starting point. Analysts need an explanation they can trace to records and pass to a reviewer. Our demonstration uses synthetic data.

## 2. An inspectable finding · 0:20–0:50

**Screen:** Open the saved target duplicate investigation, show its conclusion and one original evidence record. Caption: **Recorded live investigation**.

**Say:**

> Here we are revisiting a saved live investigation. The result identifies a duplicate disbursement. Each finding links to original records, including payment allocations and bank observations. We can inspect the record fields, its source table and the exact dataset version used. Reopening this result preserves the original investigation rather than silently running it again.

## 3. Evidence and independent checks · 0:50–1:25

**Screen:** Investigation activity, source/execution details and Validation.

**Say:**

> The model chooses among six read-only evidence tools. In this live profile, those tools retrieve records through Zetaris. FinTrace then checks them against the imported immutable snapshot. The independent verifier checks amounts, relationships, timing and source coverage. The model does not decide financial truth or issue arbitrary SQL. The activity trail shows the tools used, their source tables and recorded execution details.

## 4. The actual model route · 1:25–1:50

**Screen:** Corresponding Nightshift Proof record and reviewed Runtime correlation metadata.

**Say:**

> These calls went through Meterless Nightshift and were answered by Google Gemini 3.5 Flash Lite. We matched each successful business call to its Runtime decision, actual model, provider and application context. This is evidence of the tested route; the Runtime metadata is unsigned.

## 5. Approved procedure and later recall · 1:50–2:40

**Screen:** Independent lesson's stored review, active `mem-1`, then the target's recalled-memory snapshot.

**Say:**

> H-MEM retains an approved procedure, not the answer to a future payment. In our acceptance run, Nightshift generated a memory draft from an independent lesson. A scripted synthetic reviewer edited and explicitly approved it through the real review API. Here is that saved approval. The procedure survived application recreation and was recalled in this later investigation. Its provenance links back to the lesson. The later case still gathered and checked its own evidence. Memory can guide tool priority, but it cannot override the financial verifier.

## 6. Three distinct outcomes · 2:40–3:05

**Screen:** Saved normal result, followed by partial-coverage result.

**Say:**

> FinTrace also distinguishes a supported normal result from insufficient evidence. This payment has no supported anomaly. This other snapshot has incomplete coverage, so the system withholds a financial conclusion. A missing record, failed request or incomplete extract should not automatically become an accusation of failure.

## 7. Review and export · 3:05–3:25

**Screen:** Review controls, then exported HTML report. Do not imply a new approval was saved in this default recording.

**Say:**

> A reviewer can accept findings or request changes and approve reusable memory separately. The exported report preserves findings, checks, citations and the memory context used. Review does not execute a payment or modify source transactions.

## 8. Results and limits · 3:25–3:40

**Screen:** Four synthetic cases, 20 successful Zetaris queries, 17 correlated business model calls; public repository link.

**Say:**

> Four selected synthetic cases passed, with twenty successful Zetaris queries and seventeen correlated model calls. These demonstrate the selected workflow, not customer accuracy or cost savings. Source and reproduction steps are on GitHub.

## Recording notes

- Keep **Synthetic demonstration data** visible in the opening and **Recorded live investigation** visible when showing saved results.
- The source lesson's saved reviewer action is scripted synthetic acceptance. If recording a new manual review, describe only the actions actually performed and adjust the affected narration.
- The 17 calls are 16 planning calls plus one memory draft. The initial probe is separate. Runtime receipt metadata is unsigned.
- All calls in this evidence set used `gemini-3.5-flash-lite`; no NVIDIA/Nemotron use is claimed.
- The persistence check recreated the application wrapper; it did not restart the entire machine or database platform.
- Validation sources: [Nightshift acceptance](NIGHTSHIFT_ACCEPTANCE.md), [sanitized results](../../data/nightshift-acceptance/results.json), [current validation](VALIDATION.md).
- For the independent three-feed USL clip, replace a short segment and keep total duration below four minutes. Optional sentence: “Our separate USL demonstration connects three simulated feeds and executes seven native quality rules.”
