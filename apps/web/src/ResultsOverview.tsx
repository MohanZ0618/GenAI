import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, RefreshCw, Search } from "lucide-react";
import { api, label, money } from "./api";
import type { Case, Dataset } from "./api";
import { hydrateSavedResults, type QueueUpdate } from "./investigationQueue";

const groups = [
  { id: "all", title: "All results" },
  { id: "issues", title: "Issues found" },
  { id: "clear", title: "No anomaly supported" },
  { id: "uncertain", title: "More evidence needed" },
  { id: "pending", title: "Not ready" },
] as const;
type ResultGroup = (typeof groups)[number]["id"];

function resultGroup(item: Case): Exclude<ResultGroup, "all"> {
  if (!["completed", "reviewed"].includes(item.status ?? "")) return "pending";
  if (item.outcome === "anomaly_supported") return "issues";
  if (item.outcome === "no_anomaly_supported") return "clear";
  if (item.outcome === "insufficient_evidence") return "uncertain";
  return "pending";
}

function resultLabel(item: Case): string {
  const group = resultGroup(item);
  if (group !== "pending")
    return groups.find((entry) => entry.id === group)!.title;
  if (item.updateAvailable) return "Update required";
  if (["queued", "running", "failed", "cancelled"].includes(item.status ?? ""))
    return label(item.status!);
  return item.investigationId ? "Result unavailable" : "Not investigated";
}

