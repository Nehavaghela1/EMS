import { AxiosError } from "axios";

/** Mirrors app/core/exceptions.py's envelope (Spec 6.6) exactly. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown> | null;
    request_id: string;
  };
}

export interface ParsedApiError {
  code: string;
  message: string;
  details: Record<string, unknown> | null;
  requestId: string | null;
  status: number | null;
}

const GENERIC_MESSAGE = "Something went wrong. Please try again.";

/**
 * Every page renders `error.message` from this, never a raw error object —
 * a malformed body or a network failure (no response at all) still produces
 * a readable message instead of `[object Object]`.
 */
export function parseApiError(err: unknown): ParsedApiError {
  if (err instanceof AxiosError) {
    const body = err.response?.data as Partial<ApiErrorBody> | undefined;
    if (body?.error?.message) {
      return {
        code: body.error.code ?? "unknown_error",
        message: withFieldDetail(body.error.message, body.error.details ?? null),
        details: body.error.details ?? null,
        requestId: body.error.request_id ?? null,
        status: err.response?.status ?? null,
      };
    }
    if (err.response) {
      return {
        code: "unknown_error",
        message: `Request failed (${err.response.status}).`,
        details: null,
        requestId: null,
        status: err.response.status,
      };
    }
    return {
      code: "network_error",
      message: "Could not reach the server. Check your connection and try again.",
      details: null,
      requestId: null,
      status: null,
    };
  }
  return { code: "unknown_error", message: GENERIC_MESSAGE, details: null, requestId: null, status: null };
}

/** Turns a FastAPI field name like `effective_from` into "Effective from". */
function humanField(field: string): string {
  const words = field.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A 422 says only "The request body failed validation."; the reason sits in
 * `details.errors`. Add up to three field reasons so the user knows what to fix. */
function withFieldDetail(message: string, details: Record<string, unknown> | null): string {
  const errors = details?.errors;
  if (!Array.isArray(errors) || errors.length === 0) return message;
  const parts: string[] = [];
  for (const e of errors.slice(0, 3)) {
    const loc = (e as { loc?: unknown[] }).loc;
    const raw = (e as { msg?: string }).msg;
    if (typeof raw !== "string") continue;
    const msg = raw.replace(/^Value error, /, "");
    const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined;
    parts.push(typeof field === "string" && field !== "body" ? `${humanField(field)}: ${msg}` : msg);
  }
  return parts.length ? parts.join(" ") : message;
}

/** For a 422 (`validation_error`), `details.errors` is FastAPI's own
 * RequestValidationError list — each with `loc` (e.g. `["body","email"]`)
 * and `msg`. Used to attach a message to the right form field. */
export function fieldErrorsFromDetails(details: Record<string, unknown> | null): Record<string, string> {
  const result: Record<string, string> = {};
  const errors = details?.errors;
  if (!Array.isArray(errors)) return result;
  for (const e of errors) {
    const loc = (e as { loc?: unknown[] }).loc;
    const msg = (e as { msg?: string }).msg;
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const field = loc[loc.length - 1];
    if (typeof field === "string") result[field] = msg;
  }
  return result;
}
