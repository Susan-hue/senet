import { useEffect, useMemo, useState } from "react";
import { Alert, Button } from "../../components";
import { ConfirmDialog, EmptyState, ErrorState, SkeletonTable } from "../../components/admin";
import { RemotePicker, ScopeGate, ScopeSteps } from "../../components/scope";
import type { PickerOption, ScopeStep } from "../../components/scope";
import { ApiError } from "../../services/api";
import {
  createAssignment,
  deleteAssignment,
  listAssignments,
  listCourses,
  listDepartments,
  listFaculties,
  listSemesters,
  listSessions,
  listUsers,
} from "../../services/accounts";
import { LEVEL_OPTIONS } from "../../types";
import type { CourseAssignment, Faculty } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncAction, useAsyncData, useDebounced } from "./useAsyncData";
import { useFacultyDepartmentFilter } from "./useDirectoryFilters";
import { PageHeader, Pager, SearchBox, SelectInput } from "./ui";
import styles from "./admin.module.css";

const PAGE_SIZE = 25;
const PICKER_SIZE = 20;
const STAGES = ["Faculty", "Department", "Term"];

export function AssignmentsPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";

  const [term, setTerm] = useState("");

  const refData = useAsyncData(
    () =>
      Promise.all([
        listFaculties(token),
        listDepartments(token),
        listSessions(token),
        listSemesters(token),
      ]),
    [token],
  );
  const [faculties, departments, sessions, semesters] = refData.data ?? [[], [], [], []];

  const {
    faculty,
    department,
    setDepartment,
    departmentsById: deptMap,
    departmentOptions: deptOptions,
    pickFaculty,
  } = useFacultyDepartmentFilter(departments);

  const sessionMap = useMemo(() => {
    const m = new Map<string, string>();
    sessions.forEach((s) => m.set(s.id, s.name));
    return m;
  }, [sessions]);

  const termOptions = useMemo(
    () =>
      semesters.map((sem) => ({
        value: sem.id,
        label: `${sessionMap.get(sem.session) ?? "?"} · ${sem.name} semester`,
      })),
    [semesters, sessionMap],
  );
  const semester = semesters.find((s) => s.id === term) ?? null;

  const scoped = Boolean(faculty && department && semester);
  const doneCount = faculty ? (department ? (term ? 3 : 2) : 1) : 0;

  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(query.trim());
  useEffect(() => setPage(1), [faculty, department, term, search]);

  const { data, loading, error, reload } = useAsyncData(
    () =>
      scoped
        ? listAssignments(token, {
            page,
            page_size: PAGE_SIZE,
            faculty,
            department,
            session: semester?.session ?? "",
            semester: semester?.id ?? "",
            search,
          })
        : Promise.resolve(null),
    [token, scoped, page, faculty, department, semester?.id, search],
  );
  const assignments = data?.results ?? [];

  const [toRemove, setToRemove] = useState<CourseAssignment | null>(null);

  const facultyName = faculties.find((f: Faculty) => f.id === faculty)?.name ?? "";
  const departmentName = deptMap.get(department)?.name ?? "";
  const termLabel = termOptions.find((t) => t.value === term)?.label ?? "";

  const steps: ScopeStep[] = [
    {
      key: "faculty",
      label: "Faculty",
      placeholder: "Select a faculty",
      value: faculty,
      onChange: pickFaculty,
      options: faculties.map((f: Faculty) => ({ value: f.id, label: `${f.code} — ${f.name}` })),
    },
    {
      key: "department",
      label: "Department",
      placeholder: faculty ? "Select a department" : "Pick a faculty first",
      value: department,
      onChange: setDepartment,
      options: deptOptions.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` })),
      disabled: !faculty,
    },
    {
      key: "term",
      label: "Session · semester",
      placeholder: department ? "Select a term" : "Pick a department first",
      value: term,
      onChange: setTerm,
      options: termOptions,
      disabled: !department,
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        title="Lecturer assignments"
        subtitle={
          scoped && data
            ? `${data.count.toLocaleString()} assignment${data.count === 1 ? "" : "s"} in ${departmentName || "this department"} · ${termLabel}.`
            : "Drill to a faculty, a department and a term to assign lecturers."
        }
      />

      {refData.error ? (
        <ErrorState message={refData.error} onRetry={refData.reload} />
      ) : (
        <ScopeSteps steps={steps} loading={refData.loading} ariaLabel="Assignment scope" />
      )}

      {scoped && semester ? (
        <NewAssignment
          token={token}
          faculty={faculty}
          department={department}
          departmentName={departmentName}
          session={semester.session}
          semester={semester.id}
          onCreated={reload}
        />
      ) : null}

      {scoped ? (
        <div className={styles.toolbar}>
          <SearchBox
            value={query}
            onChange={setQuery}
            placeholder="Search these assignments by course or lecturer…"
          />
        </div>
      ) : null}

      <div className={styles.panel}>
        {!scoped ? (
          <ScopeGate
            stages={STAGES}
            doneCount={doneCount}
            title={
              !faculty
                ? "Select a faculty to begin"
                : !department
                  ? `Now select a department in ${facultyName || "this faculty"}`
                  : "Now select a session and semester"
            }
            hint={
              !faculty
                ? "Assignments are held per lecturer, per course, per term. Narrow to one faculty first."
                : !department
                  ? "Departments in the faculty you picked are listed above."
                  : "An assignment only means something inside a term, so pick the session and semester you are staffing."
            }
          />
        ) : loading ? (
          <SkeletonTable rows={5} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : assignments.length === 0 ? (
          <EmptyState
            title={
              search
                ? `No assignments match “${search}”`
                : `Nothing assigned in ${departmentName || "this department"} yet`
            }
            hint={
              search
                ? "Search only looks inside the department and term you selected."
                : "Use the form above to assign a lecturer, or bulk-import assignments."
            }
          />
        ) : (
          <>
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
                  {assignments.map((a) => (
                    <tr key={a.id}>
                      <td className={styles.cellStrong}>{a.lecturer_name}</td>
                      <td>
                        <span className={styles.mono} style={{ color: "var(--accent-eyebrow)" }}>
                          {a.course_code}
                        </span>{" "}
                        <span className={styles.cellMuted}>{a.course_title}</span>
                      </td>
                      <td className={styles.cellMuted}>{sessionMap.get(a.session) ?? "—"}</td>
                      <td className={styles.cellMuted}>
                        {semesters.find((s) => s.id === a.semester)?.name ?? "—"}
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
                  ))}
                </tbody>
              </table>
            </div>
            {data ? (
              <Pager
                page={data.page}
                totalPages={data.total_pages}
                count={data.count}
                label="assignments"
                onPage={setPage}
              />
            ) : null}
          </>
        )}
      </div>

      {toRemove ? (
        <UnassignDialog
          assignment={toRemove}
          lecturerName={toRemove.lecturer_name || "this lecturer"}
          courseCode={toRemove.course_code || "the course"}
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

function NewAssignment({
  token,
  faculty,
  department,
  departmentName,
  session,
  semester,
  onCreated,
}: {
  token: string;
  faculty: string;
  department: string;
  departmentName: string;
  session: string;
  semester: string;
  onCreated: () => void;
}) {
  const [lecturer, setLecturer] = useState<PickerOption | null>(null);
  const [level, setLevel] = useState("");
  const [course, setCourse] = useState<PickerOption | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    setLecturer(null);
    setCourse(null);
    setLevel("");
  }, [faculty, department, semester]);

  useEffect(() => setCourse(null), [level]);

  async function assign() {
    setFormError(null);
    if (!lecturer || !course) {
      setFormError("Pick a lecturer and a course.");
      return;
    }
    setSaving(true);
    try {
      await createAssignment(
        { lecturer: lecturer.value, course: course.value, session, semester },
        token,
      );
      setLecturer(null);
      setCourse(null);
      onCreated();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the assignment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className={[styles.panel, styles.panelAccent].join(" ")}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>New assignment</h2>
        <span className={styles.cellMuted}>
          {departmentName || "This department"}, this term only
        </span>
      </div>
      <div className={styles.inlineForm}>
        <div className={styles.inlineField}>
          <span className={styles.fieldLabel}>Lecturer</span>
          <RemotePicker
            value={lecturer?.value ?? ""}
            valueLabel={lecturer?.label ?? ""}
            placeholder="Search lecturers in this department"
            ariaLabel="Lecturer"
            scopeKey={`${faculty}:${department}`}
            emptyText={`No lecturers in ${departmentName || "this department"}.`}
            fetchOptions={async (search) => {
              const page = await listUsers(token, {
                role: "lecturer",
                is_active: true,
                faculty,
                department,
                search,
                page_size: PICKER_SIZE,
              });
              return {
                count: page.count,
                options: page.results.map((p) => ({
                  value: p.id,
                  label: p.full_name,
                  hint: p.rank ?? undefined,
                })),
              };
            }}
            onPick={setLecturer}
          />
        </div>
        <div className={styles.inlineField}>
          <SelectInput
            label="Level"
            value={level}
            onChange={setLevel}
            placeholder="All levels"
            options={LEVEL_OPTIONS.map((l) => ({ value: l.value, label: l.label }))}
          />
        </div>
        <div className={styles.inlineField}>
          <span className={styles.fieldLabel}>Course</span>
          <RemotePicker
            value={course?.value ?? ""}
            valueLabel={course?.label ?? ""}
            placeholder="Search courses in this department"
            ariaLabel="Course"
            scopeKey={`${department}:${level}`}
            emptyText={
              level
                ? `No ${level} level courses in ${departmentName || "this department"}.`
                : `No courses in ${departmentName || "this department"}.`
            }
            fetchOptions={async (search) => {
              const page = await listCourses(token, {
                department,
                level,
                search,
                page_size: PICKER_SIZE,
              });
              return {
                count: page.count,
                options: page.results.map((c) => ({
                  value: c.id,
                  label: `${c.code} — ${c.title}`,
                  hint: c.level ? `${c.level}L` : undefined,
                })),
              };
            }}
            onPick={setCourse}
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
  );
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
  const remove = useAsyncAction("Could not remove the assignment.");
  return (
    <ConfirmDialog
      title="Remove assignment"
      message={`Unassign ${lecturerName} from ${courseCode}?`}
      confirmLabel="Unassign"
      loading={remove.pending}
      error={remove.message}
      onCancel={onClose}
      onConfirm={() =>
        void remove.run(async () => {
          await deleteAssignment(assignment.id, token);
          onDone();
        })
      }
    />
  );
}
