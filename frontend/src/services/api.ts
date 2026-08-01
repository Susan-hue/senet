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

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiEnvelope<T>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.token) headers["Authorization"] = `Bearer ${options.token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      credentials: "include",
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (cause) {
    throwNetworkError(cause);
  }

  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    envelope = null;
  }

  if (!envelope) {
    throw new ApiError(
      response.ok ? "Unexpected response from the server." : `Request failed (${response.status}).`,
      response.status,
      null,
    );
  }

  if (!response.ok || envelope.status === "error") {
    throw new ApiError(
      envelope.message || "Something went wrong. Please try again.",
      response.status,
      envelope.errors ?? null,
    );
  }

  return envelope;
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
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "GET",
      headers,
      credentials: "include",
    });
  } catch (cause) {
    throwNetworkError(cause);
  }

  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    let envelope: ApiEnvelope<J> | null = null;
    try {
      envelope = (await response.json()) as ApiEnvelope<J>;
    } catch {
      envelope = null;
    }
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
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const form = new FormData();
  form.append("file", file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers,
      credentials: "include",
      body: form,
      signal,
    });
  } catch (cause) {
    throwNetworkError(cause);
  }

  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    envelope = null;
  }

  if (!envelope) {
    throw new ApiError(
      response.ok ? "Unexpected response from the server." : `Upload failed (${response.status}).`,
      response.status,
      null,
    );
  }

  if (!response.ok || envelope.status === "error") {
    throw new ApiError(
      envelope.message || "The import could not be processed.",
      response.status,
      envelope.errors ?? null,
    );
  }

  return envelope;
}
