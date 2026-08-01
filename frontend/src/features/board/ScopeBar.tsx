import { ScopeSteps } from "../../components/scope";
import type { ScopeStep } from "../../components/scope";
import type { ScopeState } from "./useScope";

export function ScopeBar({
  scope,
  levels,
  lockedFacultyName,
  lockedDepartmentName,
}: {
  scope: ScopeState;
  /** Which levels this board drills through, in order. */
  levels: ReadonlyArray<"faculty" | "department">;
  lockedFacultyName?: string | null;
  lockedDepartmentName?: string | null;
}) {
  const steps: ScopeStep[] = [];

  if (levels.includes("faculty")) {
    steps.push({
      key: "faculty",
      label: "Faculty",
      placeholder: "Select a faculty",
      value: scope.scope.faculty,
      onChange: scope.setFaculty,
      options: scope.faculties.map((f) => ({ value: f.id, label: `${f.code} — ${f.name}` })),
      locked: lockedFacultyName ?? undefined,
    });
  }

  if (levels.includes("department")) {
    steps.push({
      key: "department",
      label: "Department",
      placeholder: "Select a department",
      value: scope.scope.department,
      onChange: scope.setDepartment,
      options: scope.departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` })),
      locked: lockedDepartmentName ?? undefined,
      disabled: levels.includes("faculty") && !scope.scope.faculty,
    });
  }

  steps.push({
    key: "session",
    label: "Session",
    placeholder: "Select a session",
    value: scope.scope.session,
    onChange: scope.setSession,
    options: scope.sessions.map((s) => ({
      value: s.id,
      label: s.is_current ? `${s.name} (current)` : s.name,
    })),
  });

  steps.push({
    key: "semester",
    label: "Semester",
    placeholder: "Select a semester",
    value: scope.scope.semester,
    onChange: scope.setSemester,
    options: scope.semesters.map((s) => ({ value: s.id, label: `${s.name} semester` })),
    disabled: !scope.scope.session,
  });

  return <ScopeSteps steps={steps} loading={scope.loading} />;
}
