import { apiRequest } from "./api";
import type { LoginPayload, RegisterData, RegisterPayload, TokenData } from "../types";

const BASE = "/api/v1/auth";

export function register(payload: RegisterPayload) {
  return apiRequest<RegisterData>(`${BASE}/register`, { method: "POST", body: payload });
}

export function login(payload: LoginPayload) {
  return apiRequest<TokenData>(`${BASE}/login`, { method: "POST", body: payload });
}

export function verifyEmail(token: string) {
  return apiRequest<null>(`${BASE}/verify-email?token=${encodeURIComponent(token)}`, {
    method: "GET",
  });
}

export function requestPasswordReset(email: string) {
  return apiRequest<null>(`${BASE}/password-reset`, { method: "POST", body: { email } });
}

export function resetPassword(token: string, password: string) {
  return apiRequest<null>(`${BASE}/password-reset/confirm`, {
    method: "POST",
    body: { token, password },
  });
}

export function refresh() {
  return apiRequest<TokenData>(`${BASE}/token/refresh`, { method: "POST" });
}

export function logout(token: string) {
  return apiRequest<null>(`${BASE}/logout`, { method: "POST", token });
}
