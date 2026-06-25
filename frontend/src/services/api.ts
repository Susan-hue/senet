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
  } catch {
    throw new ApiError("Network error. Check your connection and try again.", 0, null);
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
