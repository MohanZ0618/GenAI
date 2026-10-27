import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileCheck2,
  LoaderCircle,
  RefreshCw,
  Workflow,
  XCircle,
} from "lucide-react";
import type { InvestigationSummary } from "../../../packages/contracts/src/index";
import { api, date, label } from "./api";
import "./investigation-list.css";

type Props = {
  active: boolean;
  revision: number;
  openingId?: string;
  onOpen: (id: string, review: boolean) => void;
  onChooseCase: () => void;
};

const PAGE_SIZE = 25;
const isActive = (run: InvestigationSummary) =>
  run.status === "queued" || run.status === "running";

function conclusion(run: InvestigationSummary) {
  if (run.status !== "completed") return "Not determined";
  if (run.outcome === "anomaly_supported") return "Issues found";
  if (run.outcome === "no_anomaly_supported") return "No anomaly supported";
  if (run.outcome === "insufficient_evidence") return "More evidence needed";
  return "No conclusion recorded";
}

export function InvestigationList({
  active,
  revision,
  openingId,
  onOpen,
  onChooseCase,
}: Props) {
  const [runs, setRuns] = useState<InvestigationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState(0);
  const loaded = useRef(false);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function load(background = false) {
      if (!loaded.current) setLoading(true);
      if (!background) setRefreshing(true);
      try {
        const result = await api<{ investigations: InvestigationSummary[] }>(
          "/investigations",
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        const investigations = [...result.investigations].sort(
          (a, b) =>
            b.createdAt.localeCompare(a.createdAt) || a.id.localeCompare(b.id),
        );
        setRuns(investigations);
        loaded.current = true;
        setError("");
        if (investigations.some(isActive))
          timer = setTimeout(() => void load(true), 3000);
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load investigations.",
          );
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    }

    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [active, revision, refresh]);

  const pageCount = Math.max(1, Math.ceil(runs.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = runs.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  const runningCount = runs.filter(isActive).length;

  return (
    <div className="page investigation-list-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR INVESTIGATION RECORD</div>
          <h1>Investigations</h1>
          <p>
            Revisit what was investigated, the evidence found and each review.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={loading || refreshing}
          onClick={() => setRefresh((value) => value + 1)}
        >
          <RefreshCw size={15} aria-hidden="true" />
          {refreshing && !loading ? "Refreshing…" : "Refresh investigations"}
        </button>
      </div>

      <section
        className="investigation-history-panel"
        aria-label="Saved investigations"
        aria-busy={loading}
      >
        <div className="investigation-history-toolbar">
          <h2>Investigation history</h2>
          {!loading && (
            <span
              className="investigation-history-count"
              role="status"
              aria-atomic="true"
            >
              {runs.length}{" "}
              {runs.length === 1 ? "investigation" : "investigations"}
              {runningCount > 0 && ` · ${runningCount} in progress`}
            </span>
          )}
        </div>

        {error && (
          <div className="investigation-history-error" role="alert">
            <div>
              <strong>Could not refresh investigations.</strong>
              <p>{error}</p>
              {loaded.current && runs.length > 0 && (
                <p>Your last received records remain available below.</p>
              )}
            </div>
            <button
              className="button secondary"
              disabled={refreshing}
              onClick={() => setRefresh((value) => value + 1)}
            >
              Retry investigations
            </button>
          </div>
        )}

        {loading ? (
          <div className="investigation-history-message" role="status">
            <LoaderCircle size={20} className="spin" aria-hidden="true" />
            Loading investigation history…
          </div>
        ) : runs.length === 0 && !error ? (
          <div className="investigation-history-empty">
            <span className="investigation-history-empty-icon">
              <Workflow size={25} aria-hidden="true" />
            </span>
            <h3>No investigations yet</h3>
            <p>
              Start with a payment from the case inbox. Its investigation will
              appear here.
            </p>
            <button className="button primary" onClick={onChooseCase}>
              Choose a case <ArrowRight size={15} aria-hidden="true" />
            </button>
          </div>
        ) : runs.length > 0 ? (
          <>
            <div className="investigation-history-scroll">
              <table
                className="investigation-history-table"
                aria-label="Investigation history"
              >
                <thead>
                  <tr>
                    <th scope="col">PAYMENT / INVESTIGATION</th>
                    <th scope="col">SNAPSHOT</th>
                    <th scope="col">STARTED</th>
                    <th scope="col">STATUS / CONCLUSION</th>
                    <th scope="col">INVESTIGATION</th>
                    <th scope="col">HUMAN REVIEW</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((run) => {
                    const completed = run.status === "completed";
                    const reviewLabel = run.review
                      ? run.review.decision === "accepted"
                        ? "Accepted"
                        : "Changes requested"
                      : completed
                        ? "Awaiting review"
                        : "Not available";
                    const StatusIcon = isActive(run)
                      ? run.status === "running"
                        ? LoaderCircle
                        : Clock3
                      : completed
                        ? CheckCircle2
                        : XCircle;
                    return (
                      <tr key={run.id} data-investigation-id={run.id}>
                        <td>
                          <strong className="investigation-history-vendor">
                            {run.vendor || "Vendor unavailable"}
                          </strong>
                          <span className="investigation-history-payment mono">
                            {run.paymentId}
                          </span>
                          <p className="investigation-history-question">
                            {run.question || "Payment investigation"}
                          </p>
                        </td>
                        <td>
                          <span className="investigation-history-dataset">
                            {run.datasetName || run.datasetId}
                          </span>
                          <span
                            className="investigation-history-sub mono"
                            title={run.datasetVersion}
                          >
                            {run.datasetVersion
                              ? `Version ${run.datasetVersion.slice(0, 12)}`
                              : "Version unavailable"}
                          </span>
                          {run.datasetRemoved && (
                            <span className="investigation-history-sub">
                              Removed snapshot
                            </span>
                          )}
                        </td>
                        <td>
                          <time
                            className="investigation-history-date"
                            dateTime={run.createdAt}
                          >
                            {date(run.createdAt, true)}
                          </time>
                          <span
                            className="investigation-history-run mono"
                            title={run.id}
                          >
                            Run {run.id}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`investigation-history-status ${run.status}`}
                          >
                            <StatusIcon
                              size={12}
                              aria-hidden="true"
                              className={
                                run.status === "running" ? "spin" : undefined
                              }
                            />
                            {label(run.status)}
                          </span>
                          <span
                            className={`investigation-history-conclusion ${completed ? (run.outcome ?? "") : ""}`}
                          >
                            {conclusion(run)}
                          </span>
                        </td>
                        <td>
                          <div className="investigation-history-actions">
                            <button
                              className="investigation-history-view"
                              disabled={!!openingId}
                              aria-label={`View investigation ${run.paymentId} · ${run.id}`}
                              onClick={() => onOpen(run.id, false)}
                            >
                              {openingId === run.id
                                ? "Opening…"
                                : "View investigation"}
                              <ArrowRight size={13} aria-hidden="true" />
                            </button>
                          </div>
                        </td>
                        <td>
                          <span
                            className={`investigation-history-review ${run.review?.decision ?? ""}`}
                          >
                            {reviewLabel}
                          </span>
                          {run.review && (
                            <span className="investigation-history-sub">
                              {date(run.review.at)}
                            </span>
                          )}
                          <div className="investigation-history-actions investigation-history-review-actions">
                            <button
                              className="investigation-history-review-button"
                              disabled={!completed || !!openingId}
                              aria-label={`${run.review ? "Edit review" : "Review"} ${run.paymentId} · ${run.id}`}
                              title={
                                !completed
                                  ? "Review is available after the investigation completes."
                                  : undefined
                              }
                              onClick={() => onOpen(run.id, true)}
                            >
                              <FileCheck2 size={13} aria-hidden="true" />
                              {run.review ? "Edit review" : "Review"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="investigation-history-footer">
              <span>
                {currentPage * PAGE_SIZE + 1}–
                {Math.min((currentPage + 1) * PAGE_SIZE, runs.length)} of{" "}
                {runs.length} investigations
              </span>
              <nav aria-label="Investigation history pages">
                <button
                  aria-label="Previous investigations page"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ArrowLeft size={14} aria-hidden="true" /> Previous
                </button>
                <span>
                  Page {currentPage + 1} of {pageCount}
                </span>
                <button
                  aria-label="Next investigations page"
                  disabled={currentPage + 1 >= pageCount}
                  onClick={() => setPage(currentPage + 1)}
                >
                  Next <ArrowRight size={14} aria-hidden="true" />
                </button>
              </nav>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
