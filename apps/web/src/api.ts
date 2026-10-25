import { parseTime } from "../../../packages/contracts/src/index";
import type {
  Mode,
  Dataset,
  Case,
  Investigation,
  EvidenceReference,
} from "../../../packages/contracts/src/index";
export type { Mode, Dataset, Case, Investigation };
export type Evidence = EvidenceReference;
export type Health = {
  mode: Mode;
  integrations?: Record<string, unknown>;
  provider?: string;
  model?: string;
  [key: string]: unknown;
};

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        ...(options?.body === undefined
          ? {}
          : { "Content-Type": "application/json" }),
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(
      "Cannot reach the FinTrace API. Check that the server is running, then try again.",
    );
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: string | { message?: string };
      message?: string;
    } | null;
    const detail =
      typeof body?.error === "string"
        ? body.error
        : (body?.error?.message ?? body?.message);
    throw new Error(
      detail || `Request failed (${response.status}). Please try again.`,
    );
  }
  return response.json() as Promise<T>;
}

export function money(amount: number | string, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(Number(amount));
  } catch {
    return `${currency} ${Number(amount).toFixed(2)}`;
  }
}
export function date(value: string | undefined, withTime = false): string {
  if (!value) return "Not available";
  const parsed = new Date(parseTime(value));
  if (Number.isNaN(parsed.getTime())) return value;
  return (
    new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
      ...(withTime ? ({ hour: "numeric", minute: "2-digit" } as const) : {}),
    }).format(parsed) + (withTime ? " UTC" : "")
  );
}
export function label(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
export function textValue(value: unknown): string {
  return typeof value === "string"
    ? value
    : value == null
      ? "—"
      : JSON.stringify(value);
}
