import type { ApiEnvelope } from "../types";

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  fieldErrors: Record<string, string[]> | null;

  constructor(message: string, status: number, fieldErrors: Record<string, string[]> | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

/**
 * Normalise a `fetch` rejection. A caller-initiated cancellation is re-thrown
 * untouched — reporting "check your connection" for a request the app aborted
 * itself would be a lie the caller cannot tell apart from a real outage.
 */
function throwNetworkError(cause: unknown): never {
  if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
  throw new ApiError("Network error. Check your connection and try again.", 0, null);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
}

export type QueryParams = Record<string, string | number | boolean | undefined>;

/** Append the defined, non-empty params to `path` as a query string. */
export function withQuery(path: string, params: QueryParams | object): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

function authHeaders(token?: string | null, extra?: Record<string, string>) {
  const headers: Record<string, string> = { ...extra };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

/** Every network-level failure surfaces as one ApiError, never a raw TypeError. */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, { credentials: "include", ...init });
  } catch (cause) {
    throwNetworkError(cause);
  }
}

async function readEnvelope<T>(response: Response): Promise<ApiEnvelope<T> | null> {
  try {
    return (await response.json()) as ApiEnvelope<T>;
  } catch {
    return null;
  }
}

/**
 * Unwrap a response the API promised to envelope: a body that is missing,
 * unreadable or flagged as an error becomes an ApiError carrying the status and
 * any field errors.
 */
async function envelopeOrThrow<T>(
  response: Response,
  messages: { failed: string; error: string },
): Promise<ApiEnvelope<T>> {
  const envelope = await readEnvelope<T>(response);

  if (!envelope) {
    throw new ApiError(
      response.ok
        ? "Unexpected response from the server."
        : `${messages.failed} (${response.status}).`,
      response.status,
      null,
    );
  }

  if (!response.ok || envelope.status === "error") {
    throw new ApiError(
      envelope.message || messages.error,
      response.status,
      envelope.errors ?? null,
    );
  }

  return envelope;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiEnvelope<T>> {
  const response = await send(path, {
    method: options.method ?? "GET",
    headers: authHeaders(options.token, { "Content-Type": "application/json" }),
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  return envelopeOrThrow<T>(response, {
    failed: "Request failed",
    error: "Something went wrong. Please try again.",
  });
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

function parseFilename(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(disposition);
  if (star) return decodeURIComponent(star[1].replace(/"/g, "").trim());
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1].trim() : fallback;
}

/**
 * GET an export endpoint that returns either a streamed file (small classes /
 * completed jobs) or a JSON envelope wrapping an ExportJob (large classes still
 * generating). Callers branch on which arm comes back.
 */
export async function requestFileOrJob<J>(
  path: string,
  token?: string | null,
  fallbackName = "download",
): Promise<{ file: DownloadedFile } | { job: J }> {
  const response = await send(path, { method: "GET", headers: authHeaders(token) });

  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    const envelope = await readEnvelope<J>(response);
    if (!envelope || !response.ok || envelope.status === "error") {
      throw new ApiError(
        envelope?.message || `Export failed (${response.status}).`,
        response.status,
        envelope?.errors ?? null,
      );
    }
    return { job: envelope.data as J };
  }

  if (!response.ok) {
    throw new ApiError(`Export failed (${response.status}).`, response.status, null);
  }
  const blob = await response.blob();
  const filename = parseFilename(response.headers.get("Content-Disposition"), fallbackName);
  return { file: { blob, filename } };
}

export function saveBlob(file: DownloadedFile): void {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function apiUpload<T>(
  path: string,
  file: File,
  token?: string | null,
  signal?: AbortSignal,
): Promise<ApiEnvelope<T>> {
  const form = new FormData();
  form.append("file", file);

  const response = await send(path, {
    method: "POST",
    headers: authHeaders(token),
    body: form,
    signal,
  });

  return envelopeOrThrow<T>(response, {
    failed: "Upload failed",
    error: "The import could not be processed.",
  });
}
