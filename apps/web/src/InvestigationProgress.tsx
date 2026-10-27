import { useId, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Circle,
  Minus,
  X,
} from "lucide-react";
import type { Investigation } from "./api";
import {
  investigationProgressSummary,
  investigationSteps,
  localizeRecordedActivityText,
  progressIsOpen,
  sourceTableLabels,
} from "./investigationActivity";
import type {
  InvestigationStep,
  ProgressDisclosure,
} from "./investigationActivity";
import type { InvestigationPlayback } from "./useInvestigationPlayback";
import "./investigation-progress.css";

type Props = {
  investigation: Investigation;
  onEvidence: (id: string) => void;
  stale?: string;
  playback?: InvestigationPlayback;
};

const statuses: Record<InvestigationStep["status"], string> = {
  running: "In progress",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  unconfirmed: "Completion not recorded",
};

function StepMark({
  step,
  current,
}: {
  step: InvestigationStep;
  current: boolean;
}) {
  if (current) return <span className="investigation-progress-pulse" />;
  if (step.status === "completed") return <Check size={12} strokeWidth={2.1} />;
  if (step.status === "failed") return <X size={11} />;
  if (step.status === "cancelled" || step.status === "unconfirmed")
    return <Minus size={12} />;
  return <Circle size={8} />;
}

