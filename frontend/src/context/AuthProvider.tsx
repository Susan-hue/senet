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
import { getMe } from "../services/accounts";
import { ApiError } from "../services/api";
import { decodeJwt } from "../utils";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);

  const clear = useCallback(() => {
    tokenRef.current = null;
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const apply = useCallback(
    async (token: string, fallbackEmail: string | null) => {
      tokenRef.current = token;
      setAccessToken(token);

      let nextUser: AuthUser;
      try {
        const me = await getMe(token);
        if (me) {
          nextUser = {
            id: me.id,
            email: me.email ?? fallbackEmail,
            fullName: me.full_name,
            role: me.role,
            institutionName: me.institution_name,
            departmentId: me.department,
            departmentName: me.department_name,
            facultyId: me.faculty,
            facultyName: me.faculty_name,
          };
        } else {
          throw new Error("empty profile");
        }
      } catch (err) {
        // A rejected token means the session is not usable. Falling back to the
        // JWT payload here would sign the user in with no role, which every
        // role-gated screen then reports as "forbidden" instead of "signed out".
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clear();
          throw err;
        }
        // Anything else (offline, a 5xx) is transient: keep the session and fall
        // back to the identity carried in the token itself.
        const payload = decodeJwt(token);
        nextUser = {
          id: payload?.user_id === undefined ? "" : String(payload.user_id),
          email: fallbackEmail,
          fullName: "",
          role: null,
          institutionName: null,
          departmentId: null,
          departmentName: null,
          facultyId: null,
          facultyName: null,
        };
      }

      setUser(nextUser);
      setStatus("authenticated");
    },
    [clear],
  );

  useEffect(() => {
    let active = true;
    refreshRequest()
      .then((res) => {
        if (active && res.data) return apply(res.data.access, null);
        if (active) clear();
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
      await apply(res.data.access, email);
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
