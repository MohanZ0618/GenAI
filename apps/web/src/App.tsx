import type {
  ApprovedMemory,
  MemoryDraft,
} from "../../../packages/contracts/src/index";
import { parseTime } from "../../../packages/contracts/src/index";
import Decimal from "decimal.js";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock3,
  Database,
  FileCheck2,
  FileJson,
  FileSpreadsheet,
  FileText,
  Fingerprint,
  FolderOpen,
  HelpCircle,
  Inbox,
  Layers3,
  LoaderCircle,
  PanelLeftClose,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  Upload,
  Workflow,
  X,
  XCircle,
} from "lucide-react";
import { api, date, label, money, textValue } from "./api";
import type { Case, Dataset, Evidence, Health, Investigation } from "./api";
import { ResultsOverview } from "./ResultsOverview";
import { ModalShell } from "./ModalShell";
import { useRemoval } from "./useRemoval";
import { runInvestigationQueue, type QueueUpdate } from "./investigationQueue";

type Page =
  | "inbox"
  | "results"
  | "workspace"
  | "datasets"
  | "guide"
  | "memories";
type Modal = "import" | "review" | null;
const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const isReviewedCase = (item: Case) =>
  item.status === "completed" || item.status === "reviewed";
const caseAction = (item: Case) =>
  item.updateAvailable
    ? "Update investigation"
    : item.status === "completed" || item.status === "reviewed"
      ? "View result"
      : item.status === "running" || item.status === "queued"
        ? "View run"
        : item.status === "failed" || item.status === "cancelled"
          ? "Retry investigation"
          : "Investigate";
const storage = {
  get: (key: string) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set: (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* Persistence is optional. */
    }
  },
};

