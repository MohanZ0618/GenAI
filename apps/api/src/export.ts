import type { Investigation } from "../../../packages/contracts/src/index.ts";
const escape = (s: string) =>
  s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
export function exportRun(
  run: Investigation,
  format: string,
): { body: string; type: string; extension: string } {
  if (format === "json")
    return {
      body: JSON.stringify(run, null, 2),
      type: "application/json",
      extension: "json",
    };
  if (format === "csv") {
    const q = (s: string) => {
      const safe = /^[=+@\-\t\r]/.test(s) ? `'${s}` : s;
      return `"${safe.replaceAll('"', '""')}"`;
    };
    const columns = [
      "execution_mode",
      "model_provider",
      "model",
      "evidence_id",
      "dataset_version",
      "source_table",
      "source_record_id",
      "query_id",
      "record",
    ];
    return {
      body: [
        columns.join(","),
        ...run.evidence.map((e) =>
          [
            run.mode,
            run.provider,
            run.model,
            e.id,
            e.datasetVersion,
            e.table,
            e.recordId,
            e.queryId,
            JSON.stringify(e.record),
          ]
            .map(q)
            .join(","),
        ),
      ].join("\r\n"),
      type: "text/csv; charset=utf-8",
      extension: "csv",
    };
  }
  if (format !== "html")
    throw new Error("Export format must be html, json, or csv");
  const body = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>FinTrace investigation ${escape(run.paymentId)}</title><style>body{font:15px/1.6 system-ui;color:#142b3d;max-width:900px;margin:40px auto;padding:24px}h1{font-size:32px}h2{border-bottom:1px solid #ddd;padding-bottom:8px}aside{padding:16px;background:#edf6f3}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6f7;padding:12px}small{color:#556}article{margin:24px 0}a{color:#087f70}</style><h1>FinTrace investigation</h1><p>${escape(run.paymentId)} · ${escape(run.createdAt)}</p><aside><strong>${run.mode === "fixture" ? "OFFLINE FIXTURE — deterministic rules; no live model or Zetaris" : run.mode === "local-model" ? "REAL MODEL + LOCAL DATA — " + escape(run.provider) + " / " + escape(run.model) + "; no Zetaris or PostgreSQL" : "LIVE RUN — " + escape(run.provider) + " / " + escape(run.model)}</strong><br>Outcome: ${escape(run.outcome || run.status)}. Recommendations require human review.</aside><p>Dataset: ${escape(run.datasetId)}<br>Run: ${escape(run.id)}</p><h2>Findings</h2>${run.findings.map((f) => `<article><h3>${escape(f.title)}</h3><p>${escape(f.summary)}</p><p>Evidence: ${f.evidenceIds.map((id) => `<a href="#${escape(id)}">${escape(id)}</a>`).join(", ")}</p><p>${f.uncertainty.map(escape).join("<br>")}</p></article>`).join("")}<h2>Verification</h2><ul>${run.checks.map((c) => `<li><strong>${escape(c.status.toUpperCase())} — ${escape(c.label)}</strong>: ${escape(c.detail)}</li>`).join("")}</ul><h2>Proposed actions</h2>${run.actions.map((a) => `<article><h3>${escape(a.title)}</h3><p>${escape(a.description)}</p><ul>${a.prerequisites.map((p) => `<li>${escape(p)}</li>`).join("")}</ul></article>`).join("")}<h2>Review</h2><p>${escape(run.review ? `${run.review.decision}: ${run.review.notes}` : "Awaiting human review")}</p><h2>Memory snapshots provided to planner</h2><p>Recall does not prove model adoption. Later memory status changes do not alter this report.</p><pre>${escape(JSON.stringify(run.memories, null, 2))}</pre><h2>Memory draft requests (separate cost)</h2><pre>${escape(JSON.stringify(run.memoryDraftRequests || [], null, 2))}</pre><h2>Source evidence</h2>${run.evidence.map((e) => `<article id="${escape(e.id)}"><strong>${escape(e.table)} / ${escape(e.recordId)}</strong><small> · Query ${escape(e.queryId)} · Version ${escape(e.datasetVersion)}</small><pre>${escape(JSON.stringify(e.record, null, 2))}</pre></article>`).join("")}</html>`;
  return { body, type: "text/html; charset=utf-8", extension: "html" };
}
