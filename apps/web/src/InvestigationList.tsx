import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileCheck2,
  HelpCircle,
  LoaderCircle,
  RefreshCw,
  Search,
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
const isUndetermined = (run: InvestigationSummary) =>
  run.status !== "completed" ||
  !run.outcome ||
  run.outcome === "insufficient_evidence";
type StatusFilter = "all" | InvestigationSummary["status"] | "in_progress";
type ConclusionFilter =
  | "all"
  | NonNullable<InvestigationSummary["outcome"]>
  | "undetermined";
type ReviewFilter =
  | "all"
  | "awaiting"
  | "accepted"
  | "needs_changes"
  | "unavailable";

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
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [conclusionFilter, setConclusionFilter] =
    useState<ConclusionFilter>("all");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
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

  const searchTerms = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filtered = runs.filter((run) => {
    if (
      statusFilter === "in_progress"
        ? !isActive(run)
        : statusFilter !== "all" && run.status !== statusFilter
    )
      return false;
    if (
      conclusionFilter === "undetermined"
        ? !isUndetermined(run)
        : conclusionFilter !== "all" &&
          (run.status !== "completed" || run.outcome !== conclusionFilter)
    )
      return false;
    const review =
      run.review?.decision ||
      (run.status === "completed" ? "awaiting" : "unavailable");
    if (reviewFilter !== "all" && review !== reviewFilter) return false;
    const text = [
      run.vendor,
      run.paymentId,
      run.id,
      run.question,
      run.datasetName,
      run.datasetId,
      run.datasetVersion,
    ]
      .join(" ")
      .toLowerCase();
    return searchTerms.every((term) => text.includes(term));
  });
  const hasFilters =
    searchTerms.length > 0 ||
    statusFilter !== "all" ||
    conclusionFilter !== "all" ||
    reviewFilter !== "all";
  function clearFilters() {
    setSearch("");
    setStatusFilter("all");
    setConclusionFilter("all");
    setReviewFilter("all");
    setPage(0);
  }
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  const runningCount = runs.filter(isActive).length;
  const summary = [
    {
      key: "total",
      title: "Total investigations",
      count: runs.length,
      detail: "All saved investigations",
      Icon: Workflow,
      selected: statusFilter === "all" && conclusionFilter === "all",
      status: "all",
      outcome: "all",
    },
    {
      key: "completed",
      title: "Completed",
      count: runs.filter((run) => run.status === "completed").length,
      detail: "Finished, including evidence gaps",
      Icon: CheckCircle2,
      selected: statusFilter === "completed" && conclusionFilter === "all",
      status: "completed",
      outcome: "all",
    },
    {
      key: "in-progress",
      title: "In progress",
      count: runningCount,
      detail: "Queued or running",
      Icon: Clock3,
      selected: statusFilter === "in_progress" && conclusionFilter === "all",
      status: "in_progress",
      outcome: "all",
    },
    {
      key: "failed",
      title: "Failed",
      count: runs.filter((run) => run.status === "failed").length,
      detail: "Stopped by an error",
      Icon: XCircle,
      selected: statusFilter === "failed" && conclusionFilter === "all",
      status: "failed",
      outcome: "all",
    },
    {
      key: "undetermined",
      title: "Undetermined",
      count: runs.filter(isUndetermined).length,
      detail: "No supported conclusion yet",
      Icon: HelpCircle,
      selected: statusFilter === "all" && conclusionFilter === "undetermined",
      status: "all",
      outcome: "undetermined",
    },
  ] as const;

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
        className="investigation-history-summary"
        aria-label="Investigation summary"
        aria-busy={loading}
      >
        {summary.map(
          ({ key, title, count, detail, Icon, selected, status, outcome }) => (
            <button
              key={key}
              className={`investigation-summary-card ${key} ${selected ? "selected" : ""}`}
              aria-pressed={selected}
              disabled={!loaded.current}
              onClick={() => {
                setStatusFilter(status);
                setConclusionFilter(outcome);
                setPage(0);
              }}
            >
              <span className="investigation-summary-label">
                <Icon size={16} aria-hidden="true" />
                {title}
              </span>
              <strong>{loaded.current ? count : "—"}</strong>
              <span className="investigation-summary-detail">{detail}</span>
            </button>
          ),
        )}
      </section>
      <p className="investigation-summary-note">
        Counts cover all saved investigations. Undetermined includes pending,
        failed, cancelled and evidence-insufficient investigations, so it can
        overlap with the status counts.
      </p>

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
              {hasFilters
                ? `${filtered.length} of ${runs.length}`
                : runs.length}{" "}
              {runs.length === 1 ? "investigation" : "investigations"}
              {runningCount > 0 && ` · ${runningCount} in progress`}
            </span>
          )}
        </div>

        <div
          className="investigation-history-filters"
          role="search"
          aria-label="Search and filter investigations"
        >
          <label className="investigation-history-search">
            <Search size={17} aria-hidden="true" />
            <input
              type="search"
              aria-label="Search investigations"
              placeholder="Search vendor, payment, run or snapshot…"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
            />
          </label>
          <label className="investigation-history-filter">
            <span>Status</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as StatusFilter);
                setPage(0);
              }}
            >
              <option value="all">All statuses</option>
              <option value="completed">Completed</option>
              <option value="in_progress">In progress</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
          <label className="investigation-history-filter">
            <span>Conclusion</span>
            <select
              value={conclusionFilter}
              onChange={(event) => {
                setConclusionFilter(event.target.value as ConclusionFilter);
                setPage(0);
              }}
            >
              <option value="all">All conclusions</option>
              <option value="anomaly_supported">Issues found</option>
              <option value="no_anomaly_supported">No anomaly supported</option>
              <option value="insufficient_evidence">
                More evidence needed
              </option>
              <option value="undetermined">Undetermined</option>
            </select>
          </label>
          <label className="investigation-history-filter">
            <span>Human review</span>
            <select
              value={reviewFilter}
              onChange={(event) => {
                setReviewFilter(event.target.value as ReviewFilter);
                setPage(0);
              }}
            >
              <option value="all">All reviews</option>
              <option value="awaiting">Awaiting review</option>
              <option value="accepted">Accepted</option>
              <option value="needs_changes">Changes requested</option>
              <option value="unavailable">Not available</option>
            </select>
          </label>
          {hasFilters && (
            <button
              className="investigation-history-clear"
              onClick={clearFilters}
            >
              Clear filters
            </button>
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
        ) : runs.length > 0 && filtered.length === 0 ? (
          <div className="investigation-history-empty">
            <span className="investigation-history-empty-icon">
              <Search size={25} aria-hidden="true" />
            </span>
            <h3>No matching investigations</h3>
            <p>
              Try another search or clear the filters to see all saved
              investigations.
            </p>
            <button className="button secondary" onClick={clearFilters}>
              Clear search and filters
            </button>
          </div>
        ) : filtered.length > 0 ? (
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
                {Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)} of{" "}
                {filtered.length} investigations
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