function App() {
  const [page, setPage] = useState<Page>("inbox");
  const [health, setHealth] = useState<Health | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [historicalDataset, setHistoricalDataset] = useState<Dataset | null>(
    null,
  );
  const [datasetSearch, setDatasetSearch] = useState("");
  const [libraryCases, setLibraryCases] = useState<Case[] | null>(null);
  const [libraryError, setLibraryError] = useState("");
  const [datasetId, setDatasetId] = useState("all");
  const [cases, setCases] = useState<Case[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [casesRevision, setCasesRevision] = useState(0);
  const [resultsScope, setResultsScope] = useState<{
    datasetId: string;
    caseIds: string[] | null;
  }>({ datasetId: "all", caseIds: null });
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [queueUpdates, setQueueUpdates] = useState<Record<string, QueueUpdate>>(
    {},
  );
  const [investigation, setInvestigation] = useState<Investigation | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [casesLoading, setCasesLoading] = useState(false);
  const [loadedDatasetId, setLoadedDatasetId] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<{
    field: "amount" | "date";
    direction: "asc" | "desc";
  } | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [activeFinding, setActiveFinding] = useState<string | null>(null);
  const [workspaceTab, setWorkspaceTab] = useState<
    "findings" | "activity" | "checks"
  >("findings");
  const [modal, setModal] = useState<Modal>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const initialResume = useRef(false);
  const casesPending = casesLoading || loadedDatasetId !== datasetId;
  const currentDataset = datasets.find((item) => item.id === datasetId);
  const filteredDatasets = datasets.filter((item) =>
    `${item.name} ${item.id} ${item.version}`
      .toLowerCase()
      .includes(datasetSearch.trim().toLowerCase()),
  );
  const reviewedCount = cases.filter(isReviewedCase).length;
  const datasetProgress = new Map(
    datasets.map((dataset) => {
      const items =
        libraryCases?.filter((item) => item.datasetId === dataset.id) ?? [];
      const completed = items.filter(isReviewedCase).length;
      const running = items.filter(
        (item) => item.status === "running" || item.status === "queued",
      ).length;
      const started = items.some(
        (item) =>
          item.investigationId || (item.status && item.status !== "unreviewed"),
      );
      const status =
        items.length === 0
          ? "empty"
          : completed === items.length
            ? "completed"
            : started
              ? "progress"
              : "new";
      return [dataset.id, { status, completed, total: items.length, running }];
    }),
  );
  const progressTotals = [...datasetProgress.values()];
  const searchedCases = cases.filter((item) =>
    `${item.vendor} ${item.paymentId} ${item.symptom}`
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  );
  const filterCounts: Record<string, number> = {
    all: searchedCases.length,
    reviewed: searchedCases.filter(isReviewedCase).length,
    unreviewed: searchedCases.filter((item) => !isReviewedCase(item)).length,
  };
  const filteredCases = searchedCases.filter(
    (item) =>
      filter === "all" ||
      (filter === "reviewed" ? isReviewedCase(item) : !isReviewedCase(item)),
  );
  if (sort) {
    filteredCases.sort((a, b) => {
      // Different currencies remain separate; amounts are not exchange-rate adjusted.
      const currencyOrder =
        sort.field === "amount" ? a.currency.localeCompare(b.currency) : 0;
      const valueOrder =
        sort.field === "amount"
          ? new Decimal(a.amount).comparedTo(b.amount)
          : parseTime(a.date) - parseTime(b.date);
      return (
        currencyOrder ||
        (sort.direction === "asc" ? valueOrder : -valueOrder) ||
        a.id.localeCompare(b.id)
      );
    });
  }
  const pageCount = Math.max(1, Math.ceil(filteredCases.length / pageSize));
  const currentPage = Math.min(pageIndex, pageCount - 1);
  const visibleCases = filteredCases.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize,
  );
  const checkedCases = cases.filter((item) => checkedIds.has(item.id));
  const allCasesChecked =
    cases.length > 0 && checkedCases.length === cases.length;
  const checkedOnPage = visibleCases.filter((item) =>
    checkedIds.has(item.id),
  ).length;
  const selectedCase =
    loading || casesPending
      ? undefined
      : (visibleCases.find((item) => item.id === selectedId) ??
        visibleCases[0]);
  const running = investigation && !TERMINAL.has(investigation.status);
  const workspaceCase = cases.find(
    (item) =>
      item.paymentId === investigation?.paymentId &&
      item.datasetId === investigation?.datasetId,
  );
  const runDataset =
    datasets.find((item) => item.id === investigation?.datasetId) ??
    (historicalDataset?.id === investigation?.datasetId
      ? historicalDataset
      : undefined);
  useEffect(() => {
    if (
      !investigation ||
      datasets.some((item) => item.id === investigation.datasetId)
    )
      return;
    let alive = true;
    api<{ dataset: Dataset }>(
      `/datasets/${encodeURIComponent(investigation.datasetId)}`,
    )
      .then(({ dataset }) => {
        if (alive) setHistoricalDataset(dataset);
      })
      .catch(() => {
        /* Existing evidence remains available if source metadata cannot be loaded. */
      });
    return () => {
      alive = false;
    };
  }, [investigation?.datasetId, datasets]);
  const updatedDataset =
    runDataset &&
    datasets
      .filter(
        (item) =>
          item.name === runDataset.name &&
          item.createdAt > runDataset.createdAt &&
          item.id !== runDataset.id &&
          (!item.focusPaymentIds ||
            item.focusPaymentIds.includes(investigation!.paymentId)),
      )
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError("");
    const [healthResult, datasetResult] = await Promise.allSettled([
      api<Health>("/health"),
      api<{ datasets: Dataset[] }>("/datasets"),
    ]);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (datasetResult.status === "fulfilled") {
      setDatasets(datasetResult.value.datasets);
      setDatasetId((previous) =>
        previous === "all" ||
        datasetResult.value.datasets.some((item) => item.id === previous)
          ? previous
          : "all",
      );
    }
    const failed = [healthResult, datasetResult].find(
      (result) => result.status === "rejected",
    );
    if (failed?.status === "rejected")
      setError(
        failed.reason instanceof Error
          ? failed.reason.message
          : "Unable to load workspace.",
      );
    setLoading(false);
  }, []);

  const rememberRun = useCallback((run: Investigation) => {
    setInvestigation(run);
    storage.set("fintrace:last-investigation", run.id);
    const url = new URL(window.location.href);
    url.searchParams.set("investigation", run.id);
    window.history.replaceState({}, "", url);
  }, []);

  const datasetRemoval = useRemoval({
    kind: "dataset",
    items: datasets.map((item) => ({ id: item.id, label: item.name })),
    visibleItems: filteredDatasets.map((item) => ({
      id: item.id,
      label: item.name,
    })),
    endpoint: "/datasets/removal",
    onChanged: async (ids, removed) => {
      if (removed && ids.includes(datasetId)) setDatasetId("all");
      setCasesRevision((previous) => previous + 1);
      await loadBase();
    },
  });

  useEffect(() => {
    void loadBase();
  }, [loadBase]);
  useEffect(() => {
    if (page !== "datasets") return;
    let alive = true;
    const refresh = async () => {
      try {
        const result = await api<{ cases: Case[] }>("/cases?datasetId=all");
        if (alive) {
          setLibraryCases(result.cases);
          setLibraryError("");
        }
      } catch (reason) {
        if (alive) {
          setLibraryCases(null);
          setLibraryError(
            reason instanceof Error
              ? reason.message
              : "Unable to load dataset progress.",
          );
        }
      }
    };
    setLibraryCases(null);
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [page, datasets, casesRevision]);
  useEffect(() => {
    setPageIndex(0);
  }, [search, filter, datasetId, pageSize, sort]);
  useEffect(() => setCheckedIds(new Set()), [datasetId]);
  useEffect(() => {
    if (!investigation) return;
    setCases((previous) =>
      previous.map((item) =>
        item.datasetId === investigation.datasetId &&
        item.paymentId === investigation.paymentId
          ? {
              ...item,
              status: investigation.review ? "reviewed" : investigation.status,
              investigationId: investigation.id,
              outcome:
                investigation.status === "completed"
                  ? investigation.outcome
                  : null,
              updateAvailable: false,
            }
          : item,
      ),
    );
  }, [investigation?.id, investigation?.status, investigation?.review]);
  useEffect(() => {
    if (!datasetId) {
      setCases([]);
      return;
    }
    let alive = true;
    setCasesLoading(true);
    api<{ cases: Case[] }>(`/cases?datasetId=${encodeURIComponent(datasetId)}`)
      .then((result) => {
        if (alive) {
          setCases(result.cases);
          setCheckedIds(
            (previous) =>
              new Set(
                [...previous].filter((id) =>
                  result.cases.some((item) => item.id === id),
                ),
              ),
          );
          setLoadedDatasetId(datasetId);
          setSelectedId((previous) =>
            result.cases.some((item) => item.id === previous)
              ? previous
              : (result.cases[0]?.id ?? ""),
          );
        }
      })
      .catch((reason) => {
        if (alive) {
          setCases([]);
          setLoadedDatasetId(datasetId);
          setError(reason.message);
        }
      })
      .finally(() => {
        if (alive) setCasesLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [datasetId, datasets, casesRevision]);

  useEffect(() => {
    if (loading || initialResume.current) return;
    initialResume.current = true;
    const runId =
      new URLSearchParams(window.location.search).get("investigation") ??
      storage.get("fintrace:last-investigation");
    if (!runId) return;
    api<Investigation>(`/investigations/${encodeURIComponent(runId)}`)
      .then((run) => {
        rememberRun(run);
        setPage("workspace");
        setActiveEvidence(
          new URLSearchParams(window.location.search).get("evidence"),
        );
        setDatasetId(
          datasets.some((item) => item.id === run.datasetId)
            ? run.datasetId
            : "all",
        );
      })
      .catch(() => {
        setNotice(
          "The previous investigation is unavailable. You can start a new one from the inbox.",
        );
      });
  }, [loading, rememberRun]);

  useEffect(() => {
    if (!investigation || TERMINAL.has(investigation.status)) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      api<Investigation>(
        `/investigations/${encodeURIComponent(investigation.id)}`,
      )
        .then((run) => {
          if (!stopped) {
            setInvestigation(run);
            setStale("");
          }
        })
        .catch((reason) => {
          if (!stopped)
            setStale(
              `Updates paused: ${reason.message} The last received result remains visible.`,
            );
        });
    }, 1500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [investigation?.id, investigation?.status]);

  async function startInvestigation(item = selectedCase) {
    if (!item || starting) return;
    if (
      batchSubmitting &&
      (!item.investigationId ||
        !["completed", "reviewed", "running", "queued"].includes(
          item.status ?? "",
        ))
    )
      return;
    setStarting(true);
    setError("");
    setStale("");
    setActiveEvidence(null);
    setActiveFinding(null);
    setWorkspaceTab("findings");
    try {
      const reusable =
        !item.updateAvailable &&
        item.investigationId &&
        ["completed", "reviewed", "running", "queued"].includes(
          item.status || "",
        );
      const run = reusable
        ? await api<Investigation>(
            `/investigations/${encodeURIComponent(item.investigationId!)}`,
          )
        : await api<Investigation>("/investigations", {
            method: "POST",
            body: JSON.stringify({
              datasetId: item.datasetId ?? datasetId,
              paymentId: item.paymentId,
            }),
          });
      rememberRun(run);
      setSelectedId(item.id);
      setPage("workspace");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not start investigation.",
      );
    } finally {
      setStarting(false);
    }
  }

  function toggleChecked(id: string) {
    setCheckedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function viewResults(items: Case[] | null) {
    setResultsScope({
      datasetId,
      caseIds:
        items && items.length !== cases.length
          ? items.map((item) => item.id)
          : null,
    });
    navigate("results");
  }

  async function investigateSelected() {
    if (!checkedCases.length || batchSubmitting || starting || casesPending)
      return;
    const selected = [...checkedCases];
    setResultsScope({
      datasetId,
      caseIds: allCasesChecked ? null : selected.map((item) => item.id),
    });
    setQueueUpdates({});
    setBatchSubmitting(true);
    navigate("results");
    try {
      await runInvestigationQueue(selected, (update) => {
        setQueueUpdates((previous) => ({
          ...previous,
          [update.item.id]: update,
        }));
        setCases((previous) =>
          previous.map((item) =>
            item.id === update.item.id ? update.item : item,
          ),
        );
      });
    } finally {
      setBatchSubmitting(false);
      setCasesRevision((value) => value + 1);
    }
  }

  async function updateInvestigation() {
    if (!updatedDataset || !investigation || starting || running) return;
    try {
      const result = await api<{ cases: Case[] }>(
        `/cases?datasetId=${encodeURIComponent(updatedDataset.id)}`,
      );
      const item = result.cases.find(
        (entry) => entry.paymentId === investigation.paymentId,
      );
      if (!item)
        throw new Error(
          "This payment is not available in the updated dataset.",
        );
      setDatasetId(updatedDataset.id);
      await startInvestigation(item);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not load the updated dataset.",
      );
    }
  }

  async function cancelInvestigation() {
    if (!investigation) return;
    setCancelling(true);
    setError("");
    try {
      await api(
        `/investigations/${encodeURIComponent(investigation.id)}/cancel`,
        { method: "POST" },
      );
      const run = await api<Investigation>(
        `/investigations/${encodeURIComponent(investigation.id)}`,
      );
      setInvestigation(run);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not cancel investigation.",
      );
    } finally {
      setCancelling(false);
    }
  }

  async function exportRun(format: "json" | "csv" | "html") {
    if (!investigation) return;
    setExporting(true);
    setError("");
    try {
      const response = await fetch(
        `/api/investigations/${encodeURIComponent(investigation.id)}/export?format=${format}`,
      );
      if (!response.ok) throw new Error(`Export failed (${response.status}).`);
      download(await response.blob(), `fintrace-${investigation.id}.${format}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  async function downloadTemplate() {
    try {
      const template = await api("/templates");
      download(
        new Blob([JSON.stringify(template, null, 2)], {
          type: "application/json",
        }),
        "fintrace-dataset-template.json",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Template could not be downloaded.",
      );
    }
  }

  function navigate(next: Page) {
    setPage(next);
    setSidebarOpen(false);
    setError("");
  }
  function toggleSort(field: "amount" | "date") {
    setSort((previous) => ({
      field,
      direction:
        previous?.field === field && previous.direction === "asc"
          ? "desc"
          : "asc",
    }));
  }
  const title = {
    inbox: "Case inbox",
    results: resultsScope.caseIds
      ? "Selected case results"
      : "All case results",
    workspace: "Investigation",
    datasets: "Dataset library",
    guide: "The evidence standard",
    memories: "Investigation memories",
  }[page];
  const evidence = investigation?.evidence ?? [];
  const chosenEvidence =
    evidence.find((item) => item.id === activeEvidence) ?? evidence[0];
  const outcome = investigation?.outcome;
  const evidenceGaps = [
    ...new Set([
      ...(investigation?.findings.flatMap((finding) => finding.uncertainty) ??
        []),
      ...(investigation?.checks
        .filter((check) => check.status === "unknown")
        .map((check) => check.detail) ?? []),
    ]),
  ];

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-open" : ""}`}>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            navigate("inbox");
          }}
          aria-label="FinTrace home"
        >
          <span className="brand-icon">
            <Fingerprint size={23} />
          </span>
          <span>
            Fin<span className="brand-light">Trace</span>
            <span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-avatar">F</span>
          <span>
            Finance workspace<small>Local workspace</small>
          </span>
          <ChevronDown size={13} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          <NavItem
            icon={<Inbox size={18} />}
            text="Case inbox"
            active={page === "inbox" || page === "results"}
            onClick={() => navigate("inbox")}
            count={cases.length}
          />
          <NavItem
            icon={<Workflow size={18} />}
            text="Investigation"
            active={page === "workspace"}
            onClick={() => navigate("workspace")}
            dot={!!running}
          />
          <NavItem
            icon={<Database size={18} />}
            text="Datasets"
            active={page === "datasets"}
            onClick={() => navigate("datasets")}
          />
          <NavItem
            icon={<BookOpen size={18} />}
            text="Investigation memories"
            active={page === "memories"}
            onClick={() => navigate("memories")}
          />
        </nav>
        <div className="sidebar-note">
          <span className="small-icon">
            <ShieldCheck size={17} />
          </span>
          <strong>
            Every conclusion.
            <br />A traceable foundation.
          </strong>
          <p>Source records, verified checks, and a human final decision.</p>
          <button onClick={() => navigate("guide")}>
            Our evidence standard <ArrowUpRight size={14} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <button className="help-link" onClick={() => navigate("guide")}>
            <HelpCircle size={17} /> How FinTrace works
          </button>
          <div className="profile">
            <span className="profile-avatar">FO</span>
            <span>
              Finance operations<small>Review workspace</small>
            </span>
            <span className="local-label">LOCAL</span>
          </div>
        </div>
      </aside>
      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label="Toggle navigation"
            >
              <PanelLeftClose size={19} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <span className={`connection ${health ? "connected" : ""}`}>
              <span />
              {health ? "API connected" : "API unavailable"}
            </span>
            <div className="top-avatar">FO</div>
          </div>
        </header>
        <div className={`mode-banner ${health?.mode === "live" ? "live" : ""}`}>
          <span className="mode-symbol">
            {health?.mode === "live" ? <Activity size={16} /> : <FlaskIcon />}
          </span>
          <div>
            <strong>
              {health?.mode === "fixture"
                ? "Offline fixture"
                : health?.mode === "local-model"
                  ? `${health.provider === "openai" ? "OpenAI" : health.provider} + local data`
                  : health?.mode === "live"
                    ? "Live integration mode"
                    : "Connection not verified"}
            </strong>
            <span>
              {health?.mode === "fixture"
                ? "Deterministic rules · no live model or Zetaris"
                : health?.mode === "local-model"
                  ? `${health.model} · Real model calls · local snapshots · no Zetaris or PostgreSQL`
                  : health?.mode === "live"
                    ? "Review integration status before running an investigation."
                    : "Start the API server to load datasets and investigations."}
            </span>
          </div>
          <button
            onClick={() => void loadBase()}
            aria-label="Refresh API connection"
          >
            <RefreshCw size={14} />
          </button>
        </div>
        {error && (
          <div className="global-alert error" role="alert">
            <XCircle size={17} />
            <span>{error}</span>
            <button onClick={() => setError("")} aria-label="Dismiss error">
              <X size={15} />
            </button>
          </div>
        )}
        {notice && (
          <div className="global-alert notice" role="status">
            <CheckCircle2 size={17} />
            <span>{notice}</span>
            <button onClick={() => setNotice("")} aria-label="Dismiss notice">
              <X size={15} />
            </button>
          </div>
        )}

        {page === "memories" && <MemoryPanel />}
        {page === "inbox" && (
          <div className="page inbox-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">EVIDENCE-LED FINANCE OPERATIONS</div>
                <h1>Make sense of every exception.</h1>
                <p>
                  Follow the evidence. Understand the discrepancy. Decide with
                  confidence.
                </p>
              </div>
              <button
                className="button primary"
                onClick={() => setModal("import")}
              >
                <Plus size={16} /> Import dataset
              </button>
            </div>
            <div className="stats-grid">
              <Stat
                icon={<Inbox size={19} />}
                label="Total cases"
                value={casesPending ? "—" : String(cases.length)}
                detail="Available for investigation"
              />
              <Stat
                icon={<FileCheck2 size={19} />}
                label="Awaiting review"
                value={
                  casesPending ? "—" : String(cases.length - reviewedCount)
                }
                detail="Cases without a completed investigation or saved review"
              />
              <Stat
                icon={<RefreshCw size={19} />}
                label="Updates available"
                value={
                  casesPending
                    ? "—"
                    : String(
                        cases.filter((item) => item.updateAvailable).length,
                      )
                }
                detail="New snapshots ready for investigation"
              />
              {currentDataset && (
                <CopyVersion
                  key={currentDataset.version}
                  value={currentDataset.version}
                />
              )}
            </div>
            <section className="inbox-section">
              <div className="section-header">
                <div>
                  <h2>
                    Payment exceptions{" "}
                    <span className="count-tag">{filteredCases.length}</span>
                  </h2>
                  <p>Your starting point for a defensible investigation.</p>
                </div>
                <label className="dataset-select">
                  <Database size={14} />
                  <select
                    aria-label="Active dataset"
                    value={datasetId}
                    onChange={(event) => setDatasetId(event.target.value)}
                  >
                    <option value="all">All review packets</option>
                    {datasets.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · {item.id.slice(-6)}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} />
                </label>
              </div>
              <div className="table-toolbar">
                <div
                  className="filter-tabs"
                  role="group"
                  aria-label="Filter cases"
                >
                  {[
                    ["all", "All cases"],
                    ["unreviewed", "Unreviewed"],
                    ["reviewed", "Reviewed"],
                  ].map(([key, text]) => (
                    <button
                      className={filter === key ? "active" : ""}
                      key={key}
                      aria-label={text}
                      aria-pressed={filter === key}
                      onClick={() => setFilter(key)}
                    >
                      {text}{" "}
                      <span className="filter-count">
                        {casesPending ? "—" : filterCounts[key]}
                      </span>
                    </button>
                  ))}
                </div>
                <label className="search-field">
                  <Search size={16} />
                  <input
                    placeholder="Search vendor, payment or exception…"
                    aria-label="Search cases"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  {search && (
                    <button
                      onClick={() => setSearch("")}
                      aria-label="Clear search"
                    >
                      <X size={13} />
                    </button>
                  )}
                </label>
              </div>
              {!loading && !casesPending && cases.length > 0 && (
                <div
                  className="batch-toolbar"
                  role="group"
                  aria-label="Batch investigation"
                >
                  <strong aria-live="polite">
                    {checkedCases.length} selected
                  </strong>
                  <button
                    className="text-button"
                    disabled={batchSubmitting}
                    onClick={() =>
                      setCheckedIds(new Set(cases.map((item) => item.id)))
                    }
                  >
                    Select all {cases.length} cases
                  </button>
                  {checkedCases.length > 0 && (
                    <button
                      className="text-button"
                      disabled={batchSubmitting}
                      onClick={() => setCheckedIds(new Set())}
                    >
                      Clear selection
                    </button>
                  )}
                  <span className="batch-scope-note">
                    Selection includes all pages.
                  </span>
                  {batchSubmitting && (
                    <button
                      className="text-button"
                      onClick={() => navigate("results")}
                    >
                      View investigation progress
                    </button>
                  )}
                  <button
                    className="button primary"
                    disabled={
                      !checkedCases.length || starting || batchSubmitting
                    }
                    onClick={() => void investigateSelected()}
                  >
                    <Sparkles size={15} /> Investigate selected (
                    {checkedCases.length})
                  </button>
                </div>
              )}
              {loading || casesPending ? (
                <Loading text="Loading payment cases…" />
              ) : !cases.length ? (
                <Empty
                  icon={<FolderOpen size={28} />}
                  title="Your next investigation starts here"
                  text="Import a dataset, or check that the API has a fixture dataset available."
                  action={
                    <button
                      className="button secondary"
                      onClick={() => setModal("import")}
                    >
                      <Upload size={15} /> Import dataset
                    </button>
                  }
                />
              ) : !filteredCases.length ? (
                <Empty
                  icon={<Search size={28} />}
                  title="No matching cases"
                  text="Try another search or select a different filter."
                />
              ) : (
                <div className="table-scroll">
                  <table className="case-table">
                    <thead>
                      <tr>
                        <th className="selection-cell">
                          <input
                            type="checkbox"
                            aria-label="Select all cases on this page"
                            checked={
                              visibleCases.length > 0 &&
                              checkedOnPage === visibleCases.length
                            }
                            ref={(element) => {
                              if (element)
                                element.indeterminate =
                                  checkedOnPage > 0 &&
                                  checkedOnPage < visibleCases.length;
                            }}
                            disabled={batchSubmitting}
                            onChange={(event) => {
                              const checked = event.target.checked;
                              setCheckedIds((previous) => {
                                const next = new Set(previous);
                                for (const item of visibleCases) {
                                  if (checked) next.add(item.id);
                                  else next.delete(item.id);
                                }
                                return next;
                              });
                            }}
                          />
                        </th>
                        <th>PAYMENT / VENDOR</th>
                        <th
                          aria-sort={
                            sort?.field === "amount"
                              ? sort.direction === "asc"
                                ? "ascending"
                                : "descending"
                              : "none"
                          }
                        >
                          <button
                            className="sort-button"
                            onClick={() => toggleSort("amount")}
                            aria-label="Sort by amount"
                            title="Sort amounts within each currency"
                          >
                            AMOUNT{" "}
                            <span aria-hidden="true">
                              {sort?.field === "amount"
                                ? sort.direction === "asc"
                                  ? "↑"
                                  : "↓"
                                : "↕"}
                            </span>
                          </button>
                        </th>
                        <th>OBSERVED EXCEPTION</th>
                        <th
                          aria-sort={
                            sort?.field === "date"
                              ? sort.direction === "asc"
                                ? "ascending"
                                : "descending"
                              : "none"
                          }
                        >
                          <button
                            className="sort-button"
                            onClick={() => toggleSort("date")}
                            aria-label="Sort by date"
                          >
                            DATE{" "}
                            <span aria-hidden="true">
                              {sort?.field === "date"
                                ? sort.direction === "asc"
                                  ? "↑"
                                  : "↓"
                                : "↕"}
                            </span>
                          </button>
                        </th>
                        <th>STATUS</th>
                        <th>
                          <span className="sr-only">Action</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleCases.map((item) => (
                        <tr
                          key={item.id}
                          aria-selected={checkedIds.has(item.id)}
                          className={
                            selectedCase?.id === item.id ? "selected" : ""
                          }
                          tabIndex={0}
                          onClick={() => setSelectedId(item.id)}
                          onKeyDown={(event) => {
                            if (
                              event.target === event.currentTarget &&
                              (event.key === "Enter" || event.key === " ")
                            ) {
                              event.preventDefault();
                              setSelectedId(item.id);
                            }
                          }}
                        >
                          <td
                            className="selection-cell"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <input
                              type="checkbox"
                              aria-label={`Select ${item.paymentId} in ${item.datasetId}`}
                              checked={checkedIds.has(item.id)}
                              disabled={batchSubmitting}
                              onChange={() => toggleChecked(item.id)}
                            />
                          </td>
                          <td>
                            <div className="vendor-cell">
                              <span
                                className={`vendor-avatar color-${hash(item.vendor) % 4}`}
                              >
                                {initials(item.vendor)}
                              </span>
                              <span>
                                <strong>{item.vendor}</strong>
                                <small>{item.paymentId}</small>
                                {datasetId === "all" && (
                                  <small className="snapshot-label">
                                    {datasets.find(
                                      (dataset) =>
                                        dataset.id === item.datasetId,
                                    )?.version ?? "Version unavailable"}{" "}
                                    · {item.datasetId}
                                  </small>
                                )}
                              </span>
                            </div>
                          </td>
                          <td>
                            <strong className="amount">
                              {money(item.amount, item.currency)}
                            </strong>
                            <small className="cell-sub">{item.currency}</small>
                          </td>
                          <td>
                            <span className="symptom">{item.symptom}</span>
                          </td>
                          <td className="date-cell">{date(item.date)}</td>
                          <td>
                            <span
                              className={`status-pill ${item.updateAvailable ? "update" : ["completed", "reviewed"].includes(item.status || "") ? "success" : ""}`}
                            >
                              <span />
                              {item.updateAvailable
                                ? "Update available"
                                : label(item.status ?? "unreviewed")}
                            </span>
                          </td>
                          <td>
                            <button
                              className="row-action"
                              disabled={starting || batchSubmitting}
                              onClick={(event) => {
                                event.stopPropagation();
                                void startInvestigation(item);
                              }}
                              aria-label={`${caseAction(item)} ${item.paymentId}`}
                              title={caseAction(item)}
                            >
                              <ArrowUpRight size={18} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="table-footer">
                <span role="status" aria-live="polite" className="page-range">
                  {loading || casesPending
                    ? "Loading cases…"
                    : `${filteredCases.length ? currentPage * pageSize + 1 : 0}–${Math.min((currentPage + 1) * pageSize, filteredCases.length)} of ${filteredCases.length} cases`}
                </span>
                <div className="pagination-controls">
                  <label>
                    Rows per page
                    <select
                      aria-label="Rows per page"
                      value={pageSize}
                      onChange={(event) =>
                        setPageSize(Number(event.target.value))
                      }
                    >
                      {[10, 25, 50].map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="icon-button"
                    aria-label="Previous page"
                    disabled={loading || casesPending || currentPage === 0}
                    onClick={() => setPageIndex(currentPage - 1)}
                  >
                    <ArrowLeft size={15} />
                  </button>
                  <span>
                    Page {currentPage + 1} of {pageCount}
                  </span>
                  <button
                    className="icon-button"
                    aria-label="Next page"
                    disabled={
                      loading || casesPending || currentPage + 1 >= pageCount
                    }
                    onClick={() => setPageIndex(currentPage + 1)}
                  >
                    <ArrowRight size={15} />
                  </button>
                </div>
              </div>
              <div className="all-results-action">
                <span>
                  See outcomes for every case in the selected dataset scope.
                </span>
                <button
                  className="button secondary"
                  disabled={
                    loading || casesPending || !cases.length || batchSubmitting
                  }
                  onClick={() =>
                    viewResults(checkedCases.length ? checkedCases : null)
                  }
                >
                  <Layers3 size={16} />{" "}
                  {checkedCases.length && !allCasesChecked
                    ? `View selected results (${checkedCases.length})`
                    : "View All Results"}{" "}
                  <ArrowRight size={15} />
                </button>
              </div>
            </section>
            {selectedCase && !checkedCases.length && (
              <div className="selected-case-bar">
                <span className="selected-case-icon">
                  <FileText size={20} />
                </span>
                <div>
                  <small>SELECTED CASE</small>
                  <strong>
                    {selectedCase.vendor}{" "}
                    <span>· {selectedCase.paymentId}</span>
                  </strong>
                </div>
                <span className="selected-amount">
                  {money(selectedCase.amount, selectedCase.currency)}
                </span>
                <button
                  className="button primary"
                  disabled={starting || batchSubmitting}
                  onClick={() => void startInvestigation()}
                >
                  {starting ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Sparkles size={15} />
                  )}{" "}
                  {caseAction(selectedCase) === "Investigate"
                    ? "Start investigation"
                    : caseAction(selectedCase)}
                  <ArrowRight size={15} />
                </button>
                {running && (
                  <button
                    className="text-button"
                    onClick={() => navigate("workspace")}
                  >
                    View run
                  </button>
                )}
              </div>
            )}
            <div className="quiet-footer">
              <Fingerprint size={15} />
              <span>
                {datasetId === "all"
                  ? "Multiple datasets · view cutoff and coverage per snapshot in Datasets."
                  : currentDataset
                    ? `${currentDataset.version} · Cutoff ${date(currentDataset.asOf, true)} · Coverage ${coverageLabel(currentDataset.coverage)}`
                    : "Snapshot information unavailable."}{" "}
                Source data stays unchanged during investigation.
              </span>
            </div>
          </div>
        )}

        {page === "results" && (
          <ResultsOverview
            datasetId={resultsScope.datasetId}
            caseIds={resultsScope.caseIds}
            datasets={datasets}
            busy={starting}
            submitting={batchSubmitting}
            queueUpdates={queueUpdates}
            actionLabel={caseAction}
            onBack={() => {
              setCasesRevision((value) => value + 1);
              navigate("inbox");
            }}
            onOpen={(item) => {
              void startInvestigation(item);
            }}
          />
        )}

        {page === "workspace" && (
          <div className="page workspace-page">
            <div className="investigation-heading">
              <div>
                <button className="back-link" onClick={() => navigate("inbox")}>
                  <ArrowLeft size={13} /> Case inbox
                </button>
                <h1>
                  {investigation
                    ? `Investigate ${investigation.paymentId}`
                    : "Investigation workspace"}
                </h1>
                <p>
                  {investigation
                    ? `${workspaceCase?.vendor ?? "Payment investigation"} · ${investigation.id}`
                    : "Select a payment exception to follow its evidence."}
                </p>
              </div>
              <div className="heading-actions">
                {running && (
                  <button
                    className="button secondary"
                    onClick={() => void cancelInvestigation()}
                    disabled={cancelling}
                  >
                    <Square size={13} />
                    {cancelling ? "Cancelling…" : "Cancel run"}
                  </button>
                )}
                {investigation && TERMINAL.has(investigation.status) && (
                  <a className="text-button" href="#investigation-review">
                    Review & export <ArrowRight size={14} />
                  </a>
                )}
              </div>
            </div>
            {stale && (
              <div className="global-alert notice" role="status">
                <Clock3 size={16} />
                <span>{stale}</span>
              </div>
            )}
            {investigation?.status === "completed" && (
              <div className="global-alert notice" role="status">
                {updatedDataset ? (
                  <RefreshCw size={16} />
                ) : (
                  <CheckCircle2 size={16} />
                )}
                <span>
                  {updatedDataset
                    ? "Update available — a newer data snapshot was imported. This result uses the previous snapshot."
                    : "Saved result — reopening this case uses the existing analysis. Memory updates do not rerun it."}
                </span>
                {updatedDataset && (
                  <button
                    className="button secondary"
                    disabled={starting || !!running}
                    onClick={() => void updateInvestigation()}
                  >
                    Update investigation
                  </button>
                )}
              </div>
            )}
            {!investigation ? (
              <div className="workspace-placeholder">
                <Empty
                  icon={<Workflow size={34} />}
                  title="A structured path to a clear answer"
                  text="Choose a payment in the case inbox. FinTrace will investigate the records, run checks, and put the evidence beside every finding."
                  action={
                    <button
                      className="button primary"
                      onClick={() => navigate("inbox")}
                    >
                      Choose a case <ArrowRight size={15} />
                    </button>
                  }
                />
                <div className="process-strip">
                  {[
                    "Query source records",
                    "Validate the explanation",
                    "Review proposed actions",
                  ].map((step, i) => (
                    <span key={step}>
                      <b>0{i + 1}</b>
                      {step}
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <>
                <div className="run-meta-strip">
                  <Status status={investigation.status} />
                  <span className="meta-divider" />
                  <span>
                    <Clock3 size={13} /> Updated{" "}
                    {date(investigation.updatedAt, true)}
                  </span>
                  <span className="run-model">
                    {investigation.mode === "fixture"
                      ? "Deterministic fixture"
                      : `${investigation.provider || "Provider not recorded"} / ${investigation.model || "Model not recorded"}`}
                  </span>
                  <span className="mono subtle">{investigation.datasetId}</span>
                </div>
                <div className="investigation-grid">
                  <aside className="case-rail">
                    <div className="panel-kicker">CASE BRIEF</div>
                    <div className="case-rail-vendor">
                      <span className="vendor-avatar">
                        {initials(workspaceCase?.vendor ?? "Payment")}
                      </span>
                      <h3>
                        {workspaceCase?.vendor ?? investigation.paymentId}
                      </h3>
                    </div>
                    <div className="case-amount">
                      {workspaceCase
                        ? money(workspaceCase.amount, workspaceCase.currency)
                        : "—"}
                    </div>
                    <span className="muted small">Payment amount</span>
                    <dl className="brief-list">
                      <dt>Payment ID</dt>
                      <dd className="mono">{investigation.paymentId}</dd>
                      <dt>Transaction date</dt>
                      <dd>{date(workspaceCase?.date)}</dd>
                      <dt>Observed symptom</dt>
                      <dd>
                        {workspaceCase?.symptom ??
                          "See source records for the reported exception."}
                      </dd>
                      <dt>Dataset snapshot</dt>
                      <dd>
                        {datasets.find(
                          (item) => item.id === investigation.datasetId,
                        )?.version ?? investigation.datasetId}
                      </dd>
                    </dl>
                    <div className="rail-divider" />
                    <div className="panel-kicker">INVESTIGATION SCOPE</div>
                    <div className="scope-item">
                      <Database size={15} />
                      <span>{evidence.length} evidence records</span>
                    </div>
                    <div className="scope-item">
                      <ShieldCheck size={15} />
                      <span>
                        {investigation.checks?.length ?? 0} validation checks
                      </span>
                    </div>
                    <div className="scope-item">
                      <Activity size={15} />
                      <span>
                        {investigation.events?.length ?? 0} recorded events
                      </span>
                    </div>
                    <div className="rail-footnote">
                      <ShieldCheck size={16} />
                      <p>
                        Findings are decision support. Proposed actions have not
                        been executed.
                      </p>
                    </div>
                  </aside>
                  <section className="findings-panel">
                    <div
                      className="workspace-tabs"
                      role="tablist"
                      aria-label="Investigation details"
                    >
                      {(["findings", "checks", "activity"] as const).map(
                        (key) => (
                          <button
                            role="tab"
                            aria-selected={workspaceTab === key}
                            className={workspaceTab === key ? "active" : ""}
                            key={key}
                            onClick={() => setWorkspaceTab(key)}
                          >
                            {key === "findings"
                              ? "Findings"
                              : key === "activity"
                                ? "Activity log"
                                : "Validation"}
                            <span>
                              {key === "findings"
                                ? (investigation.findings?.length ?? 0)
                                : key === "activity"
                                  ? (investigation.events?.length ?? 0)
                                  : (investigation.checks?.length ?? 0)}
                            </span>
                          </button>
                        ),
                      )}
                    </div>
                    {investigation.error && (
                      <div className="inline-error">
                        <XCircle size={16} />
                        {investigation.error}
                      </div>
                    )}
                    {workspaceTab === "findings" && (
                      <div className="findings-content">
                        {outcome && (
                          <div
                            className={`outcome-card ${outcome === "no_anomaly_supported" ? "clear" : outcome === "insufficient_evidence" ? "uncertain" : ""}`}
                          >
                            <span className="outcome-icon">
                              {outcome === "no_anomaly_supported" ? (
                                <CheckCheck size={21} />
                              ) : outcome === "insufficient_evidence" ? (
                                <HelpCircle size={21} />
                              ) : (
                                <Fingerprint size={21} />
                              )}
                            </span>
                            <div>
                              <div className="eyebrow">
                                INVESTIGATION OUTCOME
                              </div>
                              <h2>
                                {outcome === "anomaly_supported"
                                  ? "Anomaly supported by evidence"
                                  : outcome === "no_anomaly_supported"
                                    ? "No anomaly supported"
                                    : "More evidence is needed"}
                              </h2>
                              <p>
                                {outcome === "anomaly_supported"
                                  ? "Review the supporting records and checks before deciding on a next step."
                                  : outcome === "no_anomaly_supported"
                                    ? "The available evidence does not support the reported anomaly."
                                    : "The available records do not support a conclusive determination."}
                              </p>
                            </div>
                          </div>
                        )}
                        {!investigation.findings?.length && (
                          <Empty
                            compact
                            icon={
                              running ? (
                                <LoaderCircle className="spin" size={25} />
                              ) : (
                                <Search size={25} />
                              )
                            }
                            title={
                              running
                                ? "Investigation is in progress"
                                : "No findings recorded"
                            }
                            text={
                              running
                                ? "Results will appear as they are received from the server. You can inspect the recorded activity in the meantime."
                                : "Inspect the activity log for the run outcome or start another case."
                            }
                          />
                        )}
                        {!!investigation.findings?.length && (
                          <div className="content-section-label">
                            <span>Evidence-backed findings</span>
                            <small>SELECT A FINDING TO TRACE ITS SOURCES</small>
                          </div>
                        )}
                        {investigation.findings?.map((finding, i) => (
                          <article
                            key={finding.id}
                            className={`finding-card ${activeFinding === finding.id ? "active" : ""}`}
                          >
                            <button
                              className="finding-main"
                              onClick={() => {
                                setActiveFinding(finding.id);
                                setActiveEvidence(
                                  finding.evidenceIds?.[0] ?? null,
                                );
                              }}
                              aria-pressed={activeFinding === finding.id}
                            >
                              <span className="finding-index">
                                {String(i + 1).padStart(2, "0")}
                              </span>
                              <div>
                                <span className="category-label">
                                  {label(finding.category)}
                                </span>
                                <h3>{finding.title}</h3>
                                <p>{finding.summary}</p>
                              </div>
                              <ArrowUpRight size={15} />
                            </button>
                            {!!finding.contradictions?.length && (
                              <div className="finding-caveat">
                                <strong>
                                  Alternative explanation considered
                                </strong>
                                {finding.contradictions.map((item, index) => (
                                  <p key={index}>{item}</p>
                                ))}
                              </div>
                            )}
                            {!!finding.uncertainty?.length && (
                              <div className="finding-caveat neutral">
                                <strong>Uncertainty & limitations</strong>
                                {finding.uncertainty.map((item, index) => (
                                  <p key={index}>{item}</p>
                                ))}
                              </div>
                            )}
                            <div className="finding-sources">
                              <span>
                                <Layers3 size={12} /> Supporting records
                              </span>
                              {finding.evidenceIds?.length ? (
                                finding.evidenceIds.map((id) => (
                                  <button
                                    className={
                                      activeEvidence === id ? "selected" : ""
                                    }
                                    key={id}
                                    onClick={() => {
                                      setActiveFinding(finding.id);
                                      setActiveEvidence(id);
                                    }}
                                  >
                                    {id}
                                    <ArrowUpRight size={10} />
                                  </button>
                                ))
                              ) : (
                                <small>No source IDs recorded</small>
                              )}
                            </div>
                          </article>
                        ))}
                        <SourceTimeline investigation={investigation} />
                      </div>
                    )}
                    {workspaceTab === "activity" && (
                      <div className="activity-content">
                        <div className="content-section-label">
                          <span>Recorded execution</span>
                          <small>
                            {investigation.events?.length ?? 0} EVENTS
                          </small>
                        </div>
                        <p className="section-description">
                          Server-reported events only. No simulated progress or
                          generated activity.
                        </p>
                        <RunDiagnostics investigation={investigation} />
                        {investigation.events?.length ? (
                          <ol className="event-timeline">
                            {investigation.events.map((event) => (
                              <li key={event.id}>
                                <span className="event-dot">
                                  <Circle size={8} />
                                </span>
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
                        ) : (
                          <Empty
                            compact
                            icon={<Activity size={25} />}
                            title="No recorded events yet"
                            text="Events appear when the server records a step."
                          />
                        )}
                      </div>
                    )}
                    {workspaceTab === "checks" && (
                      <div className="checks-content">
                        <div className="content-section-label">
                          <span>Validation checks</span>
                          <small>
                            {investigation.checks?.filter(
                              (check) => check.status === "passed",
                            ).length ?? 0}{" "}
                            PASSED
                          </small>
                        </div>
                        <p className="section-description">
                          Checks validate the available evidence. An unknown
                          result is not a pass.
                        </p>
                        {investigation.checks?.length ? (
                          investigation.checks.map((check) => (
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
                                  {check.evidenceIds?.map((id) => (
                                    <button
                                      key={id}
                                      onClick={() => setActiveEvidence(id)}
                                    >
                                      {id}
                                      <ArrowUpRight size={11} />
                                    </button>
                                  ))}
                                </div>
                              </div>
                            </article>
                          ))
                        ) : (
                          <Empty
                            compact
                            icon={<ShieldCheck size={25} />}
                            title="No checks recorded yet"
                            text="Validation results will appear when available."
                          />
                        )}
                      </div>
                    )}
                  </section>
                  <EvidencePanel
                    evidence={evidence}
                    selected={chosenEvidence}
                    activeId={activeEvidence}
                    onSelect={setActiveEvidence}
                    queries={investigation.queries ?? []}
                  />
                </div>
                <section
                  className="investigation-followup"
                  aria-label="Next steps and human review"
                >
                  <div className="followup-actions">
                    {!!investigation.actions?.length && (
                      <>
                        <div className="content-section-label">
                          <span>Proposed next steps</span>
                          <small>NOT EXECUTED</small>
                        </div>
                        {investigation.actions.map((action) => (
                          <article className="action-card" key={action.id}>
                            <span className="action-icon">
                              <ArrowRight size={17} />
                            </span>
                            <div>
                              <h3>{action.title}</h3>
                              <p>{action.description}</p>
                              {!!action.prerequisites?.length && (
                                <div className="prerequisites">
                                  <strong>Before proceeding</strong>
                                  <ul>
                                    {action.prerequisites.map((item, index) => (
                                      <li key={index}>{item}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              <span
                                className={`verification-note ${action.verified ? "verified" : ""}`}
                              >
                                {action.verified ? (
                                  <ShieldCheck size={13} />
                                ) : (
                                  <Clock3 size={13} />
                                )}{" "}
                                {action.verified
                                  ? "Proposal checks verified · not executed"
                                  : "Proposal requires verification"}
                              </span>
                            </div>
                          </article>
                        ))}
                      </>
                    )}

                    {!investigation.actions.length && (
                      <p>
                        {running
                          ? "Proposed next steps will appear as the investigation runs."
                          : "No proposed actions recorded."}
                      </p>
                    )}
                    <div className="evidence-gaps">
                      <h3>Evidence gaps & uncertainty</h3>
                      {evidenceGaps.length ? (
                        <ul>
                          {evidenceGaps.map((gap) => (
                            <li key={gap}>{gap}</li>
                          ))}
                        </ul>
                      ) : (
                        <p>
                          {running
                            ? "The investigation is still checking the available evidence."
                            : "No additional evidence gaps recorded."}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="followup-review" id="investigation-review">
                    <h2>Human review</h2>
                    {investigation.review && (
                      <div
                        className={`review-receipt ${investigation.review.decision === "needs_changes" ? "needs-changes" : ""}`}
                      >
                        <FileCheck2 size={19} />
                        <div>
                          <strong>
                            Human review ·{" "}
                            {label(investigation.review.decision)}
                          </strong>
                          <small>
                            Reviewed {date(investigation.review.at, true)}
                          </small>
                          <p>
                            {investigation.review.notes ||
                              "No additional review notes."}
                          </p>
                        </div>
                      </div>
                    )}

                    {!investigation.review && (
                      <p className="review-pending">Awaiting human review</p>
                    )}
                    <p>
                      Proposed actions have not been executed. Review the
                      evidence before taking external action.
                    </p>
                    {TERMINAL.has(investigation.status) && (
                      <div className="followup-controls">
                        <button
                          className="button primary"
                          onClick={() => setModal("review")}
                          disabled={investigation.status !== "completed"}
                        >
                          <FileCheck2 size={16} /> Review findings
                        </button>
                        <ExportMenu disabled={exporting} onExport={exportRun} />
                      </div>
                    )}
                  </div>
                </section>
                <div className="workspace-bottom">
                  <span>
                    <Fingerprint size={14} />{" "}
                    {investigation.mode === "fixture"
                      ? "Fixture output — no live integration claim"
                      : investigation.mode === "local-model"
                        ? "Real model + local data — no Zetaris or PostgreSQL"
                        : "Live run — verify provider and query provenance"}
                  </span>
                  <span>
                    Snapshot:{" "}
                    {runDataset
                      ? `${runDataset.name} · ${runDataset.version}`
                      : investigation.datasetId}
                    <br />
                    Cutoff: {date(runDataset?.asOf, true)} · Investigation
                    updated: {date(investigation.updatedAt, true)}
                  </span>
                </div>
              </>
            )}
          </div>
        )}

        {page === "datasets" && (
          <div className="page datasets-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">THE FOUNDATION OF EVERY FINDING</div>
                <h1>Your data. A clear provenance.</h1>
                <p>
                  Manage reproducible snapshots and bring your own payment
                  records.
                </p>
              </div>
              <button
                className="button primary"
                onClick={() => setModal("import")}
              >
                <Upload size={16} /> Import dataset
              </button>
            </div>
            <div
              className="dataset-progress-summary"
              aria-label="Dataset progress summary"
              aria-live="polite"
            >
              {(
                [
                  [
                    "new",
                    "Not started",
                    libraryCases?.filter(
                      (item) =>
                        !isReviewedCase(item) &&
                        item.status !== "running" &&
                        item.status !== "queued",
                    ).length,
                    "cases pending",
                  ],
                  [
                    "progress",
                    "In progress",
                    libraryCases?.filter(
                      (item) =>
                        item.status === "running" || item.status === "queued",
                    ).length,
                    "cases running / queued",
                  ],
                  [
                    "completed",
                    "Completed",
                    libraryCases?.filter(isReviewedCase).length,
                    "cases completed",
                  ],
                ] as const
              ).map(([status, title, count, detail]) => (
                <div className={`dataset-progress-stat ${status}`} key={status}>
                  <span>{title}</span>
                  <strong>
                    {libraryCases === null
                      ? "—"
                      : progressTotals.filter((item) => item.status === status)
                          .length}{" "}
                    <small>datasets</small>
                  </strong>
                  <span>
                    {libraryCases === null
                      ? libraryError
                        ? "Progress unavailable"
                        : "Loading progress…"
                      : `${count} ${detail}`}
                  </span>
                </div>
              ))}
            </div>
            {libraryError && (
              <p role="alert">Dataset progress unavailable: {libraryError}</p>
            )}
            <div className="dataset-library-toolbar">
              <label className="search-field dataset-library-search">
                <Search size={20} />
                <span className="sr-only">Search datasets</span>
                <input
                  aria-label="Search datasets"
                  placeholder="Search dataset name, ID or version…"
                  value={datasetSearch}
                  onChange={(event) => setDatasetSearch(event.target.value)}
                />
                {datasetSearch && (
                  <button
                    aria-label="Clear dataset search"
                    onClick={() => setDatasetSearch("")}
                  >
                    <X size={18} />
                  </button>
                )}
              </label>
              <span className="dataset-match-count" role="status">
                {loading
                  ? "Loading datasets…"
                  : `${filteredDatasets.length} of ${datasets.length} datasets`}
              </span>
            </div>
            {datasetRemoval.controls}
            <div className="dataset-explainer">
              <span>
                <Database size={25} />
              </span>
              <div>
                <h3>Versioned inputs. Traceable outputs.</h3>
                <p>
                  Every investigation is tied to a dataset. Import a manifest
                  and CSV files, then follow each finding back to its exact
                  source record.
                </p>
              </div>
              <button
                className="button secondary"
                onClick={() => void downloadTemplate()}
              >
                <ArrowDownToLine size={15} /> Get template
              </button>
            </div>
            {loading ? (
              <Loading text="Loading datasets…" />
            ) : !datasets.length ? (
              <Empty
                icon={<Database size={30} />}
                title="No datasets available"
                text="Import a dataset bundle to make cases available for investigation."
              />
            ) : !filteredDatasets.length ? (
              <Empty
                icon={<Search size={30} />}
                title="No matching datasets"
                text="Search by dataset name, full Dataset ID, or version ID."
                action={
                  <button
                    className="button secondary"
                    onClick={() => setDatasetSearch("")}
                  >
                    Show all datasets
                  </button>
                }
              />
            ) : (
              <div className="dataset-cards">
                {filteredDatasets.map((item) => (
                  <article
                    className={`dataset-card ${item.id === datasetId ? "active" : ""}`}
                    aria-label={`Dataset ${item.name}`}
                    key={item.id}
                    onClick={(event) => {
                      if (
                        (event.target as HTMLElement).closest(
                          "button, a, input, label",
                        )
                      )
                        return;
                      setDatasetId(item.id);
                      navigate("inbox");
                    }}
                  >
                    <div className="dataset-card-top">
                      {datasetRemoval.checkbox({
                        id: item.id,
                        label: item.name,
                      })}
                      <span className="dataset-icon">
                        <Database size={22} />
                      </span>
                      <div className="dataset-card-badges">
                        <span
                          className={`dataset-progress-badge ${libraryCases === null ? "unknown" : datasetProgress.get(item.id)?.status}`}
                        >
                          {libraryCases === null
                            ? libraryError
                              ? "Status unavailable"
                              : "Loading…"
                            : datasetProgress.get(item.id)?.status ===
                                "completed"
                              ? "Completed"
                              : datasetProgress.get(item.id)?.status ===
                                  "progress"
                                ? "In progress"
                                : datasetProgress.get(item.id)?.status ===
                                    "empty"
                                  ? "No cases"
                                  : "Not started"}
                        </span>
                        {libraryCases !== null && (
                          <span className="dataset-progress-detail">
                            {datasetProgress.get(item.id)?.completed} /{" "}
                            {datasetProgress.get(item.id)?.total} cases
                            completed
                          </span>
                        )}
                        {item.id === datasetId && (
                          <span className="dataset-selected">
                            <Check size={16} /> Selected
                          </span>
                        )}
                      </div>
                    </div>
                    <h2>{item.name}</h2>
                    <div className="dataset-identifiers">
                      <CopyVersion value={item.id} kind="dataset" compact />
                      <CopyVersion value={item.version} compact />
                    </div>
                    <div className="dataset-properties">
                      <span>
                        Payment cases<strong>{item.caseCount ?? "—"}</strong>
                      </span>
                      <span>
                        Snapshot date<strong>{date(item.asOf)}</strong>
                      </span>
                      <span>
                        Coverage<strong>{coverageLabel(item.coverage)}</strong>
                      </span>
                    </div>
                    <button
                      className={`button dataset-open-button ${item.id === datasetId ? "soft" : "secondary"}`}
                      onClick={() => {
                        setDatasetId(item.id);
                        navigate("inbox");
                      }}
                    >
                      {item.id === datasetId ? (
                        <Check size={15} />
                      ) : (
                        <FolderOpen size={15} />
                      )}{" "}
                      {item.id === datasetId
                        ? "Open active dataset"
                        : "Select dataset & open cases"}
                      <ArrowRight size={14} />
                    </button>
                    {datasetRemoval.removeButton({
                      id: item.id,
                      label: item.name,
                    })}
                  </article>
                ))}
              </div>
            )}
            <div className="import-format-note">
              <FileSpreadsheet size={19} />
              <div>
                <strong>Bring your own data</strong>
                <p>
                  Upload the JSON template bundle, or select a manifest JSON
                  file together with its CSV files. Validation errors are
                  returned before the dataset is accepted.
                </p>
              </div>
            </div>
            <IntegrationStatus health={health} />
          </div>
        )}

        {page === "guide" && (
          <div className="page guide-page">
            <div className="eyebrow">THE FINTRACE APPROACH</div>
            <h1>Confidence comes from evidence.</h1>
            <p className="guide-intro">
              FinTrace turns a payment question into an investigation you can
              inspect, challenge, and review.
            </p>
            <div className="guide-grid">
              {[
                {
                  icon: <Database size={22} />,
                  title: "Start with the records",
                  text: "Investigations are grounded in a versioned dataset. Each evidence card identifies its source table, record, query and snapshot.",
                },
                {
                  icon: <Workflow size={22} />,
                  title: "Investigate, then validate",
                  text: "Findings, conflicting evidence, uncertainty and validation checks are shown separately. An unsupported explanation should stay unresolved.",
                },
                {
                  icon: <ShieldCheck size={22} />,
                  title: "Keep the decision human",
                  text: "Actions are proposals. A completed investigation does not mean a payment, bank record or ledger has been changed. Review findings before taking action.",
                },
                {
                  icon: <FileCheck2 size={22} />,
                  title: "Take the evidence with you",
                  text: "Export a run as JSON, CSV or HTML. Human review records whether findings were accepted or need changes; memory approval is explicit.",
                },
              ].map((item) => (
                <article key={item.title}>
                  <span>{item.icon}</span>
                  <h2>{item.title}</h2>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
            <div className="honest-mode-note">
              <Fingerprint size={23} />
              <div>
                <h3>Every execution mode is clearly labelled.</h3>
                <p>
                  Offline fixture mode uses deterministic rules. It does not
                  call a live model or Zetaris. Local-model mode calls your
                  configured model using local snapshots, without PostgreSQL or
                  Zetaris. Live mode requires both external data services. Each
                  live integration must be configured and verified separately;
                  the mode banner and recorded provider make that distinction
                  visible.
                </p>
              </div>
            </div>
            <button
              className="button primary"
              onClick={() => navigate("inbox")}
            >
              Explore the case inbox <ArrowRight size={15} />
            </button>
          </div>
        )}
      </main>
      {modal === "import" && (
        <ImportModal
          onClose={() => setModal(null)}
          onTemplate={downloadTemplate}
          onImported={async (id) => {
            await loadBase();
            setDatasetSearch("");
            if (id) setDatasetId(id);
            setNotice(
              "Dataset imported. Its cases are now available in the inbox.",
            );
            setPage("datasets");
            setModal(null);
          }}
        />
      )}
      {modal === "review" && investigation && (
        <ReviewModal
          investigation={investigation}
          onClose={() => setModal(null)}
          onReviewed={(run) => {
            setInvestigation(run);
            setModal(null);
            setNotice(
              "Human review saved. Proposed actions remain unexecuted.",
            );
          }}
        />
      )}
    </div>
  );
}

function RunDiagnostics({ investigation }: { investigation: Investigation }) {
  const requests = investigation.modelRequests;
  return (
    <section className="run-diagnostics" aria-label="Run diagnostics">
      <h3>Model API requests</h3>
      <p className="section-description">
        Run ID: <span className="mono">{investigation.id}</span> ·{" "}
        {investigation.modelTurns} planning calls. HTTP attempts include
        retries.
      </p>
      {!requests?.length ? (
        <p>
          {investigation.mode === "fixture"
            ? "No model API calls in fixture mode."
            : requests
              ? "No model requests recorded yet."
              : "Request details were not recorded for this older run."}
        </p>
      ) : (
        requests.map((request) => (
          <article className="diagnostic-record" key={request.id}>
            <strong>
              {label(request.status)} · attempt {request.attempt} ·{" "}
              {request.durationMs} ms
            </strong>
            <p>
              {request.provider} / {request.returnedModel || request.model}
              {request.httpStatus ? ` · HTTP ${request.httpStatus}` : ""}
              {request.errorCode ? ` · ${request.errorCode}` : ""}
            </p>
            <p>Request ID: {request.requestId || "Not returned"}</p>
            <p>
              Tokens: input {request.inputTokens ?? "not reported"} · output{" "}
              {request.outputTokens ?? "not reported"} · total{" "}
              {request.totalTokens ?? "not reported"}
            </p>
          </article>
        ))
      )}
      <h3>Evidence queries</h3>
      {investigation.queries.map((query) => (
        <article className="diagnostic-record" key={query.id}>
          <strong>
            {query.tool} · {query.status} · {query.rowCount} records
          </strong>
          <p>
            {query.tables.join(", ") || "No table result"} · {query.durationMs}{" "}
            ms
          </p>
          <p>Query ID: {query.id}</p>
        </article>
      ))}
      <h3>Memories provided to planner</h3>
      <p>
        Recalled snapshots were provided to the planner; model adoption is not
        asserted. Later status changes do not alter these snapshots.
      </p>
      {!investigation.memories.length ? (
        <p>No approved memories recalled.</p>
      ) : (
        investigation.memories.map((value, index) => {
          const memory =
            value && typeof value === "object"
              ? (value as Record<string, unknown>)
              : {};
          return (
            <article
              className="diagnostic-record"
              key={String(memory.id ?? index)}
            >
              <p>{String(memory.content ?? "Content not recorded")}</p>
              <small>
                Source run:{" "}
                <a
                  href={`?investigation=${encodeURIComponent(String(memory.source || ""))}`}
                >
                  {String(memory.source ?? "Not recorded")}
                </a>
                <p>
                  Scope: {String(memory.scope || "workspace")} · Suggested
                  tools:{" "}
                  {Array.isArray(memory.suggestedTools)
                    ? memory.suggestedTools.join(", ")
                    : "Not recorded"}
                </p>
                <p>
                  Match explanation:{" "}
                  {JSON.stringify(
                    memory.explanation ||
                      "Legacy snapshot; explanation not recorded",
                  )}
                </p>
              </small>
            </article>
          );
        })
      )}
    </section>
  );
}

function SourceTimeline({ investigation }: { investigation: Investigation }) {
  const payment = investigation.evidence.find(
    (e) =>
      e.table === "payments" && e.record.payment_id === investigation.paymentId,
  )?.record;
  if (!payment) return null;
  const entries = investigation.evidence
    .flatMap((e) => {
      const r = e.record;
      const related =
        (e.table === "payments" && r.payment_id === investigation.paymentId) ||
        (e.table === "audit_log" && r.entity_id === investigation.paymentId) ||
        (e.table === "vendor_change_log" &&
          r.vendor_id === payment.vendor_id) ||
        (e.table === "bank_transactions" &&
          r.payment_reference === payment.reference_number);
      const at =
        e.table === "payments"
          ? r.created_at
          : e.table === "vendor_change_log"
            ? r.changed_at
            : e.table === "audit_log"
              ? r.timestamp
              : r.posted_date;
      return related && at
        ? [
            {
              id: e.id,
              at,
              title:
                e.table === "payments"
                  ? "Payment created"
                  : e.table === "audit_log"
                    ? label(r.event_type)
                    : e.table === "vendor_change_log"
                      ? "Vendor instructions changed"
                      : "Bank observation",
              detail:
                e.table === "bank_transactions"
                  ? r.status
                  : e.table === "audit_log"
                    ? r.source_system
                    : e.table,
            },
          ]
        : [];
    })
    .sort((a, b) => parseTime(a.at) - parseTime(b.at));
  if (!entries.length) return null;
  return (
    <>
      <div className="content-section-label">
        <span>Source event timeline</span>
        <small>RECORDED SOURCE DATES · UTC</small>
      </div>
      <ol className="event-timeline source-timeline">
        {entries.map((e) => (
          <li key={e.id}>
            <span className="event-dot">
              <Circle size={8} />
            </span>
            <div className="event-header">
              <strong>{e.title}</strong>
              <time>{date(e.at, true)}</time>
            </div>
            <p>{label(e.detail)}</p>
            <small className="mono">{e.id}</small>
          </li>
        ))}
      </ol>
    </>
  );
}

function NavItem({
  icon,
  text,
  active,
  onClick,
  count,
  dot,
}: {
  icon: React.ReactNode;
  text: string;
  active: boolean;
  onClick: () => void;
  count?: number;
  dot?: boolean;
}) {
  return (
    <button className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>
      {icon}
      <span>{text}</span>
      {count !== undefined && <small>{count}</small>}
      {dot && <span className="nav-running" />}
    </button>
  );
}
function Stat({
  icon,
  label: name,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-top">
        <span>{name}</span>
        <span className="stat-icon">{icon}</span>
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </div>
  );
}
function CopyVersion({
  value,
  kind = "version",
  compact = false,
}: {
  value: string;
  kind?: "dataset" | "version";
  compact?: boolean;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 2500);
    return () => window.clearTimeout(timer);
  }, [state]);
  return (
    <button
      className={compact ? "dataset-identifier-copy" : "version-copy-card"}
      aria-label={
        kind === "dataset" ? "Copy dataset ID" : "Copy dataset version ID"
      }
      title={value}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setState("copied");
        } catch {
          setState("failed");
        }
      }}
    >
      <span className="version-copy-label">
        <Database size={16} />{" "}
        {kind === "dataset" ? "Dataset ID" : "Dataset version ID"}
      </span>
      <code className={kind === "dataset" ? "mono dataset-id" : undefined}>
        {value}
      </code>
      <span className="version-copy-hint" role="status">
        {state === "copied"
          ? "Copied!"
          : state === "failed"
            ? "Copy failed — click to retry"
            : "Click to copy"}
      </span>
    </button>
  );
}
function Loading({ text }: { text: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle size={22} className="spin" />
      {text}
    </div>
  );
}
function Empty({
  icon,
  title,
  text,
  action,
  compact,
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty-state ${compact ? "compact" : ""}`}>
      <span className="empty-icon">{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Status({ status }: { status: Investigation["status"] }) {
  return (
    <span className={`run-status ${status}`}>
      {status === "running" || status === "queued" ? (
        <LoaderCircle className="spin" size={13} />
      ) : status === "completed" ? (
        <CheckCircle2 size={13} />
      ) : status === "failed" ? (
        <XCircle size={13} />
      ) : (
        <Square size={12} />
      )}{" "}
      {label(status)}
    </span>
  );
}
function FlaskIcon() {
  return (
    <span className="fixture-glyph">
      <Square size={12} />
      <span />
    </span>
  );
}
function initials(value: string) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}
function hash(value: string) {
  return [...value].reduce((total, char) => total + char.charCodeAt(0), 0);
}
function coverageLabel(value: unknown): string {
  if (Array.isArray(value))
    return `${value.length} ${value.length === 1 ? "category" : "categories"}`;
  if (typeof value === "number") return `${value} categories`;
  if (typeof value === "string") return value;
  if (value && typeof value === "object")
    return `${Object.keys(value).length} categories`;
  return "Not specified";
}
function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ExportMenu({
  disabled,
  onExport,
}: {
  disabled: boolean;
  onExport: (format: "json" | "csv" | "html") => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="export-menu">
      <button
        className="button secondary"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <ArrowDownToLine size={15} />
        {disabled ? "Exporting…" : "Export"}
        <ChevronDown size={12} />
      </button>
      {open && (
        <>
          <button
            className="menu-backdrop"
            aria-label="Close export menu"
            onClick={() => setOpen(false)}
          />
          <div className="dropdown-panel">
            {(["json", "csv", "html"] as const).map((format) => (
              <button
                key={format}
                onClick={() => {
                  setOpen(false);
                  void onExport(format);
                }}
              >
                {format === "json" ? (
                  <FileJson size={15} />
                ) : format === "csv" ? (
                  <FileSpreadsheet size={15} />
                ) : (
                  <FileText size={15} />
                )}{" "}
                {format.toUpperCase()} report
                <ArrowDownToLine size={13} />
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function EvidencePanel({
  evidence,
  selected,
  activeId,
  onSelect,
  queries,
}: {
  evidence: Evidence[];
  selected: Evidence | undefined;
  activeId: string | null;
  onSelect: (id: string) => void;
  queries: unknown[];
}) {
  const [tab, setTab] = useState<"record" | "provenance">("record");
  const query = queries.find(
    (item) =>
      item &&
      typeof item === "object" &&
      (("id" in item && item.id === selected?.queryId) ||
        ("queryId" in item && item.queryId === selected?.queryId)),
  ) as Record<string, unknown> | undefined;
  return (
    <aside className="evidence-panel">
      <div className="evidence-panel-heading">
        <span>
          <Layers3 size={17} />
          <h2>Source evidence</h2>
        </span>
        <small>{evidence.length}</small>
      </div>
      <p className="evidence-help">
        Select a finding to inspect the records behind it.
      </p>
      {!selected ? (
        <Empty
          compact
          icon={<BookOpen size={26} />}
          title="Evidence will appear here"
          text="Source records are displayed when an investigation retrieves them."
        />
      ) : (
        <>
          <label className="evidence-picker">
            <span className="sr-only">Evidence record</span>
            <select
              value={selected.id}
              onChange={(event) => onSelect(event.target.value)}
            >
              {evidence.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id} · {item.table}
                </option>
              ))}
            </select>
            <ChevronDown size={13} />
          </label>
          <div className="source-record-top">
            <span className="source-table">
              <Database size={13} />
              {selected.table}
            </span>
            <span className="record-id">{selected.recordId}</span>
          </div>
          <div className="evidence-subtabs">
            <button
              className={tab === "record" ? "active" : ""}
              onClick={() => setTab("record")}
            >
              Record detail
            </button>
            <button
              className={tab === "provenance" ? "active" : ""}
              onClick={() => setTab("provenance")}
            >
              Provenance
            </button>
          </div>
          {tab === "record" ? (
            <div className="record-fields">
              {Object.entries(selected.record ?? {}).map(([key, value]) => (
                <div key={key}>
                  <dt>{label(key)}</dt>
                  <dd
                    className={/id|number|reference/i.test(key) ? "mono" : ""}
                  >
                    {textValue(value)}
                  </dd>
                </div>
              ))}
              {!Object.keys(selected.record ?? {}).length && (
                <p className="muted">No fields were recorded.</p>
              )}
            </div>
          ) : (
            <div className="provenance-details">
              <dl>
                <dt>Evidence ID</dt>
                <dd>{selected.id}</dd>
                <dt>Source table</dt>
                <dd>{selected.table}</dd>
                <dt>Source record</dt>
                <dd>{selected.recordId}</dd>
                <dt>Query ID</dt>
                <dd>{selected.queryId || "Not recorded"}</dd>
                <dt>Dataset version</dt>
                <dd>{selected.datasetVersion || "Not recorded"}</dd>
              </dl>
              <strong className="small">Recorded query</strong>
              <pre>
                {query
                  ? textValue(
                      query.sql ?? query.statement ?? query.query ?? query,
                    )
                  : "No query text was recorded for this evidence."}
              </pre>
            </div>
          )}
          <div className="provenance-stamp">
            <Fingerprint size={16} />
            <div>
              <strong>Source provenance</strong>
              <small>
                {selected.datasetVersion || "Version not recorded"} ·{" "}
                {selected.queryId || "Query not recorded"}
              </small>
            </div>
          </div>
          <div className="evidence-record-list">
            <div className="panel-kicker">ALL EVIDENCE</div>
            {evidence.map((item) => (
              <button
                key={item.id}
                className={
                  (activeId ?? selected.id) === item.id ? "active" : ""
                }
                onClick={() => {
                  onSelect(item.id);
                  setTab("record");
                }}
              >
                <span>
                  <FileText size={14} />
                  <span>
                    <strong>{item.id}</strong>
                    <small>
                      {item.table} · {item.recordId}
                    </small>
                  </span>
                </span>
                <ChevronRight size={13} />
              </button>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}

function IntegrationStatus({ health }: { health: Health | null }) {
  return (
    <section className="integration-section">
      <div className="section-header">
        <div>
          <h2>Integration status</h2>
          <p>
            Reported by the API. Fixture output does not establish live
            connectivity.
          </p>
        </div>
        <span className="version-tag">
          {health ? label(health.mode) : "Unavailable"}
        </span>
      </div>
      <div className="integration-grid">
        {Object.entries(health?.integrations ?? {}).length ? (
          Object.entries(health?.integrations ?? {}).map(([key, value]) => {
            const object =
              value && typeof value === "object"
                ? (value as Record<string, unknown>)
                : null;
            const state = object
              ? textValue(
                  object.status ??
                    (object.connected === true
                      ? "connected"
                      : object.connected === false
                        ? "not connected"
                        : "not verified"),
                )
              : textValue(value);
            return (
              <div className="integration-item" key={key}>
                <span className="integration-logo">
                  <Database size={18} />
                </span>
                <div>
                  <strong>{label(key)}</strong>
                  <small>
                    {object?.detail ? textValue(object.detail) : state}
                  </small>
                </div>
                <span className="integration-state">{state}</span>
              </div>
            );
          })
        ) : (
          <p className="muted">No integration details were returned.</p>
        )}
      </div>
    </section>
  );
}

function ImportModal({
  onClose,
  onImported,
  onTemplate,
}: {
  onClose: () => void;
  onImported: (id?: string) => Promise<void>;
  onTemplate: () => Promise<void>;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  async function submit() {
    setBusy(true);
    setError("");
    try {
      const jsonFiles = files.filter((file) =>
        file.name.toLowerCase().endsWith(".json"),
      );
      if (jsonFiles.length !== 1)
        throw new Error(
          "Select exactly one manifest JSON or dataset bundle, together with any CSV files.",
        );
      const json = JSON.parse(await jsonFiles[0].text()) as Record<
        string,
        unknown
      >;
      const csvFiles: Record<string, string> = {};
      for (const file of files.filter((item) =>
        item.name.toLowerCase().endsWith(".csv"),
      ))
        csvFiles[file.name] = await file.text();
      const payload =
        "manifest" in json && "files" in json
          ? json
          : { manifest: json, files: csvFiles };
      const result = await api<{ dataset?: Dataset; id?: string }>(
        "/datasets",
        { method: "POST", body: JSON.stringify(payload) },
      );
      await onImported(result.dataset?.id ?? result.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <ModalShell
      title="Import a dataset"
      subtitle="Bring a reproducible snapshot into your workspace."
      onClose={onClose}
      busy={busy}
    >
      <div className="modal-body">
        <div className="import-instruction">
          <FileSpreadsheet size={20} />
          <div>
            <strong>Manifest + CSV files, or one JSON bundle</strong>
            <p>
              Start with the template for the expected schema. Your original
              files are not modified.
            </p>
          </div>
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept=".csv,.json"
          className="sr-only"
          aria-label="Dataset files"
          disabled={busy}
          onChange={(event) => {
            setFiles(Array.from(event.target.files ?? []));
            setError("");
          }}
        />
        <button
          className="upload-zone"
          disabled={busy}
          onClick={() => fileInput.current?.click()}
        >
          <span>
            <Upload size={25} />
          </span>
          <strong>Choose dataset files</strong>
          <small>JSON manifest and CSV tables · select multiple files</small>
          <span className="button secondary">Browse files</span>
        </button>
        {!!files.length && (
          <div className="chosen-files">
            {files.map((file) => (
              <div key={`${file.name}-${file.size}`}>
                <FileText size={15} />
                <span>
                  {file.name}
                  <small>{(file.size / 1024).toFixed(1)} KB</small>
                </span>
                <button
                  onClick={() =>
                    setFiles((previous) =>
                      previous.filter((item) => item !== file),
                    )
                  }
                  aria-label={`Remove ${file.name}`}
                  disabled={busy}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
        {error && (
          <div className="inline-error" role="alert">
            <XCircle size={16} />
            {error}
          </div>
        )}
        <button
          className="template-link"
          onClick={() => void onTemplate()}
          disabled={busy}
        >
          <ArrowDownToLine size={14} /> Download template bundle
        </button>
      </div>
      <div className="modal-footer">
        <button className="button secondary" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button
          className="button primary"
          onClick={() => void submit()}
          disabled={!files.length || busy}
        >
          {busy ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Upload size={15} />
          )}{" "}
          {busy ? "Validating & importing…" : "Validate & import"}
        </button>
      </div>
    </ModalShell>
  );
}

function MemoryPanel() {
  const [memories, setMemories] = useState<ApprovedMemory[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const visibleMemories = memories.filter(
    (item) => filter === "all" || item.status === filter,
  );
  const memoryRemoval = useRemoval({
    kind: "memory",
    items: memories.map((item) => ({
      id: item.id,
      label: `${item.id}: ${item.content}`,
    })),
    visibleItems: visibleMemories.map((item) => ({
      id: item.id,
      label: `${item.id}: ${item.content}`,
    })),
    endpoint: "/memories/removal",
    onChanged: async () => {
      await load();
    },
  });
  async function load() {
    try {
      setMemories(
        (await api<{ memories: ApprovedMemory[] }>("/memories")).memories,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load memories");
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function toggle(m: ApprovedMemory) {
    setBusy(true);
    setError("");
    try {
      await api(`/memories/${encodeURIComponent(m.id)}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: m.status === "active" ? "inactive" : "active",
        }),
      });
      await load();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not change memory status",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="memory-panel">
      <h1>Investigation memories</h1>
      <p>
        Human approved procedures in Meterless H-MEM. Memories prioritize
        allowed evidence tools; independent verification determines financial
        results.
      </p>
      <p>
        Approved text is immutable. Deactivate an incorrect entry, open its
        source investigation and approve an edited correction. Existing
        investigations are never rerun automatically.
      </p>
      <label>
        Memory status{" "}
        <select
          value={filter}
          disabled={busy || memoryRemoval.busy}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
      </label>
      {memoryRemoval.controls}
      {error && <p role="alert">{error}</p>}
      {!memories.length && <p>No approved memories yet.</p>}
      {memories
        .filter((m) => filter === "all" || m.status === filter)
        .map((m) => (
          <article className="diagnostic-record" key={m.id}>
            {memoryRemoval.checkbox({
              id: m.id,
              label: `${m.id}: ${m.content}`,
            })}
            <strong>
              {m.id} · {m.status}
            </strong>
            <p>{m.content}</p>
            <p>
              Scope: {m.scope}
              {m.vendorId ? ` · ${m.vendorId}` : ""}
            </p>
            <p>Conditions: {m.conditions || "Legacy workspace procedure"}</p>
            <p>
              Suggested tools: {m.suggestedTools.join(", ") || "None recorded"}
            </p>
            <p>
              Approved {date(m.approvedAt, true)} · Generated by:{" "}
              {m.generationSource} · Approved by: human reviewer
            </p>
            <a href={`?investigation=${encodeURIComponent(m.source)}`}>
              Open source investigation
            </a>{" "}
            <button
              className="button secondary"
              disabled={busy || memoryRemoval.busy}
              onClick={() => void toggle(m)}
            >
              {m.status === "active" ? "Deactivate" : "Restore"}
            </button>
            {memoryRemoval.removeButton({
              id: m.id,
              label: `${m.id}: ${m.content}`,
            })}
          </article>
        ))}
      <p>
        Single instance workspace; local hash embeddings and bilingual keywords.
        Production semantic retrieval and multiuser permissions are not
        implemented.
      </p>
    </section>
  );
}

function ReviewModal({
  investigation,
  onClose,
  onReviewed,
}: {
  investigation: Investigation;
  onClose: () => void;
  onReviewed: (run: Investigation) => void;
}) {
  const [decision, setDecision] = useState<"accepted" | "needs_changes">(
    "accepted",
  );
  const [notes, setNotes] = useState("");
  const [approveMemory, setApproveMemory] = useState(false);
  const [existingMemories, setExistingMemories] = useState<ApprovedMemory[]>(
    [],
  );
  const namespace = investigation.memoryNamespace || "workspace";
  useEffect(() => {
    let alive = true;
    api<{ memories: ApprovedMemory[] }>(
      `/memories?namespace=${encodeURIComponent(namespace)}`,
    )
      .then(({ memories }) => {
        if (alive)
          setExistingMemories(
            memories.filter(
              (item) =>
                item.source === investigation.id && item.status === "active",
            ),
          );
      })
      .catch(() => {
        /* The review API remains authoritative if the memory list is unavailable. */
      });
    return () => {
      alive = false;
    };
  }, [investigation.id, namespace]);
  async function deactivateMemory(id: string) {
    setBusy(true);
    setError("");
    try {
      await api(
        `/memories/${encodeURIComponent(id)}?namespace=${encodeURIComponent(namespace)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: "inactive" }),
        },
      );
      setExistingMemories((previous) =>
        previous.filter((item) => item.id !== id),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to deactivate the existing memory.",
      );
    } finally {
      setBusy(false);
    }
  }
  const [draft, setDraft] = useState<MemoryDraft | undefined>(
    investigation.memoryDraft,
  );
  const [memoryContent, setMemoryContent] = useState(
    investigation.memoryDraft?.content || "",
  );
  const [scope, setScope] = useState<"workspace" | "vendor">("workspace");
  const [draftRequests, setDraftRequests] = useState(
    investigation.memoryDraftRequests || [],
  );
  const [generating, setGenerating] = useState(false);
  const draftLock = useRef(false);
  async function suggest(retry = false) {
    if (draftLock.current) return;
    draftLock.current = true;
    setGenerating(true);
    setError("");
    try {
      const run = await api<Investigation>(
        `/investigations/${encodeURIComponent(investigation.id)}/memory-draft`,
        {
          method: "POST",
          body: JSON.stringify({ retry }),
        },
      );
      setDraft(run.memoryDraft);
      setDraftRequests(run.memoryDraftRequests || []);
      if (run.memoryDraft?.status === "ready")
        setMemoryContent(run.memoryDraft.content || "");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Generation failed; manual entry remains available.",
      );
    } finally {
      draftLock.current = false;
      setGenerating(false);
    }
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit() {
    setBusy(true);
    setError("");
    try {
      const run = await api<Investigation>(
        `/investigations/${encodeURIComponent(investigation.id)}/review`,
        {
          method: "POST",
          body: JSON.stringify({
            decision,
            notes,
            approveMemory,
            memoryScope: scope,
            ...(approveMemory && draft?.status === "ready"
              ? { memoryDraftId: draft.id }
              : {}),
            ...(approveMemory && memoryContent.trim()
              ? { memoryContent: memoryContent.trim() }
              : {}),
          }),
        },
      );
      onReviewed(run);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Review could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <ModalShell
      title="Review the investigation"
      subtitle={`${investigation.paymentId} · Your decision is recorded with the run.`}
      onClose={onClose}
      busy={busy || generating}
    >
      <div className="modal-body">
        <div className="review-options">
          <button
            className={decision === "accepted" ? "active" : ""}
            onClick={() => setDecision("accepted")}
            disabled={busy || generating}
            aria-pressed={decision === "accepted"}
          >
            <CheckCircle2 size={20} />
            <strong>Accept findings</strong>
            <span>The evidence supports this assessment.</span>
          </button>
          <button
            className={decision === "needs_changes" ? "active" : ""}
            onClick={() => {
              setDecision("needs_changes");
              setApproveMemory(false);
            }}
            disabled={busy || generating}
            aria-pressed={decision === "needs_changes"}
          >
            <RefreshCw size={20} />
            <strong>Request changes</strong>
            <span>More evidence or corrections are needed.</span>
          </button>
        </div>
        <label className="form-label">
          Review notes
          <textarea
            value={notes}
            disabled={busy || generating}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Record what you checked, any limitations, or the changes needed."
            rows={4}
          />
        </label>
        <div className="memory-draft">
          <button
            className="button secondary"
            disabled={
              busy || generating || investigation.status !== "completed"
            }
            onClick={() => void suggest(draft?.status === "failed")}
          >
            {generating
              ? "Generating suggestion…"
              : draft?.status === "failed"
                ? "Retry memory suggestion"
                : "Suggest memory"}
          </button>
          {draft && (
            <div aria-live="polite">
              <p>
                Draft: {draft.status} ·{" "}
                {draft.source === "fixture"
                  ? "Deterministic fixture example · no model called"
                  : `${draft.provider} / ${draft.model}`}
              </p>
              {draft.status === "none" && (
                <p>No suitable reusable lesson. {draft.reason}</p>
              )}
              {draft.error && <p role="alert">{draft.error}</p>}
              {draft.status === "ready" && (
                <>
                  <p>Conditions: {draft.conditions}</p>
                  <p>Suggested tools: {draft.suggestedTools?.join(", ")}</p>
                  <p>
                    Evidence:{" "}
                    {draft.evidenceIds?.map((id) => (
                      <a
                        key={id}
                        href={`?investigation=${encodeURIComponent(investigation.id)}&evidence=${encodeURIComponent(id)}`}
                      >
                        {id}{" "}
                      </a>
                    ))}
                  </p>
                </>
              )}
              <p>
                Draft requests: {draftRequests.length} (separate from
                investigation cost). Drafts are excluded from recall.
              </p>
            </div>
          )}
          <p>
            Manual entry remains available. Accept findings and explicitly
            approve before saving to H-MEM.
          </p>
        </div>
        <div className="memory-consent">
          {existingMemories.map((item) => (
            <div key={item.id}>
              <strong>Existing approved memory</strong>
              <p>{item.content}</p>
              <p>
                To approve different content, deactivate this memory first. Its
                history will be preserved. You can also leave memory approval
                unchecked to save only the review.
              </p>
              <button
                className="button secondary"
                disabled={busy || generating}
                onClick={() => void deactivateMemory(item.id)}
              >
                Deactivate existing memory
              </button>
            </div>
          ))}
          <label>
            <input
              type="checkbox"
              checked={approveMemory}
              disabled={busy || decision !== "accepted"}
              onChange={(event) => setApproveMemory(event.target.checked)}
            />
            <span>
              <strong>Approve a reusable memory</strong>
              <small>
                {decision === "accepted"
                  ? "Explicitly allow a confirmed lesson to inform future investigations."
                  : "Accept findings before approving a reusable memory."}
              </small>
            </span>
          </label>
          <label className="form-label">
            Memory scope
            <select
              aria-label="Memory scope"
              value={scope}
              disabled={busy || generating}
              onChange={(e) =>
                setScope(e.target.value as "workspace" | "vendor")
              }
            >
              <option value="workspace">Current workspace</option>
              <option value="vendor">Current vendor</option>
            </select>
          </label>
          {approveMemory && (
            <label className="form-label">
              Confirmed lesson
              <textarea
                aria-label="Confirmed lesson"
                value={memoryContent}
                disabled={busy || generating}
                onChange={(event) => setMemoryContent(event.target.value)}
                placeholder="Write only the confirmed lesson you want the system to remember."
                rows={3}
              />
            </label>
          )}
        </div>
        <p className="review-disclaimer">
          <ShieldCheck size={15} /> Saving a review does not execute actions or
          modify source transactions.
        </p>
        {error && (
          <div className="inline-error" role="alert">
            <XCircle size={16} />
            {error}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button
          className="button secondary"
          onClick={onClose}
          disabled={busy || generating}
        >
          Cancel
        </button>
        <button
          className="button primary"
          onClick={() => void submit()}
          disabled={
            busy || generating || (approveMemory && !memoryContent.trim())
          }
        >
          {busy ? (
            <LoaderCircle className="spin" size={15} />
          ) : (
            <FileCheck2 size={15} />
          )}{" "}
          {busy ? "Saving review…" : "Save human review"}
        </button>
      </div>
    </ModalShell>
  );
}

export default App;
