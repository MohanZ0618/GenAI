import { useId } from "react";
import type { ReactNode } from "react";
import { ChevronRight, Database, FileText, Fingerprint } from "lucide-react";
import type { Evidence, Investigation } from "./api";
import { date, label, money } from "./api";
import { ModalShell } from "./ModalShell";
import "./evidence-drawer.css";

type EvidenceDrawerProps = {
  evidence: Evidence[];
  selected: Evidence | undefined;
  onSelect: (id: string) => void;
  onClose: () => void;
  queries: Investigation["queries"];
  paymentId: string;
  findingTitle?: string;
  embedded?: boolean;
};

function EvidenceContainer({
  embedded,
  onClose,
  children,
}: {
  embedded: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (embedded)
    return (
      <section
        className="evidence-drawer evidence-drawer-embedded"
        aria-label="Original record"
      >
        {children}
      </section>
    );
  return (
    <div className="evidence-drawer">
      <ModalShell
        title="Original record"
        subtitle="Source evidence"
        onClose={onClose}
      >
        {children}
      </ModalShell>
    </div>
  );
}

function fieldLabel(key: string) {
  return label(key.replace(/([a-z\d])([A-Z])/g, "$1 $2"));
}

function RecordedValue({ value }: { value: unknown }) {
  if (value !== null && typeof value === "object") {
    return (
      <pre className="evidence-drawer-json">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return <>{value == null || value === "" ? "—" : String(value)}</>;
}

function amountSummary(record: Record<string, unknown>) {
  const amount = record.amount;
  if (
    (typeof amount !== "string" && typeof amount !== "number") ||
    String(amount).trim() === "" ||
    !Number.isFinite(Number(amount))
  )
    return null;
  const currency = record.currency;
  return typeof currency === "string" && /^[A-Z]{3}$/i.test(currency)
    ? money(amount, currency.toUpperCase())
    : String(amount);
}

export function EvidenceDrawer({
  evidence,
  selected,
  onSelect,
  onClose,
  queries,
  paymentId,
  findingTitle,
  embedded = false,
}: EvidenceDrawerProps) {
  const pickerId = useId();
  const query = selected
    ? queries.find((item) => item.id === selected.queryId)
    : undefined;
  // Older or extended API responses may also contain a recorded statement.
  // Current QueryTrace responses contain execution metadata, not SQL text.
  const queryFields = query as unknown as Record<string, unknown> | undefined;
  const statement =
    queryFields?.sql ?? queryFields?.statement ?? queryFields?.query;
  const summaryAmount = selected ? amountSummary(selected.record ?? {}) : null;
  const recordedStatus = selected?.record?.status;

  return (
    <EvidenceContainer embedded={embedded} onClose={onClose}>
      <div className="evidence-drawer-body">
        <div className="evidence-drawer-context">
          <strong>{paymentId}</strong>
          {findingTitle && <p>Selected finding: {findingTitle}</p>}
        </div>

        <div className="evidence-drawer-picker">
          <label htmlFor={pickerId}>Evidence record</label>
          <select
            id={pickerId}
            value={selected?.id ?? ""}
            disabled={!evidence.length}
            onChange={(event) => onSelect(event.target.value)}
          >
            {!selected && <option value="">Select a source record</option>}
            {evidence.map((item) => (
              <option key={item.id} value={item.id}>
                {item.recordId} · {fieldLabel(item.table)}
              </option>
            ))}
          </select>
        </div>

        {!selected ? (
          <div className="evidence-drawer-empty">
            <FileText size={26} aria-hidden="true" />
            <h3>No record selected</h3>
            <p>
              {evidence.length
                ? "Choose a record to inspect its fields and query provenance."
                : "This investigation has not retrieved any source evidence."}
            </p>
          </div>
        ) : (
          <>
            <section
              className="evidence-drawer-summary"
              aria-label="Selected source record"
            >
              <div className="evidence-drawer-source-label">
                <Database size={15} aria-hidden="true" />
                <span>{fieldLabel(selected.table)}</span>
              </div>
              <div className="evidence-drawer-summary-heading">
                <h3>{selected.recordId}</h3>
                {typeof recordedStatus === "string" &&
                  recordedStatus !== "" && (
                    <span className="evidence-drawer-status">
                      {fieldLabel(recordedStatus)}
                    </span>
                  )}
              </div>
              {summaryAmount && (
                <p className="evidence-drawer-amount">{summaryAmount}</p>
              )}
              <p className="evidence-drawer-record-reference">
                Evidence ID: {selected.id}
              </p>
            </section>

            <section className="evidence-drawer-section">
              <h3>Source and record identity</h3>
              <dl className="evidence-drawer-fields">
                <div>
                  <dt>Source table</dt>
                  <dd>{selected.table}</dd>
                </div>
                <div>
                  <dt>Source record ID</dt>
                  <dd>{selected.recordId}</dd>
                </div>
                <div className="evidence-drawer-field-wide">
                  <dt>Dataset version</dt>
                  <dd>{selected.datasetVersion || "Not recorded"}</dd>
                </div>
              </dl>
            </section>

            <section className="evidence-drawer-section">
              <h3>Original record fields</h3>
              <dl className="evidence-drawer-fields">
                {Object.entries(selected.record ?? {}).map(([key, value]) => (
                  <div
                    key={key}
                    className={
                      typeof value === "object" ||
                      String(value ?? "").length > 55
                        ? "evidence-drawer-field-wide"
                        : undefined
                    }
                  >
                    <dt title={key}>{fieldLabel(key)}</dt>
                    <dd>
                      <RecordedValue value={value} />
                    </dd>
                  </div>
                ))}
              </dl>
              {!Object.keys(selected.record ?? {}).length && (
                <p className="evidence-drawer-note">
                  No source fields were recorded for this evidence.
                </p>
              )}
            </section>

            <section className="evidence-drawer-section">
              <div className="evidence-drawer-section-heading">
                <h3>Related references</h3>
                <span>{evidence.length} records</span>
              </div>
              <p className="evidence-drawer-note">
                Source records in this investigation. Shared queries are marked.
              </p>
              <div
                className="evidence-drawer-record-list"
                role="group"
                aria-label="Select investigation evidence"
              >
                {evidence.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={item.id === selected.id ? "is-selected" : ""}
                    aria-current={item.id === selected.id ? "true" : undefined}
                    onClick={() => onSelect(item.id)}
                  >
                    <FileText size={15} aria-hidden="true" />
                    <span className="evidence-drawer-record-label">
                      <strong>{item.recordId}</strong>
                      <small>{fieldLabel(item.table)}</small>
                    </span>
                    {item.id !== selected.id &&
                      selected.queryId &&
                      item.queryId === selected.queryId && (
                        <span className="evidence-drawer-same-query">
                          Same query
                        </span>
                      )}
                    <ChevronRight size={15} aria-hidden="true" />
                  </button>
                ))}
              </div>
            </section>

            <section className="evidence-drawer-section">
              <h3 className="evidence-drawer-icon-heading">
                <Fingerprint size={16} aria-hidden="true" />
                Query provenance
              </h3>
              <dl className="evidence-drawer-fields">
                <div className="evidence-drawer-field-wide">
                  <dt>Query ID</dt>
                  <dd>{selected.queryId || "Not recorded"}</dd>
                </div>
                {query && (
                  <>
                    <div>
                      <dt>Retrieval tool</dt>
                      <dd>{fieldLabel(query.tool)}</dd>
                    </div>
                    <div>
                      <dt>Query status</dt>
                      <dd>{fieldLabel(query.status)}</dd>
                    </div>
                    <div className="evidence-drawer-field-wide">
                      <dt>Retrieved at</dt>
                      <dd>{date(query.at, true)}</dd>
                    </div>
                    <div>
                      <dt>Duration</dt>
                      <dd>{query.durationMs.toLocaleString()} ms</dd>
                    </div>
                    <div>
                      <dt>Rows returned</dt>
                      <dd>{query.rowCount.toLocaleString()}</dd>
                    </div>
                    <div className="evidence-drawer-field-wide">
                      <dt>Queried tables</dt>
                      <dd>{query.tables.join(", ") || "Not recorded"}</dd>
                    </div>
                    {query.error && (
                      <div className="evidence-drawer-field-wide">
                        <dt>Query error</dt>
                        <dd>{query.error}</dd>
                      </div>
                    )}
                  </>
                )}
              </dl>
              {!query && (
                <p className="evidence-drawer-note">
                  No matching query trace was recorded for this evidence.
                </p>
              )}

              {query && Object.keys(query.coverage ?? {}).length > 0 && (
                <div className="evidence-drawer-coverage">
                  <h4>Recorded source coverage</h4>
                  {Object.entries(query.coverage).map(([table, coverage]) => (
                    <div key={table}>
                      <strong>{fieldLabel(table)}</strong>
                      <RecordedValue value={coverage} />
                    </div>
                  ))}
                </div>
              )}

              {statement !== undefined && statement !== null && (
                <div className="evidence-drawer-statement">
                  <h4>Recorded query</h4>
                  <pre>
                    {typeof statement === "string"
                      ? statement
                      : JSON.stringify(statement, null, 2)}
                  </pre>
                </div>
              )}
              <p className="evidence-drawer-note evidence-drawer-boundary">
                Original source evidence is read-only. A source record alone
                does not establish the investigation's final conclusion.
              </p>
            </section>
          </>
        )}
      </div>
    </EvidenceContainer>
  );
}
