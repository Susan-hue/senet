import { useMemo, useState } from "react";
import { Alert, Button } from "../../components";
import { ConfirmDialog, EmptyState, ErrorState, SkeletonTable } from "../../components/admin";
import { ApiError } from "../../services/api";
import {
  createAssignment,
  deleteAssignment,
  listAssignments,
  listCourses,
  listSemesters,
  listSessions,
  listUsers,
} from "../../services/accounts";
import type { CourseAssignment } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncData } from "./useAsyncData";
import { PageHeader, SelectInput } from "./ui";
import styles from "./admin.module.css";

export function AssignmentsPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";

  const { data, loading, error, reload } = useAsyncData(
    () =>
      Promise.all([
        listAssignments(token),
        listUsers(token),
        listCourses(token),
        listSessions(token),
        listSemesters(token),
      ]),
    [token],
  );
  const [assignments, users, courses, sessions, semesters] = data ?? [[], [], [], [], []];

  const lecturers = users.filter((u) => u.role === "lecturer");
  const lecturerMap = useMemo(() => mapBy(lecturers, (l) => l.id), [lecturers]);
  const courseMap = useMemo(() => mapBy(courses, (c) => c.id), [courses]);
  const sessionMap = useMemo(() => mapBy(sessions, (s) => s.id), [sessions]);
  const semesterMap = useMemo(() => mapBy(semesters, (s) => s.id), [semesters]);

  const [lecturer, setLecturer] = useState("");
  const [course, setCourse] = useState("");
  const [term, setTerm] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [toRemove, setToRemove] = useState<CourseAssignment | null>(null);

  const termOptions = semesters.map((sem) => ({
    value: sem.id,
    label: `${sessionMap.get(sem.session)?.name ?? "?"} · ${sem.name}`,
  }));

  async function assign() {
    setFormError(null);
    const semester = semesterMap.get(term);
    if (!lecturer || !course || !semester) {
      setFormError("Select a lecturer, course and term.");
      return;
    }
    setSaving(true);
    try {
      await createAssignment(
        { lecturer, course, session: semester.session, semester: semester.id },
        token,
      );
      setLecturer("");
      setCourse("");
      setTerm("");
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the assignment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Lecturer assignments"
        subtitle="Assign lecturers to courses for a session and semester."
      />

      <section className={[styles.panel, styles.panelAccent].join(" ")}>
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle}>New assignment</h2>
        </div>
        <div className={styles.inlineForm}>
          <div className={styles.inlineField}>
            <SelectInput
              label="Lecturer"
              value={lecturer}
              onChange={setLecturer}
              placeholder="Select lecturer"
              options={lecturers.map((l) => ({ value: l.id, label: l.full_name }))}
            />
          </div>
          <div className={styles.inlineField}>
            <SelectInput
              label="Course"
              value={course}
              onChange={setCourse}
              placeholder="Select course"
              options={courses.map((c) => ({ value: c.id, label: `${c.code} — ${c.title}` }))}
            />
          </div>
          <div className={styles.inlineField}>
            <SelectInput
              label="Term"
              value={term}
              onChange={setTerm}
              placeholder="Session · semester"
              options={termOptions}
            />
          </div>
          <Button loading={saving} onClick={assign}>
            Assign
          </Button>
        </div>
        {formError ? (
          <div style={{ padding: "0 18px 18px" }}>
            <Alert variant="error">{formError}</Alert>
          </div>
        ) : null}
      </section>

      <div className={styles.panel}>
        {loading ? (
          <SkeletonTable rows={5} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : assignments.length === 0 ? (
          <EmptyState
            title="No assignments yet"
            hint="Use the form above, or bulk-import lecturer assignments."
          />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Lecturer</th>
                  <th>Course</th>
                  <th>Session</th>
                  <th>Semester</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {assignments.map((a) => {
                  const c = courseMap.get(a.course);
                  return (
                    <tr key={a.id}>
                      <td className={styles.cellStrong}>
                        {lecturerMap.get(a.lecturer)?.full_name ?? "—"}
                      </td>
                      <td>
                        {c ? (
                          <>
                            <span className={styles.mono} style={{ color: "var(--accent-eyebrow)" }}>
                              {c.code}
                            </span>{" "}
                            <span className={styles.cellMuted}>{c.title}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className={styles.cellMuted}>{sessionMap.get(a.session)?.name ?? "—"}</td>
                      <td className={styles.cellMuted}>
                        {semesterMap.get(a.semester)?.name ?? "—"}
                      </td>
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            type="button"
                            className={[styles.textBtn, styles.textDanger].join(" ")}
                            onClick={() => setToRemove(a)}
                          >
                            Unassign
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {toRemove ? (
        <UnassignDialog
          assignment={toRemove}
          lecturerName={lecturerMap.get(toRemove.lecturer)?.full_name ?? "this lecturer"}
          courseCode={courseMap.get(toRemove.course)?.code ?? "the course"}
          token={token}
          onClose={() => setToRemove(null)}
          onDone={() => {
            setToRemove(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

function mapBy<T>(items: T[], key: (item: T) => string) {
  const m = new Map<string, T>();
  items.forEach((i) => m.set(key(i), i));
  return m;
}

function UnassignDialog({
  assignment,
  lecturerName,
  courseCode,
  token,
  onClose,
  onDone,
}: {
  assignment: CourseAssignment;
  lecturerName: string;
  courseCode: string;
  token: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function confirm() {
    setLoading(true);
    setError(null);
    try {
      await deleteAssignment(assignment.id, token);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove the assignment.");
      setLoading(false);
    }
  }
  return (
    <ConfirmDialog
      title="Remove assignment"
      message={`Unassign ${lecturerName} from ${courseCode}?`}
      confirmLabel="Unassign"
      loading={loading}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
    />
  );
}
