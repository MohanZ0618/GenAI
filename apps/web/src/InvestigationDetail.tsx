import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileCheck2,
  FileText,
  HelpCircle,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Square,
  TriangleAlert,
  UserRoundCheck,
  XCircle,
} from "lucide-react";
import { api, date, label, money, textValue } from "./api";
import type { Case, Dataset, Evidence, Investigation } from "./api";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { InvestigationProgress } from "./InvestigationProgress";
import "@fontsource-variable/inter";
import "./investigation-detail.css";

type Props = {
  investigation: Investigation;
  payment?: Case;
  dataset?: Dataset;
  updatedDataset?: Dataset;
  stale: string;
  starting: boolean;
  cancelling: boolean;
  exporting: boolean;
  activeEvidence: string | null;
  activeFinding: string | null;
  onEvidence: (id: string | null) => void;
  onFinding: (id: string | null) => void;
  onBack: () => void;
  backLabel?: string;
  onCancel: () => void;
  onUpdate: () => void;
  onReview: (notes: string) => void;
  onReviewed: (run: Investigation) => void;
  runStatus: ReactNode;
  diagnostics: ReactNode;
  timeline: ReactNode;
  exportControl: ReactNode;
  presentation?: "page" | "dialog";
  showProgress?: boolean;
};

function recordDate(item: Evidence): string | undefined {
  const r = item.record;
  return (
    r.posted_date ||
    r.payment_date ||
    r.invoice_date ||
    r.changed_at ||
    r.timestamp ||
    r.created_at
  );
}

function evidenceAmount(item: Evidence): string | null {
  const r = item.record;
  const amount =
    r.amount ?? r.payment_amount ?? r.invoice_total ?? r.allocated_amount;
  const currency = r.currency || r.payment_currency;
  return amount !== undefined && currency ? money(amount, currency) : null;
}