export function InvestigationProgress({
  investigation: run,
  onEvidence,
  stale = "",
  playback,
}: Props) {
  const contentId = useId();
  const active = run.status === "queued" || run.status === "running";
  const recordedSteps = useMemo(() => investigationSteps(run), [run]);
  const steps = playback?.steps ?? recordedSteps;
  // Polling never overrides an explicit choice; untouched completed runs collapse.
  const [preference, setPreference] = useState<ProgressDisclosure>(null);
  const viewKey = playback
    ? `${run.id}:${playback.ready ? "ready" : "process"}`
    : run.id;
  const explicitOpen =
    preference?.key === viewKey ? preference.open : undefined;
  const open =
    explicitOpen ??
    (playback ? playback.phase !== "results" : progressIsOpen(preference, run));
  const reviewing =
    !!playback && explicitOpen === true && playback.phase !== "collapsing";
  const summary = playback?.replaying
    ? "Showing recorded investigation steps"
    : investigationProgressSummary(run, playback?.fullSteps ?? recordedSteps);
  const lastVerification = [...steps]
    .reverse()
    .find((step) => step.kind === "verification");
  const legacyVisibleSteps = steps.filter(
    (step) =>
      step.kind === "tool" ||
      step.kind === "memory" ||
      step.status !== "completed" ||
      (step.kind === "verification" && step.id === lastVerification?.id),
  );
  const visibleSteps = reviewing
    ? playback!.fullSteps
    : playback
      ? steps
      : legacyVisibleSteps;
  const current = !stale
    ? playback && !reviewing
      ? visibleSteps.find((step) => step.id === playback.currentStepId)
      : active
        ? [...visibleSteps].reverse().find((step) => step.status === "running")
        : undefined
    : undefined;
  const announcement = stale
    ? "Investigation updates are temporarily unavailable. The last received records remain visible."
    : summary;

  return (
    <section
      className={`investigation-progress ${active || playback?.replaying ? "is-active" : "is-finished"} ${playback?.phase === "collapsing" && !reviewing ? "is-collapsing" : ""}`}
      aria-label="Investigation activity"
      data-playback-phase={playback?.phase}
    >
      <p
        className="investigation-progress-announcement"
        aria-live="polite"
        aria-atomic="true"
      >
        {announcement}
      </p>
      <button
        type="button"
        className="investigation-progress-toggle"
        aria-label={
          open
            ? "Collapse investigation activity"
            : "Expand investigation activity"
        }
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setPreference({ key: viewKey, open: !open })}
      >
        <span
          className={`investigation-progress-header-mark ${(active || playback?.replaying) && !stale ? "is-breathing" : ""}`}
          aria-hidden="true"
        >
          {active || playback?.replaying ? (
            <span />
          ) : run.status === "completed" ? (
            <Check size={13} />
          ) : (
            <Minus size={13} />
          )}
        </span>
        <span className="investigation-progress-heading">
          <span className="investigation-progress-title">
            <strong>Investigation activity</strong>
            <ChevronDown
              className={`investigation-progress-chevron${open ? " is-open" : ""}`}
              size={15}
              aria-hidden="true"
            />
          </span>
          <span className="investigation-progress-mode">
            {run.mode === "fixture"
              ? "Rule-based checks"
              : "Model-assisted checks"}
          </span>
          <span className="investigation-progress-caption">
            {stale ? "Updates paused" : summary}
          </span>
        </span>
      </button>
      <div
        id={contentId}
        className="investigation-progress-content"
        hidden={!open}
      >
        {stale && <p className="investigation-progress-stale">{stale}</p>}
        {!visibleSteps.length && (
          <p className="investigation-progress-empty">
            {run.status === "queued"
              ? "This investigation is queued. Its recorded steps will appear here when it starts."
              : run.status === "running"
                ? "Waiting for the next recorded step. New evidence and results will appear automatically."
                : "This investigation has no saved step-by-step records. Its saved results and source evidence remain available below."}
          </p>
        )}
        {!!visibleSteps.length && (
          <ol className="investigation-progress-steps">
            {visibleSteps.map((step) => {
              const isCurrent = current?.id === step.id;
              const presenting = isCurrent && step.status !== "running";
              const title =
                active && step.status === "running" && isCurrent
                  ? `${step.title}…`
                  : step.title;
              return (
                <li
                  key={step.id}
                  data-activity-id={step.id}
                  data-status={step.status}
                  className={`${isCurrent ? "is-current" : ""} ${step.status === "failed" ? "has-error" : ""}`}
                >
                  <span
                    className="investigation-progress-mark"
                    aria-hidden="true"
                  >
                    <StepMark step={step} current={isCurrent} />
                  </span>
                  <div className="investigation-progress-step-body">
                    <div className="investigation-progress-step-title">
                      <strong>{title}</strong>
                      {step.tool && <code>{step.tool}</code>}
                      {step.source && (
                        <span className="investigation-progress-source">
                          {step.source === "model"
                            ? "Selected by model"
                            : "Rule-driven"}
                        </span>
                      )}
                      <span className="investigation-progress-step-status">
                        {presenting
                          ? "Playing back"
                          : stale && step.status === "running"
                            ? "Waiting for updates"
                            : statuses[step.status]}
                      </span>
                    </div>
                    {step.reason && (
                      <p className="investigation-progress-reason">
                        {step.kind === "tool" ? "Purpose: " : "Details: "}
                        {step.reason}
                      </p>
                    )}
                    {isCurrent && !!step.tables?.length && (
                      <p className="investigation-progress-tables">
                        {active && step.status === "running"
                          ? "Reading: "
                          : "Source tables: "}
                        {step.tables
                          .map((table) => sourceTableLabels[table] ?? table)
                          .join(", ")}
                      </p>
                    )}
                    {step.summary && (
                      <p className="investigation-progress-summary">
                        {step.summary}
                      </p>
                    )}
                    {!!step.evidenceIds?.length && (
                      <details className="investigation-progress-evidence-disclosure">
                        <summary>Evidence ({step.evidenceIds.length})</summary>
                        <div
                          className="investigation-progress-evidence"
                          aria-label="Source evidence for this step"
                        >
                          {step.evidenceIds.slice(0, 3).map((id) => {
                            const record = run.evidence.find(
                              (item) => item.id === id,
                            );
                            if (!record) return null;
                            return (
                              <button
                                key={id}
                                type="button"
                                aria-label={`View evidence ${id}`}
                                title={record.recordId}
                                onClick={() => onEvidence(id)}
                              >
                                {record.recordId}
                                <ArrowUpRight size={11} aria-hidden="true" />
                              </button>
                            );
                          })}
                          {step.evidenceIds.length > 3 && (
                            <button
                              type="button"
                              aria-label={`View ${step.evidenceIds.length - 3} more evidence records`}
                              onClick={() => onEvidence(step.evidenceIds![3])}
                            >
                              {step.evidenceIds.length - 3} more evidence
                              records
                              <ArrowUpRight size={11} aria-hidden="true" />
                            </button>
                          )}
                        </div>
                      </details>
                    )}
                    {(!!step.tables?.length ||
                      step.queryId ||
                      step.durationMs !== undefined) && (
                      <details className="investigation-progress-provenance">
                        <summary>Source and execution details</summary>
                        {!!step.tables?.length && (
                          <p>Tables: {step.tables.join(", ")}</p>
                        )}
                        {step.queryId && (
                          <p>
                            Query ID: <code>{step.queryId}</code>
                          </p>
                        )}
                        {step.durationMs !== undefined && (
                          <p>
                            Recorded duration:{" "}
                            {step.durationMs.toLocaleString()} ms
                          </p>
                        )}
                      </details>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        {run.status === "failed" && (
          <p className="investigation-progress-end has-error">
            Investigation failed.
            {run.error
              ? `Reason: ${localizeRecordedActivityText(run.error)}`
              : "No specific reason was recorded."}{" "}
            A technical failure does not establish whether a payment is normal
            or anomalous.
          </p>
        )}
        {run.status === "cancelled" && (
          <p className="investigation-progress-end">
            {run.error
              ? localizeRecordedActivityText(run.error)
              : "The investigation stopped. Records received before it stopped remain above."}
          </p>
        )}
      </div>
    </section>
  );
}
