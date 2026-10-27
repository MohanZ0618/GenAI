import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { Investigation } from "./api";
import {
  investigationSteps,
  type InvestigationStep,
} from "./investigationActivity";

export type InvestigationPlayback = {
  ready: boolean;
  replaying: boolean;
  phase: "process" | "collapsing" | "results" | "interrupted";
  steps: InvestigationStep[];
  fullSteps: InvestigationStep[];
  currentStepId?: string;
  skip: () => void;
};
type Options = { animate: boolean; visible: boolean; reducedMotion?: boolean };
type View = Omit<InvestigationPlayback, "skip"> & { runId?: string };
type Cursor = {
  reason: string;
  summary: string;
  reasonShown: number;
  summaryShown: number;
  typingMs: number;
  shown: boolean;
  finished: boolean;
};
type Session = {
  run: Investigation;
  fullSteps: InvestigationStep[];
  mainSteps: InvestigationStep[];
  cursors: Map<string, Cursor>;
  phase: View["phase"];
  collapseMs: number;
  skipped: boolean;
};

const TICK_MS = 20;
const STEP_LIMIT_MS = 1200;
const COLLAPSE_MS = 200;
const characters = (text: string) => Array.from(text);
const length = (text: string) => characters(text).length;
const backendActive = (run: Investigation) =>
  run.status === "queued" || run.status === "running";

export function mainInvestigationSteps(steps: InvestigationStep[]) {
  const verification = [...steps]
    .reverse()
    .find((step) => step.kind === "verification");
  return steps.filter(
    (step) =>
      step.kind === "tool" ||
      step.kind === "memory" ||
      (step.kind === "planning" && step.status === "running") ||
      step.id === verification?.id,
  );
}

function updateCursor(cursor: Cursor, step: InvestigationStep) {
  for (const field of ["reason", "summary"] as const) {
    const next = step[field] || "";
    const shown = field === "reason" ? "reasonShown" : "summaryShown";
    // Appended text continues from its cursor. Corrections replace the text
    // immediately rather than erasing and retyping already visible words.
    if (
      cursor.finished ||
      (cursor[shown] > 0 && !next.startsWith(cursor[field]))
    )
      cursor[shown] = length(next);
    cursor[field] = next;
    cursor[shown] = Math.min(cursor[shown], length(next));
  }
}

function ingest(session: Session, run: Investigation) {
  session.run = run;
  session.fullSteps = investigationSteps(run);
  session.mainSteps = mainInvestigationSteps(session.fullSteps);
  for (const step of session.mainSteps) {
    let cursor = session.cursors.get(step.id);
    if (!cursor) {
      cursor = {
        reason: "",
        summary: "",
        reasonShown: 0,
        summaryShown: 0,
        typingMs: 0,
        shown: false,
        finished: false,
      };
      session.cursors.set(step.id, cursor);
    }
    updateCursor(cursor, step);
  }
}

function createSession(run: Investigation): Session {
  const session: Session = {
    run,
    fullSteps: [],
    mainSteps: [],
    cursors: new Map(),
    phase: "process",
    collapseMs: 0,
    skipped: false,
  };
  ingest(session, run);
  return session;
}

export const createInvestigationPlaybackCache = () =>
  new Map<string, Session>();
// A dismissed/remounted dialog can resume during this browser session. This is
// presentation state only; it never starts a run or changes a backend result.
const savedSessions = createInvestigationPlaybackCache();

function textComplete(cursor: Cursor) {
  return (
    cursor.reasonShown >= length(cursor.reason) &&
    cursor.summaryShown >= length(cursor.summary)
  );
}

function currentStep(session: Session) {
  for (const step of session.mainSteps) {
    const cursor = session.cursors.get(step.id)!;
    if (cursor.finished) continue;
    cursor.shown = true;
    if (textComplete(cursor) && step.status !== "running") {
      cursor.finished = true;
      continue;
    }
    return step;
  }
  return undefined;
}

function showAll(session: Session) {
  for (const step of session.mainSteps) {
    const cursor = session.cursors.get(step.id)!;
    cursor.shown = true;
    cursor.reasonShown = length(cursor.reason);
    cursor.summaryShown = length(cursor.summary);
    cursor.finished = step.status !== "running";
  }
}

function reconcile(session: Session, options: Options) {
  const interrupted =
    session.run.status === "failed" || session.run.status === "cancelled";
  const instant = !options.animate || options.reducedMotion || session.skipped;
  if (interrupted || instant) showAll(session);
  if (interrupted) {
    session.phase = "interrupted";
    return;
  }
  if (backendActive(session.run)) {
    session.phase = "process";
    session.collapseMs = 0;
    currentStep(session);
    return;
  }
  if (instant || !session.mainSteps.length) {
    session.phase = "results";
    return;
  }
  if (currentStep(session)) {
    session.phase = "process";
    session.collapseMs = 0;
  } else if (session.phase !== "results") {
    session.phase = "collapsing";
  }
}

