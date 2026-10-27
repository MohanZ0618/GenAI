import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowDown,
  LoaderCircle,
  ShieldCheck,
  Square,
  XCircle,
} from "lucide-react";
import type { Case, Investigation } from "./api";
import { money } from "./api";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { InvestigationProgress } from "./InvestigationProgress";
import { ModalShell } from "./ModalShell";
import { useInvestigationPlayback } from "./useInvestigationPlayback";
import { useInvestigationFollowScroll } from "./useInvestigationFollowScroll";
import { localizeRecordedActivityText } from "./investigationActivity";
import "./investigation-dialog.css";

export type InvestigationDialogProps = {
  open: boolean;
  investigation?: Investigation;
  payment?: Case;
  pending: boolean;
  error?: string;
  stale?: string;
  animate: boolean;
  cancelling?: boolean;
  busy?: boolean;
  onClose: () => void;
  onCancel: () => void;
  onRetry?: () => void;
  children: ReactNode;
  subview?: ReactNode;
  subviewTitle?: string;
  onBack?: () => void;
};

export function InvestigationDialog({
  open,
  investigation: run,
  payment,
  pending,
  error,
  stale,
  animate,
  cancelling = false,
  busy = false,
  onClose,
  onCancel,
  onRetry,
  children,
  subview,
  subviewTitle,
  onBack,
}: InvestigationDialogProps) {
  // Keep playback mounted when this window closes; the request itself continues.
  const playback = useInvestigationPlayback(run, { animate, visible: open });
  const [evidence, setEvidence] = useState<{
    runId: string;
    id: string;
  } | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const mainContent = useRef<HTMLDivElement>(null);
  const mainScrollTop = useRef(0);
  const back = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const mainFocus = useRef<HTMLElement | null>(null);
  const restoreScroll = useRef(0);
  const wasSubview = useRef(false);
  const lastSubview = useRef<string | null>(null);
  const subviewFocus = useRef(new Map<string, HTMLElement>());
  const subviewScroll = useRef(new Map<string, number>());
  const externalSubview =
    subview !== undefined && subview !== null && subview !== false;
  const selectedEvidence =
    evidence?.runId === run?.id
      ? run?.evidence.find((item) => item.id === evidence?.id)
      : undefined;
  const showingEvidence = !pending && !!selectedEvidence;
  const showingSubview = externalSubview || showingEvidence;
  const subviewKey = externalSubview ? (subviewTitle ?? "review") : "evidence";
  const active = run?.status === "queued" || run?.status === "running";
  const completed = run?.status === "completed";
  const showResults = completed && playback.ready;
  const showingProcess =
    active || playback.replaying || playback.phase === "collapsing";
  const follow = useInvestigationFollowScroll({
    viewport: scroll,
    content: mainContent,
    sessionKey: run?.id ?? "pending",
    open,
    active: !pending && showingProcess,
    suspended: showingSubview,
    completed: showResults,
  });

  useEffect(() => {
    subviewFocus.current.clear();
    subviewScroll.current.clear();
    lastSubview.current = null;
  }, [run?.id]);

  useEffect(() => {
    if (!open) setEvidence(null);
  }, [open]);
  useEffect(() => {
    if (!open) {
      wasSubview.current = false;
      return;
    }
    if (
      showingSubview &&
      (!wasSubview.current || lastSubview.current !== subviewKey)
    ) {
      if (!wasSubview.current) {
        restoreFocus.current =
          mainFocus.current ?? (document.activeElement as HTMLElement | null);
        restoreScroll.current = mainScrollTop.current;
      }
      if (scroll.current)
        scroll.current.scrollTop = subviewScroll.current.get(subviewKey) ?? 0;
      const previousFocus = subviewFocus.current.get(subviewKey);
      if (previousFocus?.isConnected && previousFocus.getClientRects().length)
        previousFocus.focus({ preventScroll: true });
      else back.current?.focus({ preventScroll: true });
    } else if (!showingSubview && wasSubview.current) {
      if (scroll.current) scroll.current.scrollTop = restoreScroll.current;
      if (
        restoreFocus.current?.isConnected &&
        restoreFocus.current.getClientRects().length
      )
        restoreFocus.current.focus({ preventScroll: true });
    }
    wasSubview.current = showingSubview;
    lastSubview.current = showingSubview ? subviewKey : null;
  }, [open, showingSubview, subviewKey]);

  if (!open) return null;
  const close = () => {
    setEvidence(null);
    onClose();
  };
  const goBack = () => {
    if (externalSubview) {
      if (onBack) onBack();
      else close();
    } else setEvidence(null);
  };
  const paymentId = payment?.paymentId ?? run?.paymentId;
  const title = externalSubview
    ? (subviewTitle ?? "Human review")
    : showingEvidence
      ? "Source evidence · Original record"
      : "Payment investigation";
  const subtitle =
    [
      paymentId,
      payment?.vendor,
      payment ? money(payment.amount, payment.currency) : undefined,
    ]
      .filter(Boolean)
      .join(" · ") || "Preparing investigation";

  return (
    <ModalShell
      title={title}
      subtitle={subtitle}
      onClose={close}
      busy={busy}
      onEscape={showingSubview ? goBack : close}
      closeLabel="Close investigation"
      className="investigation-dialog"
      overlayClassName="investigation-dialog-overlay"
      headingPrefix={
        showingSubview ? (
          <button
            ref={back}
            type="button"
            className="investigation-dialog-back"
            aria-label="Back to investigation results"
            disabled={busy}
            onClick={goBack}
          >
            <ArrowLeft size={17} />
          </button>
        ) : undefined
      }
      headerActions={
        active ? (
          <button
            type="button"
            className="investigation-dialog-stop"
            disabled={cancelling}
            onClick={onCancel}
          >
            {cancelling ? (
              <LoaderCircle size={13} className="spin" />
            ) : (
              <Square size={12} />
            )}
            <span>{cancelling ? "Stopping…" : "Stop investigation"}</span>
          </button>
        ) : undefined
      }
    >
      <div
        ref={scroll}
        className="investigation-dialog-scroll"
        data-following={follow.following}
        tabIndex={-1}
        aria-label="Investigation content"
        onScroll={(event) => {
          if (!showingSubview)
            mainScrollTop.current = event.currentTarget.scrollTop;
        }}
      >
        <div
          ref={mainContent}
          className="investigation-dialog-main"
          hidden={showingSubview}
          onFocusCapture={(event) => {
            mainFocus.current = event.target as HTMLElement;
          }}
          onClickCapture={() => {
            mainScrollTop.current = scroll.current?.scrollTop ?? 0;
          }}
        >
          {pending && (
            <div className="investigation-dialog-pending" role="status">
              <LoaderCircle size={22} className="spin" aria-hidden="true" />
              <h3>Preparing investigation</h3>
              <p>
                Checking this payment’s investigation record. Recorded
                investigation steps will appear here.
              </p>
            </div>
          )}
          {error && (
            <div className="investigation-dialog-error" role="alert">
              <XCircle size={18} aria-hidden="true" />
              <div>
                <strong>
                  {run ? "Action failed" : "Unable to open investigation"}
                </strong>
                <p>{error}</p>
                {!run && onRetry && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={onRetry}
                  >
                    Retry
                  </button>
                )}
              </div>
            </div>
          )}
          {run && !pending && (
            <>
              {run.error && (
                <p className="investigation-dialog-error" role="alert">
                  {localizeRecordedActivityText(run.error)}
                </p>
              )}
              <div className="investigation-dialog-process-header">
                <span
                  className={`investigation-dialog-stage${showResults ? " is-results" : ""}`}
                >
                  {active
                    ? "Investigating payment…"
                    : completed && !playback.ready
                      ? "Investigation complete. Showing recorded steps…"
                      : run.status === "failed"
                        ? "Investigation failed"
                        : run.status === "cancelled"
                          ? "Investigation stopped"
                          : "Investigation results"}
                </span>
                {completed && !playback.ready && (
                  <button
                    type="button"
                    className="investigation-dialog-skip"
                    onClick={playback.skip}
                  >
                    Skip to results
                    <ArrowRight size={13} />
                  </button>
                )}
              </div>
              <div
                className={`investigation-dialog-process${playback.phase === "collapsing" ? " is-collapsing" : ""}`}
              >
                <InvestigationProgress
                  investigation={run}
                  stale={stale}
                  playback={playback}
                  onEvidence={(id) => setEvidence({ runId: run.id, id })}
                />
              </div>
              {showResults && (
                <div className="investigation-dialog-results">{children}</div>
              )}
              {!showResults && active && (
                <p className="investigation-dialog-continuation">
                  You can close this window and return to the inbox. The
                  investigation will continue in the background.
                </p>
              )}
              {!active && !completed && onRetry && (
                <div className="investigation-dialog-retry">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={onRetry}
                  >
                    Retry investigation
                  </button>
                </div>
              )}
            </>
          )}
        </div>
        {externalSubview ? (
          <div
            className="investigation-dialog-subview"
            onFocusCapture={(event) =>
              subviewFocus.current.set(subviewKey, event.target as HTMLElement)
            }
            onClickCapture={() =>
              subviewScroll.current.set(
                subviewKey,
                scroll.current?.scrollTop ?? 0,
              )
            }
          >
            {subview}
          </div>
        ) : showingEvidence && selectedEvidence && run ? (
          <div className="investigation-dialog-subview">
            <EvidenceDrawer
              embedded
              evidence={run.evidence}
              selected={selectedEvidence}
              onSelect={(id) => setEvidence({ runId: run.id, id })}
              onClose={() => setEvidence(null)}
              queries={run.queries}
              paymentId={run.paymentId}
            />
          </div>
        ) : null}
      </div>
      {!follow.following && showingProcess && !showingSubview && !pending && (
        <button
          type="button"
          className="investigation-dialog-follow"
          onClick={follow.jumpToLatest}
        >
          <ArrowDown size={13} aria-hidden="true" />
          Jump to latest
        </button>
      )}
      <footer className="investigation-dialog-footer">
        <ShieldCheck size={13} aria-hidden="true" />
        <span>
          Based on recorded source evidence. Reviews do not execute payments or
          post journal entries.
        </span>
      </footer>
    </ModalShell>
  );
}
