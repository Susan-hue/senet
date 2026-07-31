import type { ScopeState } from "./useScope";
import styles from "./board.module.css";

interface Step {
  key: "faculty" | "department" | "session" | "semester";
  label: string;
  placeholder: string;
  value: string;
  onChange: (id: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  /** Pinned to the actor's own faculty/department — shown, not editable. */
  locked?: string;
  disabled?: boolean;
}

/**
 * The drill-down that scopes a board. Steps read left to right and narrow as
 * they go: a later step is disabled until the one before it is answered, so a
 * board can never end up asking for every sheet in the institution at once.
 */
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
  const steps: Step[] = [];

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

  return (
    <section className={styles.scopeBar} aria-label="Scope">
      {steps.map((step, index) => (
        <div key={step.key} className={styles.scopeStep}>
          <span className={styles.scopeIndex} aria-hidden="true">
            {index + 1}
          </span>
          <label className={styles.scopeField}>
            <span className={styles.scopeLabel}>{step.label}</span>
            {step.locked ? (
              <span className={styles.scopeLocked} title="Scoped to you — set by your role">
                {step.locked}
              </span>
            ) : (
              <select
                className={styles.scopeSelect}
                value={step.value}
                disabled={step.disabled || scope.loading}
                onChange={(e) => step.onChange(e.target.value)}
              >
                <option value="">{step.placeholder}</option>
                {step.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
          </label>
        </div>
      ))}
    </section>
  );
}
