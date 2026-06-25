import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AuthContext } from "./AuthContext";
import type { AuthStatus } from "./AuthContext";
import type { AuthUser } from "../types";
import {
  login as loginRequest,
  logout as logoutRequest,
  refresh as refreshRequest,
} from "../services/auth";
import { decodeJwt } from "../utils";

function userFromToken(token: string, email: string | null): AuthUser {
  const payload = decodeJwt(token);
  const rawId = payload?.user_id;
  return { id: rawId === undefined ? "" : String(rawId), email };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);

  const apply = useCallback((token: string, email: string | null) => {
    tokenRef.current = token;
    setAccessToken(token);
    setUser(userFromToken(token, email));
    setStatus("authenticated");
  }, []);

  const clear = useCallback(() => {
    tokenRef.current = null;
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  useEffect(() => {
    let active = true;
    refreshRequest()
      .then((res) => {
        if (active && res.data) apply(res.data.access, null);
        else if (active) clear();
      })
      .catch(() => {
        if (active) clear();
      });
    return () => {
      active = false;
    };
  }, [apply, clear]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await loginRequest({ email, password });
      if (!res.data) throw new Error("No access token was returned.");
      apply(res.data.access, email);
    },
    [apply],
  );

  const logout = useCallback(async () => {
    if (tokenRef.current) await logoutRequest(tokenRef.current).catch(() => undefined);
    clear();
  }, [clear]);

  const value = useMemo(
    () => ({ status, user, accessToken, login, logout }),
    [status, user, accessToken, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
