import { useEffect, useRef, useState } from "react";
import { Trash2, Undo2 } from "lucide-react";
import { api } from "./api";
import { ModalShell } from "./ModalShell";

type Item = { id: string; label: string };
type Result = { id: string; success: boolean; error?: string };

export function useRemoval({
  kind,
  items,
  visibleItems = items,
  endpoint,
  onChanged,
}: {
  kind: "dataset" | "memory";
  items: Item[];
  visibleItems?: Item[];
  endpoint: string;
  onChanged: (ids: string[], removed: boolean) => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Item[]>([]);
  const [undo, setUndo] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const lock = useRef(false);
  const plural = kind === "memory" ? "memories" : "datasets";
  const visibleSelected =
    visibleItems.length > 0 &&
    visibleItems.every((item) => selected.has(item.id));

  useEffect(() => {
    if (!undo.length) return;
    const timer = window.setTimeout(() => setUndo([]), 15000);
    return () => window.clearTimeout(timer);
  }, [undo]);
  const itemIds = items.map((item) => item.id).join("\n");
  useEffect(() => {
    const valid = new Set(itemIds.split("\n"));
    setSelected(
      (previous) => new Set([...previous].filter((id) => valid.has(id))),
    );
  }, [itemIds]);

  async function apply(ids: string[], removed: boolean) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const { results } = await api<{ results: Result[] }>(endpoint, {
        method: "POST",
        body: JSON.stringify({ ids, removed }),
      });
      const succeeded = results
        .filter((result) => result.success)
        .map((result) => result.id);
      const failed = ids.filter((id) => !succeeded.includes(id));
      setSelected(
        (previous) =>
          new Set(
            [...previous]
              .filter((id) => !succeeded.includes(id))
              .concat(removed ? failed : []),
          ),
      );
      setUndo(removed ? succeeded : failed);
      setPending([]);
      setMessage(
        `${succeeded.length} ${succeeded.length === 1 ? kind : plural} ${removed ? "removed" : "restored"}.`,
      );
      if (failed.length)
        setError(
          failed
            .map(
              (id) =>
                `${items.find((item) => item.id === id)?.label || id}: ${results.find((result) => result.id === id)?.error || "No confirmation received. Please retry."}`,
            )
            .join(" "),
        );
      if (succeeded.length) await onChanged(succeeded, removed);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to update selected items.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  function checkbox(item: Item) {
    return (
      <label
        className="resource-selection"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          type="checkbox"
          aria-label={`Select ${kind} ${item.label}`}
          checked={selected.has(item.id)}
          disabled={busy}
          onChange={(event) =>
            setSelected((previous) => {
              const next = new Set(previous);
              if (event.target.checked) next.add(item.id);
              else next.delete(item.id);
              return next;
            })
          }
        />
        <span className="sr-only">Select {item.label}</span>
      </label>
    );
  }
  function removeButton(item: Item) {
    return (
      <button
        className="button secondary resource-remove"
        aria-label={`Remove ${kind} ${item.label}`}
        disabled={busy}
        onClick={(event) => {
          event.stopPropagation();
          setError("");
          setPending([item]);
        }}
      >
        <Trash2 size={15} /> Remove
      </button>
    );
  }
  const controls = (
    <>
      <div className="resource-toolbar" aria-label={`${kind} selection`}>
        <label>
          <input
            type="checkbox"
            aria-label={`Select all matching ${plural}`}
            disabled={busy || !visibleItems.length}
            checked={visibleSelected}
            onChange={() =>
              setSelected((previous) => {
                const next = new Set(previous);
                visibleItems.forEach((item) => {
                  if (visibleSelected) next.delete(item.id);
                  else next.add(item.id);
                });
                return next;
              })
            }
          />{" "}
          Select all matching
        </label>
        <span>
          {selected.size} {plural} selected
        </span>
        {selected.size > 0 && (
          <>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setSelected(new Set())}
            >
              Clear selection
            </button>
            <button
              className="button secondary resource-remove"
              disabled={busy}
              onClick={() => {
                setError("");
                setPending(items.filter((item) => selected.has(item.id)));
              }}
            >
              Remove selected
            </button>
          </>
        )}
      </div>
      {message && (
        <div className="resource-notice" role="status">
          {message}{" "}
          {undo.length > 0 && (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void apply(undo, false)}
            >
              <Undo2 size={15} /> Undo
            </button>
          )}
        </div>
      )}
      {error && pending.length === 0 && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {pending.length > 0 && (
        <ModalShell
          title={`Remove ${pending.length} ${pending.length === 1 ? kind : plural}?`}
          subtitle="This removes items from the current list. History is preserved."
          busy={busy}
          onClose={() => setPending([])}
        >
          <div className="modal-body">
            {error && (
              <p className="inline-error" role="alert">
                {error}
              </p>
            )}
            <ul className="removal-items">
              {pending.map((item) => (
                <li key={item.id}>{item.label}</li>
              ))}
            </ul>
            <p>
              {kind === "dataset"
                ? "Removed datasets cannot be selected for new investigations. Existing investigations and source evidence remain available. Datasets with active investigations cannot be removed."
                : "Removed memories will no longer be recalled. Existing investigations keep their original memory snapshots. Undo restores the previous active or inactive state."}
            </p>
            <p>
              You can undo successful removals from this page for 15 seconds.
            </p>
          </div>
          <div className="modal-footer">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setPending([])}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() =>
                void apply(
                  pending.map((item) => item.id),
                  true,
                )
              }
            >
              {busy
                ? "Removing…"
                : `Remove ${pending.length} ${pending.length === 1 ? kind : plural}`}
            </button>
          </div>
        </ModalShell>
      )}
    </>
  );
  return { controls, checkbox, removeButton, busy };
}
