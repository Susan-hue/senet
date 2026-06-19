import { createContext } from "react";

export type Role = "admin" | "teacher" | "student";

export interface RoleContextValue {
  role: Role | null;
}

export const RoleContext = createContext<RoleContextValue | null>(null);
