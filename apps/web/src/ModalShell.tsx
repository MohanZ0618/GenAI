import { useEffect, useRef } from "react";
import { X } from "lucide-react";

export function ModalShell({
  title,
  subtitle,
  onClose,
  busy = false,
  children,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  busy?: boolean;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeState = useRef({ onClose, busy });
  closeState.current = { onClose, busy };
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, input, textarea")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !closeState.current.busy)
        closeState.current.onClose();
      if (event.key !== "Tab") return;
      const nodes = ref.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]',
      );
      if (!nodes?.length) {
        event.preventDefault();
        ref.current?.focus();
        return;
      }
      const first = nodes[0],
        last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
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
      previous?.focus();
    };
  }, []);
  useEffect(() => {
    if (busy) ref.current?.focus();
  }, [busy]);
  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (!busy && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        ref={ref}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-busy={busy}
        aria-labelledby="modal-title"
      >
        <div className="modal-heading">
          <div>
            <h2 id="modal-title">{title}</h2>
            <p>{subtitle}</p>
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close dialog"
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
