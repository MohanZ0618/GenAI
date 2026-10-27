import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";

let scrollLocks = 0;
let restorePageScroll: (() => void) | undefined;

function lockPageScroll() {
  scrollLocks++;
  if (scrollLocks === 1) {
    const body = document.body;
    const html = document.documentElement;
    const bodyKeys = [
      "overflow",
      "position",
      "top",
      "left",
      "right",
      "width",
      "paddingRight",
    ] as const;
    const original = bodyKeys.map((key) => [key, body.style[key]] as const);
    const overflow = html.style.overflow;
    const x = window.scrollX;
    const y = window.scrollY;
    const scrollbar = Math.max(0, window.innerWidth - html.clientWidth);
    const padding = parseFloat(getComputedStyle(body).paddingRight) || 0;
    html.style.overflow = "hidden";
    body.style.overflow = "hidden";
    body.style.position = "fixed";
    body.style.top = `-${y}px`;
    body.style.left = `-${x}px`;
    body.style.right = "0";
    body.style.width = "100%";
    if (scrollbar) body.style.paddingRight = `${padding + scrollbar}px`;
    restorePageScroll = () => {
      for (const [key, value] of original) body.style[key] = value;
      html.style.overflow = overflow;
      const behavior = html.style.scrollBehavior;
      html.style.scrollBehavior = "auto";
      window.scrollTo(x, y);
      html.style.scrollBehavior = behavior;
    };
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    scrollLocks--;
    if (!scrollLocks) {
      restorePageScroll?.();
      restorePageScroll = undefined;
    }
  };
}

export function ModalShell({
  title,
  subtitle,
  onClose,
  busy = false,
  children,
  className = "",
  overlayClassName = "",
  headerActions,
  headingPrefix,
  closeLabel = "Close dialog",
  onEscape,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  busy?: boolean;
  children: ReactNode;
  className?: string;
  overlayClassName?: string;
  headerActions?: ReactNode;
  headingPrefix?: ReactNode;
  closeLabel?: string;
  onEscape?: () => void;
}) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const closeState = useRef({ onClose, busy, onEscape });
  closeState.current = { onClose, busy, onEscape };
  useEffect(() => lockPageScroll(), []);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    (
      ref.current?.querySelector<HTMLElement>("[data-modal-autofocus]") ??
      ref.current?.querySelector<HTMLElement>("button, input, textarea")
    )?.focus();
    function onKey(event: KeyboardEvent) {
      const dialogs = [
        ...document.querySelectorAll<HTMLElement>(
          '[role="dialog"][aria-modal="true"]',
        ),
      ].filter((element) => element.getClientRects().length);
      if (event.defaultPrevented || dialogs.at(-1) !== ref.current) return;
      if (event.key === "Escape" && !closeState.current.busy) {
        event.preventDefault();
        (closeState.current.onEscape ?? closeState.current.onClose)();
      }
      if (event.key !== "Tab") return;
      const nodes = [
        ...(ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary, [tabindex="0"]',
        ) ?? []),
      ].filter(
        (node) =>
          node.getClientRects().length && !node.closest("[hidden], [inert]"),
      );
      if (!nodes?.length) {
        event.preventDefault();
        ref.current?.focus();
        return;
      }
      const first = nodes[0],
        last = nodes[nodes.length - 1];
      if (
        document.activeElement === ref.current ||
        !ref.current?.contains(document.activeElement)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    if (busy) ref.current?.focus();
  }, [busy]);
  return (
    <div
      className={`modal-overlay ${overlayClassName}`.trim()}
      onMouseDown={(event) => {
        if (!busy && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${className}`.trim()}
        ref={ref}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-busy={busy}
        aria-labelledby={titleId}
      >
        <div className="modal-heading">
          {headingPrefix}
          <div>
            <h2 id={titleId}>{title}</h2>
            <p>{subtitle}</p>
          </div>
          {headerActions}
          <button
            className="icon-button"
            onClick={onClose}
            aria-label={closeLabel}
            data-modal-autofocus
            disabled={busy}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
