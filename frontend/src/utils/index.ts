export interface JwtPayload {
  user_id?: string | number;
  exp?: number;
  [key: string]: unknown;
}

export function decodeJwt(token: string): JwtPayload | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}