export function InvestigationDetail(props: Props) {
  const { investigation: run, payment, dataset, updatedDataset } = props;
  const savedPayment = run.evidence.find(
    (item) =>
      item.table === "payments" && item.record.payment_id === run.paymentId,
  )?.record;
  const savedVendor = savedPayment?.vendor_id
    ? run.evidence.find(
        (item) =>
          item.table === "vendors" &&
          item.record.vendor_id === savedPayment.vendor_id,
      )?.record
    : undefined;
  // Saved evidence also supplies the header when its snapshot was removed.
  const paymentVendor =
    savedVendor?.vendor_name ??
    payment?.vendor ??
    savedPayment?.vendor_id ??
    "Payment investigation";
  const paymentDate = savedPayment?.payment_date ?? payment?.date;
  const paymentAmount = savedPayment?.payment_amount ?? payment?.amount;
  const paymentCurrency = savedPayment?.payment_currency ?? payment?.currency;
  const embedded = props.presentation === "dialog";
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const evidenceContentId = useId();
  useEffect(() => setEvidenceOpen(true), [run.id]);
  const showingEvidence = embedded && !!props.activeEvidence;
  const evidenceBack = useRef<HTMLButtonElement>(null);
  const evidenceReturn = useRef<HTMLElement | null>(null);
  const evidenceScroll = useRef<{ element: HTMLElement; top: number } | null>(
    null,
  );
  const wasShowingEvidence = useRef(false);
  function selectEvidence(id: string | null) {
    if (embedded && id && !props.activeEvidence) {
      evidenceReturn.current = document.activeElement as HTMLElement | null;
      const element = evidenceReturn.current?.closest<HTMLElement>(
        ".investigation-dialog-scroll",
      );
      if (element) evidenceScroll.current = { element, top: element.scrollTop };
    }
    props.onEvidence(id);
  }
  useEffect(() => {
    if (showingEvidence) {
      if (evidenceScroll.current) evidenceScroll.current.element.scrollTop = 0;
      evidenceBack.current?.focus({ preventScroll: true });
    } else if (wasShowingEvidence.current) {
      if (evidenceScroll.current)
        evidenceScroll.current.element.scrollTop = evidenceScroll.current.top;
      if (evidenceReturn.current?.isConnected)
        evidenceReturn.current.focus({ preventScroll: true });
    }
    wasShowingEvidence.current = showingEvidence;
  }, [showingEvidence]);
  const running = run.status === "running" || run.status === "queued";
  const completed = run.status === "completed";
  const findings = run.findings;
  const primary =
    findings.find(
      (item) =>
        item.category !== "EVIDENCE_GAP" && item.category !== "NO_FAILURE",
    ) ?? findings[0];
  const tone = !completed
    ? "pending"
    : run.outcome === "anomaly_supported"
      ? "issues"
      : run.outcome === "no_anomaly_supported"
        ? "clear"
        : "uncertain";
  const businessLabel = !completed
    ? "Not determined"
    : run.outcome === "anomaly_supported"
      ? "Issues found"
      : run.outcome === "no_anomaly_supported"
        ? "No anomaly supported"
        : "Insufficient evidence";
  const title = running
    ? "Investigation in progress"
    : run.status === "failed"
      ? "Investigation could not complete"
      : run.status === "cancelled"
        ? "Investigation cancelled"
        : (primary?.title ?? businessLabel);
  const summary = running
    ? "Retrieving source records and checking the available evidence."
    : run.status === "failed"
      ? "The run failed. A technical failure does not establish a financial conclusion."
      : run.status === "cancelled"
        ? "This run stopped before completing its assessment."
        : (primary?.summary ?? "No assessment has been recorded for this run.");
  const selected = run.evidence.find(
    (item) => item.id === props.activeEvidence,
  );
  const selectedFinding =
    findings.find(
      (item) =>
        item.id === props.activeFinding &&
        selected &&
        item.evidenceIds.includes(selected.id),
    ) ??
    findings.find((item) => selected && item.evidenceIds.includes(selected.id));
  const uncertainty = [
    ...new Set([
      ...findings.flatMap((item) => item.uncertainty),
      ...run.checks
        .filter((item) => item.status === "unknown")
        .map((item) => item.detail),
    ]),
  ];
  const [notes, setNotes] = useState(run.review?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [reviewError, setReviewError] = useState("");
  useEffect(() => {
    setNotes(run.review?.notes ?? "");
    setReviewError("");
  }, [run.id, run.review?.at]);
  async function saveReview(decision: "accepted" | "needs_changes") {
    if (saving || !completed) return;
    setSaving(true);
    setReviewError("");
    try {
      const reviewed = await api<Investigation>(
        `/investigations/${encodeURIComponent(run.id)}/review`,
        {
          method: "POST",
          body: JSON.stringify({ decision, notes, approveMemory: false }),
        },
      );
      props.onReviewed(reviewed);
    } catch (error) {
      setReviewError(
        error instanceof Error ? error.message : "Review could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }
  const OutcomeIcon =
    tone === "clear"
      ? CheckCircle2
      : tone === "issues"
        ? TriangleAlert
        : running
          ? LoaderCircle
          : HelpCircle;

  return (
    <div
      className={`page workspace-page investigation-detail${embedded ? " investigation-detail-embedded" : ""}`}
    >
      <div hidden={showingEvidence} className="investigation-detail-content">
        {!embedded && (
          <>
            <div className="detail-breadcrumb">
              <button className="back-link" onClick={props.onBack}>
                <ArrowLeft size={14} /> {props.backLabel ?? "Case inbox"}
              </button>
              <ChevronRight size={13} />
              <span>{run.paymentId}</span>
              <ChevronRight size={13} />
              <strong>Investigation</strong>
            </div>
            <header className="detail-case-header">
              <div>
                <h1>{run.paymentId}</h1>
                <p className="detail-case-meta">
                  {paymentVendor}
                  <span>·</span>
                  {date(paymentDate)}
                  <span>·</span>
                  {dataset?.name ?? run.datasetId}
                </p>
              </div>
              <div className="detail-case-amount">
                <strong>
                  {paymentAmount !== undefined && paymentCurrency
                    ? money(paymentAmount, paymentCurrency)
                    : "Amount not recorded"}
                </strong>
                {running ? (
                  <button
                    className="button secondary"
                    disabled={props.cancelling}
                    onClick={props.onCancel}
                  >
                    <Square size={13} />
                    {props.cancelling ? "Cancelling…" : "Cancel run"}
                  </button>
                ) : (
                  <button
                    className="button primary"
                    onClick={() => props.onReview(notes)}
                    disabled={!completed}
                  >
                    <FileCheck2 size={15} />
                    Review findings
                  </button>
                )}
              </div>
            </header>
          </>
        )}
        {embedded && (
          <div
            className="detail-dialog-actions"
            aria-label="Investigation actions"
          >
            <span>Review and investigation report</span>
            <button
              type="button"
              className="button primary"
              disabled={!completed}
              onClick={() => props.onReview(notes)}
            >
              <FileCheck2 size={14} />
              Review findings
            </button>
            <div className="detail-dialog-export">{props.exportControl}</div>
          </div>
        )}
        <div className="detail-status-row">
          <div className="detail-status-item">
            <span className="detail-status-label">Run status</span>
            {props.runStatus}
          </div>
          <div className="detail-status-item">
            <span className="detail-status-label">Business conclusion</span>
            <span className={`detail-validation-tag ${tone}`}>
              <OutcomeIcon size={13} className={running ? "spin" : undefined} />
              {businessLabel}
            </span>
          </div>
          <div className="detail-status-item">
            <span className="detail-status-label">Human review</span>
            <span
              className={`detail-validation-tag ${run.review?.decision === "accepted" ? "clear" : run.review ? "uncertain" : "pending"}`}
            >
              <UserRoundCheck size={13} />
              {run.review ? label(run.review.decision) : "Awaiting review"}
            </span>
          </div>
        </div>
        {props.stale && (
          <div className="global-alert notice" role="status">
            <Clock3 size={16} />
            {props.stale}
          </div>
        )}
        {updatedDataset && completed && (
          <div className="global-alert notice" role="status">
            <RefreshCw size={16} />
            <span>
              Update available — a newer data snapshot was imported. This result
              uses the previous snapshot.
            </span>
            <button
              className="button secondary"
              disabled={props.starting}
              onClick={props.onUpdate}
            >
              Update investigation
            </button>
          </div>
        )}
        {completed && !updatedDataset && (
          <p className="detail-saved-note">
            Saved result — reopening this case uses the existing analysis.
          </p>
        )}
        {run.error && (
          <div className="inline-error" role="alert">
            <XCircle size={16} />
            {run.error}
          </div>
        )}
        {props.showProgress !== false && (
          <InvestigationProgress
            investigation={run}
            stale={props.stale}
            onEvidence={(id) => {
              props.onFinding(null);
              selectEvidence(id);
            }}
          />
        )}
        <section
          className={`detail-outcome ${tone}`}
          aria-label="Investigation conclusion"
          aria-live="polite"
        >
          <div className="detail-outcome-copy">
            <span className={`detail-validation-tag ${tone}`}>
              <OutcomeIcon size={14} className={running ? "spin" : undefined} />
              {businessLabel}
            </span>
            <h2>{title}</h2>
            <p>{summary}</p>
            {primary?.uncertainty[0] && (
              <p className="detail-conclusion-limitation">
                {primary.uncertainty[0]}
              </p>
            )}
          </div>
          {run.actions[0] && (
            <div className="detail-next-action">
              <strong>
                <ArrowRight size={15} />
                Recommended next action
              </strong>
              <p>{run.actions[0].title}</p>
            </div>
          )}
        </section>
        <div className="detail-body-grid">
          <div className="detail-main">
            <section
              className="detail-section findings-panel"
              aria-label="Findings"
            >
              <div className="detail-section-heading">
                <h2>Findings</h2>
                <span>
                  {findings.length}{" "}
                  {findings.length === 1 ? "finding" : "findings"}
                  {uncertainty.length
                    ? ` · ${uncertainty.length} evidence ${uncertainty.length === 1 ? "gap" : "gaps"}`
                    : ""}
                </span>
              </div>
              {!findings.length && (
                <div className="detail-empty">
                  <OutcomeIcon size={25} />
                  <h3>
                    {running
                      ? "Checking the source evidence"
                      : "No findings recorded"}
                  </h3>
                  <p>
                    {running
                      ? "Findings will appear as the run progresses."
                      : "Review the activity log for the recorded run outcome."}
                  </p>
                </div>
              )}
              <div className="detail-findings-list">
                {findings.map((finding) => {
                  const gap = finding.category === "EVIDENCE_GAP";
                  const clear = finding.category === "NO_FAILURE";
                  const Icon = clear
                    ? CheckCircle2
                    : gap
                      ? HelpCircle
                      : TriangleAlert;
                  const checks = run.checks.filter((check) =>
                    check.evidenceIds.some((id) =>
                      finding.evidenceIds.includes(id),
                    ),
                  );
                  const firstId = finding.evidenceIds.find((id) =>
                    run.evidence.some((item) => item.id === id),
                  );
                  return (
                    <article
                      className={`detail-finding ${props.activeFinding === finding.id ? "active" : ""}`}
                      key={finding.id}
                    >
                      <button
                        className="finding-main detail-finding-title"
                        disabled={!firstId}
                        onClick={() => {
                          props.onFinding(finding.id);
                          selectEvidence(firstId ?? null);
                        }}
                        aria-pressed={props.activeFinding === finding.id}
                      >
                        <Icon
                          size={18}
                          className={
                            clear ? "clear" : gap ? "uncertain" : "issues"
                          }
                        />
                        <h3>{finding.title}</h3>
                        <ChevronRight size={16} />
                      </button>
                      <p className="detail-finding-copy">{finding.summary}</p>
                      <div className="detail-finding-evidence">
                        {finding.evidenceIds.map((id) => {
                          const record = run.evidence.find(
                            (item) => item.id === id,
                          );
                          return record ? (
                            <button
                              key={id}
                              title={id}
                              onClick={() => {
                                props.onFinding(finding.id);
                                selectEvidence(id);
                              }}
                            >
                              {`E${String(run.evidence.indexOf(record) + 1).padStart(2, "0")}`}{" "}
                              · {record.recordId}
                              <ArrowUpRight size={11} />
                            </button>
                          ) : (
                            <span key={id}>{id} · Record unavailable</span>
                          );
                        })}
                      </div>
                      {checks.length > 0 && (
                        <span
                          className={`detail-validation-tag ${checks.some((check) => check.status === "unknown") ? "uncertain" : "pending"}`}
                        >
                          <ShieldCheck size={13} />
                          {
                            checks.filter((check) => check.status === "passed")
                              .length
                          }{" "}
                          passed ·{" "}
                          {
                            checks.filter((check) => check.status === "failed")
                              .length
                          }{" "}
                          flagged ·{" "}
                          {
                            checks.filter((check) => check.status === "unknown")
                              .length
                          }{" "}
                          unknown
                        </span>
                      )}
                      {(finding.contradictions.length > 0 ||
                        finding.uncertainty.length > 0) && (
                        <details className="detail-finding-limitations">
                          <summary>
                            Limitations & alternative explanations
                          </summary>
                          {[
                            ...finding.contradictions,
                            ...finding.uncertainty,
                          ].map((item, index) => (
                            <p key={index}>{item}</p>
                          ))}
                        </details>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
            <section className="detail-section" aria-label="Source evidence">
              <div className="detail-section-heading">
                <div className="detail-evidence-heading">
                  <h2>Evidence</h2>
                  <button
                    type="button"
                    className="detail-evidence-toggle"
                    aria-label={
                      evidenceOpen ? "Collapse evidence" : "Expand evidence"
                    }
                    aria-expanded={evidenceOpen}
                    aria-controls={evidenceContentId}
                    onClick={() => setEvidenceOpen((open) => !open)}
                  >
                    <ChevronRight
                      className={evidenceOpen ? "is-open" : undefined}
                      size={15}
                      aria-hidden="true"
                    />
                  </button>
                </div>
                <span>{run.evidence.length} source references</span>
              </div>
              <p className="detail-evidence-caption">
                Imported snapshot
                {dataset?.asOf
                  ? ` · Observation cutoff ${date(dataset.asOf)}`
                  : ""}
              </p>
              <div id={evidenceContentId} hidden={!evidenceOpen}>
                {run.evidence.length ? (
                  <div
                    className="table-scroll"
                    tabIndex={0}
                    role="region"
                    aria-label="Evidence records"
                  >
                    <table className="detail-evidence-table">
                      <thead>
                        <tr>
                          <th>REF</th>
                          <th>ORIGINAL RECORD / SOURCE</th>
                          <th>RECORD DATE</th>
                          <th>AMOUNT</th>
                          <th>RECORD STATUS</th>
                          <th>
                            <span className="sr-only">View evidence</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {run.evidence.map((record, index) => (
                          <tr
                            className={`detail-evidence-row ${props.activeEvidence === record.id ? "selected" : ""}`}
                            key={record.id}
                          >
                            <td
                              title={record.id}
                            >{`E${String(index + 1).padStart(2, "0")}`}</td>
                            <td>
                              <button
                                className="detail-record-name"
                                onClick={() => {
                                  props.onFinding(null);
                                  selectEvidence(record.id);
                                }}
                              >
                                <strong>{record.recordId}</strong>
                                <span>{label(record.table)}</span>
                              </button>
                            </td>
                            <td>
                              {recordDate(record)
                                ? date(recordDate(record))
                                : "—"}
                            </td>
                            <td className="detail-record-amount">
                              {evidenceAmount(record) ?? "—"}
                            </td>
                            <td>
                              <span className="detail-validation-tag pending">
                                {textValue(
                                  record.record.status ??
                                    record.record.payment_status ??
                                    record.record.settlement_status ??
                                    "Recorded",
                                )}
                              </span>
                            </td>
                            <td>
                              <button
                                className="icon-button"
                                aria-label={`View evidence ${record.id}`}
                                onClick={() => {
                                  props.onFinding(null);
                                  selectEvidence(record.id);
                                }}
                              >
                                <ChevronRight size={15} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="detail-empty">
                    {running
                      ? "Source records will appear as they are retrieved."
                      : "No source evidence was recorded."}
                  </p>
                )}
              </div>
            </section>
            <details
              className="detail-secondary-section"
              aria-label="Validation"
            >
              <summary>
                <span>
                  <ShieldCheck size={16} />
                  Validation
                </span>
                <span>
                  {run.checks.filter((item) => item.status === "passed").length}{" "}
                  passed ·{" "}
                  {run.checks.filter((item) => item.status === "failed").length}{" "}
                  flagged ·{" "}
                  {
                    run.checks.filter((item) => item.status === "unknown")
                      .length
                  }{" "}
                  unknown
                  <ChevronRight size={14} />
                </span>
              </summary>
              <div className="checks-content">
                <p>
                  Checks validate the available evidence. An unknown result is
                  not a pass.
                </p>
                {run.checks.map((check) => (
                  <article className="check-card" key={check.id}>
                    <span className={`check-status ${check.status}`}>
                      {check.status === "passed" ? (
                        <CheckCircle2 size={19} />
                      ) : check.status === "failed" ? (
                        <XCircle size={19} />
                      ) : (
                        <HelpCircle size={19} />
                      )}
                    </span>
                    <div>
                      <div className="check-title">
                        <h3>{check.label}</h3>
                        <span>{label(check.status)}</span>
                      </div>
                      <p>{check.detail}</p>
                      <div className="check-source-buttons">
                        {check.evidenceIds.map((id) => (
                          <button key={id} onClick={() => selectEvidence(id)}>
                            {id}
                            <ArrowUpRight size={11} />
                          </button>
                        ))}
                      </div>
                    </div>
                  </article>
                ))}
                {!run.checks.length && <p>No checks recorded yet.</p>}
              </div>
            </details>
            <details
              className="detail-secondary-section"
              aria-label="Activity log"
            >
              <summary>
                <span>
                  <Activity size={16} />
                  Activity log
                </span>
                <span>
                  {run.events.length} recorded events
                  <ChevronRight size={14} />
                </span>
              </summary>
              <div className="activity-content">
                <dl className="detail-run-reference">
                  <div>
                    <dt>Run ID</dt>
                    <dd>
                      <code>{run.id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Snapshot</dt>
                    <dd>{date(run.updatedAt, true)}</dd>
                  </div>
                </dl>
                {props.diagnostics}
                <ol className="event-timeline">
                  {run.events.map((event) => (
                    <li key={event.id}>
                      <div className="event-header">
                        <strong>{label(event.type)}</strong>
                        <time>{date(event.at, true)}</time>
                      </div>
                      <p>{event.message}</p>
                      {event.tool && (
                        <span className="tool-tag">{event.tool}</span>
                      )}
                    </li>
                  ))}
                </ol>
                {props.timeline}
              </div>
            </details>
            {(run.actions.length > 0 || uncertainty.length > 0) && (
              <details className="detail-secondary-section">
                <summary>
                  <span>
                    <ArrowRight size={16} />
                    Next steps & evidence gaps
                  </span>
                  <ChevronRight size={14} />
                </summary>
                <div className="detail-action-list">
                  {run.actions.map((action) => (
                    <article key={action.id}>
                      <h3>{action.title}</h3>
                      <p>{action.description}</p>
                      {action.prerequisites.length > 0 && (
                        <ul>
                          {action.prerequisites.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      )}
                      <span className="detail-validation-tag pending">
                        {action.verified
                          ? "Proposal checks verified · not executed"
                          : "Proposal requires verification"}
                      </span>
                    </article>
                  ))}
                  {uncertainty.length > 0 && (
                    <div className="evidence-gaps">
                      <h3>Evidence gaps & uncertainty</h3>
                      <ul>
                        {uncertainty.map((gap) => (
                          <li key={gap}>{gap}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </details>
            )}
          </div>
          <aside
            className="detail-aside"
            role="region"
            aria-label="Next steps and human review"
          >
            <section
              className={`detail-review${completed && !run.review ? " is-awaiting-review" : ""}`}
              id="investigation-review"
            >
              <div className="detail-section-heading">
                <h2>Human review</h2>
                <UserRoundCheck size={17} />
              </div>
              {run.review ? (
                <div
                  className={`review-receipt detail-review-receipt ${run.review.decision === "needs_changes" ? "needs-changes" : ""}`}
                >
                  <span
                    className={`detail-validation-tag ${run.review.decision === "accepted" ? "clear" : "uncertain"}`}
                  >
                    <FileCheck2 size={14} />
                    {label(run.review.decision)}
                  </span>
                  <small>{date(run.review.at, true)}</small>
                  <strong>Reviewer note</strong>
                  <p>{run.review.notes || "No additional review notes."}</p>
                  <button
                    className="text-button"
                    onClick={() => props.onReview(notes)}
                  >
                    Edit human review
                    <ChevronRight size={13} />
                  </button>
                </div>
              ) : (
                <>
                  <span className="detail-validation-tag pending">
                    <UserRoundCheck size={14} />
                    Awaiting human review
                  </span>
                  <label className="detail-review-note">
                    Reviewer note
                    <textarea
                      aria-label="Reviewer note"
                      value={notes}
                      onChange={(event) => setNotes(event.target.value)}
                      placeholder="Add a review note…"
                      rows={4}
                      maxLength={4000}
                      disabled={!completed || saving}
                    />
                  </label>
                  <div className="detail-review-controls">
                    <button
                      className="button primary"
                      disabled={!completed || saving}
                      onClick={() => void saveReview("accepted")}
                    >
                      {saving ? (
                        <LoaderCircle size={14} className="spin" />
                      ) : null}
                      Accept findings
                    </button>
                    <button
                      className="button secondary"
                      disabled={!completed || saving}
                      onClick={() => void saveReview("needs_changes")}
                    >
                      Request changes
                    </button>
                  </div>
                </>
              )}
              {reviewError && (
                <p role="alert" className="inline-error">
                  {reviewError}
                </p>
              )}
              <p className="detail-review-boundary">
                Review only — no payment is approved or executed.
              </p>
              {!embedded && (
                <div className="detail-export">
                  <span>
                    <FileText size={14} />
                    Export the recorded investigation
                  </span>
                  {props.exportControl}
                </div>
              )}
            </section>
            <section className="detail-memory">
              <h2>
                <BookOpen size={16} />
                Investigation memory
              </h2>
              <span
                className={`detail-validation-tag ${run.review?.memoryId ? "clear" : "pending"}`}
              >
                {run.review?.memoryId ? "Memory approved" : "Not approved"}
              </span>
              <p>
                {run.memoryDraft?.status === "ready"
                  ? run.memoryDraft.content
                  : "Keep a confirmed lesson for future investigations."}
              </p>
              <small>Requires separate, explicit human approval.</small>
              <button
                className="button secondary"
                onClick={() => props.onReview(notes)}
                disabled={!completed}
              >
                <ArrowUpRight size={14} />
                Review memory suggestion
              </button>
            </section>
            <section className="detail-scope">
              <h2>Investigation scope</h2>
              <dl className="detail-scope-list">
                <dt>Dataset snapshot</dt>
                <dd>{dataset?.name ?? run.datasetId}</dd>
                <dt>Version</dt>
                <dd>{dataset?.version ?? "Not recorded"}</dd>
                <dt>Observation cutoff</dt>
                <dd>{date(dataset?.asOf, true)}</dd>
                <dt>Model</dt>
                <dd className="run-model">
                  {run.mode === "fixture"
                    ? "Deterministic fixture"
                    : `${run.provider || "Provider not recorded"} / ${run.model || "Model not recorded"}`}
                </dd>
              </dl>
            </section>
          </aside>
        </div>
        {!embedded && (
          <div className="workspace-bottom">
            <span>
              <ShieldCheck size={14} />
              {run.mode === "fixture"
                ? "Fixture output — no live integration claim"
                : run.mode === "local-model"
                  ? "Real model + local data — no Zetaris or PostgreSQL"
                  : "Live run — verify provider and query provenance"}
            </span>
            <span>Updated {date(run.updatedAt, true)}</span>
          </div>
        )}
      </div>
      {props.activeEvidence && (
        <div
          className={
            embedded ? "investigation-dialog-evidence-subview" : undefined
          }
          onKeyDown={(event) => {
            if (embedded && event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              selectEvidence(null);
            }
          }}
        >
          {embedded && (
            <div className="investigation-dialog-subview-heading">
              <button
                ref={evidenceBack}
                type="button"
                className="investigation-dialog-back"
                onClick={() => selectEvidence(null)}
              >
                <ArrowLeft size={15} />
                Back to investigation
              </button>
              <h3>Source evidence · Original record</h3>
            </div>
          )}
          <EvidenceDrawer
            embedded={embedded}
            evidence={run.evidence}
            selected={selected}
            onSelect={selectEvidence}
            onClose={() => selectEvidence(null)}
            queries={run.queries}
            paymentId={run.paymentId}
            findingTitle={selectedFinding?.title}
          />
        </div>
      )}
    </div>
  );
}