function view(session: Session): View {
  const current = currentStep(session);
  const ready = session.phase === "results" || session.phase === "interrupted";
  return {
    runId: session.run.id,
    ready,
    replaying: session.run.status === "completed" && !ready,
    phase: session.phase,
    currentStepId: ready ? undefined : current?.id,
    fullSteps: session.fullSteps,
    steps: session.mainSteps
      .filter((step) => session.cursors.get(step.id)!.shown)
      .map((step) => {
        const cursor = session.cursors.get(step.id)!;
        return {
          ...step,
          reason: characters(cursor.reason)
            .slice(0, cursor.reasonShown)
            .join(""),
          summary: characters(cursor.summary)
            .slice(0, cursor.summaryShown)
            .join(""),
          evidenceIds: textComplete(cursor) ? step.evidenceIds : [],
        };
      }),
  };
}

const emptyView = (): View => ({
  ready: false,
  replaying: false,
  phase: "process",
  steps: [],
  fullSteps: [],
});

/** The same timer-driven state machine is used by React and the clock tests. */
export class InvestigationPlaybackController {
  private session?: Session;
  private options: Options = { animate: true, visible: false };
  private timer?: ReturnType<typeof setTimeout>;
  private snapshot: View = emptyView();
  private listeners = new Set<() => void>();
  constructor(private cache = createInvestigationPlaybackCache()) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  getSnapshot = () => this.snapshot;

  preview(run: Investigation | undefined, options: Options): View {
    if (!run) return emptyView();
    const cached = this.cache.get(run.id);
    if (cached) return view(cached);
    const session = createSession(run);
    reconcile(session, options);
    return view(session);
  }

  configure(run: Investigation | undefined, options: Options) {
    this.pause();
    this.options = options;
    if (!run) {
      this.session = undefined;
      this.publish(emptyView());
      return;
    }
    let session = this.cache.get(run.id);
    if (!session) {
      session = createSession(run);
      this.cache.set(run.id, session);
    } else ingest(session, run);
    this.session = session;
    reconcile(session, options);
    this.publish(view(session));
    this.schedule();
  }

  skip = () => {
    if (!this.session) return;
    this.pause();
    this.session.skipped = true;
    reconcile(this.session, this.options);
    this.publish(view(this.session));
  };

  pause() {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
  }

  private publish(snapshot: View) {
    this.snapshot = snapshot;
    for (const listener of this.listeners) listener();
  }

  private schedule() {
    const session = this.session;
    if (!session || !this.options.visible) return;
    const step = currentStep(session);
    const needsText = step && !textComplete(session.cursors.get(step.id)!);
    if (session.phase !== "collapsing" && !needsText) return;
    const delay =
      session.phase === "collapsing"
        ? Math.max(1, COLLAPSE_MS - session.collapseMs)
        : TICK_MS;
    const started = Date.now();
    this.timer = setTimeout(() => {
      this.timer = undefined;
      this.advance(Math.max(delay, Date.now() - started));
    }, delay);
  }

  private advance(elapsed: number) {
    const session = this.session;
    if (!session || !this.options.visible) return;
    if (session.phase === "collapsing") {
      session.collapseMs += elapsed;
      if (session.collapseMs >= COLLAPSE_MS) session.phase = "results";
    } else {
      const step = currentStep(session);
      if (step) {
        const cursor = session.cursors.get(step.id)!;
        cursor.typingMs += elapsed;
        if (cursor.typingMs >= STEP_LIMIT_MS) {
          cursor.reasonShown = length(cursor.reason);
          cursor.summaryShown = length(cursor.summary);
        } else {
          const reasonRemaining = length(cursor.reason) - cursor.reasonShown;
          const reasonAdded = Math.min(2, reasonRemaining);
          cursor.reasonShown += reasonAdded;
          cursor.summaryShown = Math.min(
            length(cursor.summary),
            cursor.summaryShown + 2 - reasonAdded,
          );
        }
      }
      reconcile(session, this.options);
    }
    this.publish(view(session));
    this.schedule();
  }
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
  );
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!media) return;
    const changed = () => setReduced(media.matches);
    changed();
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  return reduced;
}

export function useInvestigationPlayback(
  run: Investigation | undefined,
  { animate, visible }: { animate: boolean; visible: boolean },
): InvestigationPlayback {
  const reference = useRef<InvestigationPlaybackController | null>(null);
  if (!reference.current)
    reference.current = new InvestigationPlaybackController(savedSessions);
  const controller = reference.current;
  const reducedMotion = useReducedMotion();
  const subscribe = useCallback(controller.subscribe, [controller]);
  const snapshot = useSyncExternalStore(subscribe, controller.getSnapshot);
  useLayoutEffect(() => {
    controller.configure(run, { animate, visible, reducedMotion });
  }, [controller, run, animate, visible, reducedMotion]);
  useEffect(() => () => controller.pause(), [controller]);
  const current =
    snapshot.runId === run?.id
      ? snapshot
      : controller.preview(run, { animate, visible, reducedMotion });
  return {
    ready: current.ready,
    replaying: current.replaying,
    phase: current.phase,
    steps: current.steps,
    fullSteps: current.fullSteps,
    currentStepId: current.currentStepId,
    skip: controller.skip,
  };
}
