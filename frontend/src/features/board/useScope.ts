import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listDepartments,
  listFaculties,
  listSemesters,
  listSessions,
} from "../../services/accounts";
import type { Department, Faculty, Semester, Session } from "../../types";
import { useAsyncData } from "../admin/useAsyncData";

/**
 * The slice of the hierarchy a board is currently looking at. Every worklist
 * request is scoped by this — an institution has thousands of result sheets, so
 * a board drills to a term (and a department, or a faculty and a department)
 * before any sheet is listed.
 */
export interface Scope {
  faculty: string;
  department: string;
  session: string;
  semester: string;
}

export interface ScopeState {
  scope: Scope;
  faculties: Faculty[];
  /** Departments the actor may drill into — narrowed to the chosen faculty. */
  departments: Department[];
  sessions: Session[];
  /** Semesters of the chosen session only; a semester belongs to one session. */
  semesters: Semester[];
  setFaculty: (id: string) => void;
  setDepartment: (id: string) => void;
  setSession: (id: string) => void;
  setSemester: (id: string) => void;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Loads the academic catalogue and tracks the drill-down selection over it.
 *
 * `fixedFaculty` / `fixedDepartment` pin a level the actor cannot move: a dean
 * is pinned to their faculty, an HOD to their department. Pinning is a UI
 * convenience only — the API scopes every response to the caller's role
 * regardless of what the client asks for.
 */
export function useScope(
  token: string,
  { fixedFaculty = "", fixedDepartment = "" }: { fixedFaculty?: string; fixedDepartment?: string },
): ScopeState {
  const { data, loading, error, reload } = useAsyncData(
    () =>
      Promise.all([
        listFaculties(token),
        listDepartments(token),
        listSessions(token),
        listSemesters(token),
      ]),
    [token],
  );
  const [faculties, allDepartments, sessions, allSemesters] = data ?? [[], [], [], []];

  const [scope, setScope] = useState<Scope>({
    faculty: fixedFaculty,
    department: fixedDepartment,
    session: "",
    semester: "",
  });

  // A pinned level can arrive after first render (the profile resolves async),
  // so adopt it whenever it changes rather than only at mount.
  useEffect(() => {
    setScope((prev) => ({
      ...prev,
      faculty: fixedFaculty || prev.faculty,
      department: fixedDepartment || prev.department,
    }));
  }, [fixedFaculty, fixedDepartment]);

  // Land on the live term. Boards almost always want the session in progress,
  // and an unset term would mean either an empty screen or an unscoped list.
  useEffect(() => {
    if (sessions.length === 0) return;
    setScope((prev) => {
      if (prev.session) return prev;
      const current = sessions.find((s) => s.is_current) ?? sessions[0];
      const now = Date.now();
      const inSession = allSemesters.filter((sem) => sem.session === current.id);
      const semester =
        inSession.find(
          (sem) =>
            new Date(sem.start_date).getTime() <= now && now <= new Date(sem.end_date).getTime(),
        ) ??
        inSession[0] ??
        null;
      return { ...prev, session: current.id, semester: semester?.id ?? "" };
    });
  }, [sessions, allSemesters]);

  const departments = useMemo(() => {
    const faculty = fixedFaculty || scope.faculty;
    if (!faculty) return allDepartments;
    return allDepartments.filter((d) => d.faculty === faculty);
  }, [allDepartments, fixedFaculty, scope.faculty]);

  const semesters = useMemo(
    () => (scope.session ? allSemesters.filter((s) => s.session === scope.session) : []),
    [allSemesters, scope.session],
  );

  const setFaculty = useCallback(
    (id: string) =>
      setScope((prev) => {
        if (id === prev.faculty) return prev;
        // Changing faculty invalidates a department chosen under the old one.
        const kept = allDepartments.find((d) => d.id === prev.department);
        const department = kept && kept.faculty === id ? prev.department : "";
        return { ...prev, faculty: id, department };
      }),
    [allDepartments],
  );

  const setDepartment = useCallback(
    (id: string) => setScope((prev) => ({ ...prev, department: id })),
    [],
  );

  const setSession = useCallback(
    (id: string) =>
      setScope((prev) => {
        if (id === prev.session) return prev;
        const first = allSemesters.find((s) => s.session === id);
        return { ...prev, session: id, semester: first?.id ?? "" };
      }),
    [allSemesters],
  );

  const setSemester = useCallback(
    (id: string) => setScope((prev) => ({ ...prev, semester: id })),
    [],
  );

  return {
    scope,
    faculties,
    departments,
    sessions,
    semesters,
    setFaculty,
    setDepartment,
    setSession,
    setSemester,
    loading,
    error,
    reload,
  };
}
