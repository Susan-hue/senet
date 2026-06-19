import { createContext } from "react";

export interface AuthContextValue {
  isAuthenticated: boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