export function ResultsOverview({
  datasetId,
  caseIds = null,
  datasets,
  busy,
  submitting = false,
  queueUpdates = {},
  actionLabel,
  onBack,
  onOpen,
}: {
  datasetId: string;
  caseIds?: string[] | null;
  datasets: Dataset[];
  busy: boolean;
  submitting?: boolean;
  queueUpdates?: Record<string, QueueUpdate>;
  actionLabel: (item: Case) => string;
  onBack: () => void;
  onOpen: (item: Case) => void;
}) {
  const [loadedCases, setCases] = useState<Case[]>([]);
  const savedResults = useRef(new Map<string, Case>());
  const loadedScope = useRef("");
  const cases = loadedCases.map((item) => {
    const update = queueUpdates[item.id];
    if (
      !update ||
      (!submitting &&
        item.investigationId &&
        update.item.investigationId !== item.investigationId)
    )
      return item;
    if (
      update.phase === "waiting" &&
      !["completed", "reviewed", "running", "queued"].includes(
        update.item.status ?? "",
      )
    )
      return {
        ...update.item,
        status: "queued",
        outcome: null,
        investigationId: undefined,
      };
    return update.item;
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [filter, setFilter] = useState<ResultGroup>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const scope = JSON.stringify([datasetId, caseIds]);
    if (loadedScope.current !== scope) {
      setLoading(true);
      setCases([]);
      loadedScope.current = scope;
    }
    setError("");
    async function load() {
      try {
        const result = await api<{ cases: Case[] }>(
          `/cases?datasetId=${encodeURIComponent(datasetId)}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        const selected = caseIds ? new Set(caseIds) : null;
        const scoped = result.cases
          .filter((item) => !selected || selected.has(item.id))
          .map((item) => {
            const saved =
              item.investigationId &&
              savedResults.current.get(item.investigationId);
            return saved &&
              ["completed", "reviewed"].includes(item.status ?? "")
              ? { ...item, outcome: saved.outcome }
              : item;
          });
        setCases(scoped);
        const hydrated = await hydrateSavedResults(scoped, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        for (const item of hydrated)
          if (item.investigationId && item.outcome)
            savedResults.current.set(item.investigationId, item);
        setCases(hydrated);
        setError("");
        if (
          submitting ||
          scoped.some((item) =>
            ["queued", "running"].includes(item.status ?? ""),
          )
        )
          timer = setTimeout(() => void load(), 3000);
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load results.",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [datasetId, caseIds, refresh, submitting]);

  useEffect(() => setPage(0), [datasetId, filter, search]);
  const filtered = cases.filter(
    (item) =>
      (filter === "all" || resultGroup(item) === filter) &&
      `${item.vendor} ${item.paymentId} ${item.datasetId}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize,
  );
  const dataset = datasets.find((item) => item.id === datasetId);
  const startError = (item: Case) => {
    const update = queueUpdates[item.id];
    return update?.phase === "error" &&
      (!item.investigationId ||
        update.item.investigationId === item.investigationId)
      ? update.error
      : undefined;
  };
  const submissionFailureCount = cases.filter((item) =>
    startError(item),
  ).length;
  const runningCount = cases.filter((item) => item.status === "running").length;
  const queuedCount = cases.filter((item) => item.status === "queued").length;
  const failedCount = cases.filter(
    (item) =>
      ["failed", "cancelled"].includes(item.status ?? "") || startError(item),
  ).length;
  const finishedCount = cases.filter(
    (item) =>
      ["completed", "reviewed", "failed", "cancelled"].includes(
        item.status ?? "",
      ) || startError(item),
  ).length;
  const total = caseIds?.length ?? cases.length;

  return (
    <div className="page results-page">
      <button className="back-link" onClick={onBack}>
        <ArrowLeft size={13} /> Case inbox
      </button>
      <div className="page-heading">
        <div>
          <h1>{caseIds ? "Selected case results" : "All case results"}</h1>
          <p>
            {datasetId === "all"
              ? "All review packets"
              : (dataset?.name ?? datasetId)}{" "}
            ·{" "}
            {caseIds
              ? `${caseIds.length} selected cases across all pages.`
              : "All pages, independent of inbox search and review filters."}
          </p>
        </div>
        <button
          className="button secondary"
          disabled={loading}
          onClick={() => setRefresh((value) => value + 1)}
        >
          <RefreshCw size={15} /> Refresh results
        </button>
      </div>
      <p className="results-note">
        Saved investigation outcomes. “No anomaly supported” reflects the
        available evidence; cases awaiting investigation remain unresolved.
      </p>
      {Boolean(
        caseIds ||
          submitting ||
          Object.keys(queueUpdates).length ||
          runningCount ||
          queuedCount,
      ) && (
        <div className="batch-progress" role="status" aria-live="polite">
          <strong>
            {finishedCount} of {total} finished ·{" "}
            {Math.max(0, total - finishedCount)} remaining
          </strong>
          <span>
            {runningCount} running · {queuedCount} waiting · {failedCount}{" "}
            failed or cancelled
            {submitting ? " · Processing one case at a time" : ""}
          </span>
          <progress
            aria-label="Investigation progress"
            value={finishedCount}
            max={Math.max(1, total)}
          />
        </div>
      )}
      {submissionFailureCount > 0 && (
        <p className="results-error" role="alert">
          {submissionFailureCount}{" "}
          {submissionFailureCount === 1 ? "case needs" : "cases need"}{" "}
          attention. Their rows show the error; completed cases are not rerun.
        </p>
      )}
      <div className="results-summary" role="group" aria-label="Filter results">
        {groups.map((group) => (
          <button
            key={group.id}
            className={`result-summary ${group.id} ${filter === group.id ? "active" : ""}`}
            aria-pressed={filter === group.id}
            onClick={() => setFilter(group.id)}
          >
            <strong>
              {loading
                ? "—"
                : group.id === "all"
                  ? cases.length
                  : cases.filter((item) => resultGroup(item) === group.id)
                      .length}
            </strong>
            <span>{group.title}</span>
          </button>
        ))}
      </div>
      <section className="inbox-section" aria-label="Case results">
        <div className="table-toolbar">
          <h2>{groups.find((group) => group.id === filter)!.title}</h2>
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="Search results"
              placeholder="Search vendor, payment or snapshot…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>
        {error && (
          <div className="results-error" role="alert">
            {error}{" "}
            <button
              className="text-button"
              onClick={() => setRefresh((value) => value + 1)}
            >
              Retry results
            </button>
          </div>
        )}
        {loading ? (
          <p className="results-message" role="status">
            Loading all case results…
          </p>
        ) : (
          <>
            <div className="table-scroll">
              <table className="case-table results-table">
                <thead>
                  <tr>
                    <th>PAYMENT / VENDOR</th>
                    <th>SNAPSHOT</th>
                    <th>AMOUNT</th>
                    <th>RESULT</th>
                    <th>
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.vendor}</strong>
                        <small className="cell-sub">{item.paymentId}</small>
                      </td>
                      <td>
                        <span className="snapshot-label">
                          {datasets.find((entry) => entry.id === item.datasetId)
                            ?.version ?? "Version unavailable"}
                          <br />
                          {item.datasetId}
                        </span>
                      </td>
                      <td>
                        <strong className="amount">
                          {money(item.amount, item.currency)}
                        </strong>
                      </td>
                      <td>
                        <span className={`result-badge ${resultGroup(item)}`}>
                          {startError(item)
                            ? ["completed", "reviewed"].includes(
                                item.status ?? "",
                              )
                              ? "Result unavailable"
                              : "Investigation failed"
                            : resultLabel(item)}
                        </span>
                        {startError(item) && (
                          <small className="cell-sub result-start-error">
                            {startError(item)}
                          </small>
                        )}
                      </td>
                      <td>
                        <button
                          className="text-button"
                          disabled={
                            busy ||
                            (submitting &&
                              (!item.investigationId ||
                                ![
                                  "completed",
                                  "reviewed",
                                  "running",
                                  "queued",
                                ].includes(item.status ?? "")))
                          }
                          onClick={() => onOpen(item)}
                          aria-label={`${actionLabel(item)} ${item.paymentId} in ${item.datasetId}`}
                        >
                          {actionLabel(item)} <ArrowRight size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!visible.length && !error && (
              <p className="results-message">
                No cases match this result filter.
              </p>
            )}
            <div className="table-footer">
              <span role="status">
                {filtered.length ? currentPage * pageSize + 1 : 0}–
                {Math.min((currentPage + 1) * pageSize, filtered.length)} of{" "}
                {filtered.length} results
              </span>
              <div className="pagination-controls">
                <button
                  className="icon-button"
                  aria-label="Previous results page"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ArrowLeft size={15} />
                </button>
                <span>
                  Page {currentPage + 1} of {pageCount}
                </span>
                <button
                  className="icon-button"
                  aria-label="Next results page"
                  disabled={currentPage + 1 >= pageCount}
                  onClick={() => setPage(currentPage + 1)}
                >
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
