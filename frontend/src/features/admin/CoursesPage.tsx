import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, Button } from "../../components";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Modal,
  SkeletonTable,
} from "../../components/admin";
import { ScopeGate, ScopeSteps } from "../../components/scope";
import type { ScopeStep } from "../../components/scope";
import { ApiError } from "../../services/api";
import {
  createCourse,
  deleteCourse,
  listCourses,
  listDepartments,
  listFaculties,
  listSemesters,
  listSessions,
  updateCourse,
} from "../../services/accounts";
import { LEVEL_OPTIONS } from "../../types";
import type { Course, Department, Faculty } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncData, useDebounced } from "./useAsyncData";
import { PageHeader, Pager, SearchBox, SelectInput, TextInput, firstError } from "./ui";
import { PlusIcon } from "./adminIcons";
import styles from "./admin.module.css";

const PAGE_SIZE = 25;
const STAGES = ["Faculty", "Department", "Level"];

export function CoursesPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();

  const [faculty, setFaculty] = useState("");
  const [department, setDepartment] = useState("");
  const [level, setLevel] = useState("");
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(query.trim());

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

  const deptMap = useMemo(() => {
    const m = new Map<string, Department>();
    departments.forEach((d) => m.set(d.id, d));
    return m;
  }, [departments]);

  const deptOptions = useMemo(
    () => departments.filter((d) => d.faculty === faculty),
    [departments, faculty],
  );

  const sessionMap = useMemo(() => {
    const m = new Map<string, string>();
    sessions.forEach((s) => m.set(s.id, s.name));
    return m;
  }, [sessions]);

  const termOptions = useMemo(
    () =>
      semesters.map((sem) => ({
        value: sem.id,
        label: `${sessionMap.get(sem.session) ?? "?"} · ${sem.name}`,
      })),
    [semesters, sessionMap],
  );
  const selectedTerm = semesters.find((s) => s.id === term) ?? null;

  const scoped = Boolean(faculty && department && level);
  const doneCount = faculty ? (department ? (level ? 3 : 2) : 1) : 0;

  useEffect(() => setPage(1), [faculty, department, level, term, search]);

  const { data, loading, error, reload } = useAsyncData(
    () =>
      scoped
        ? listCourses(token, {
            page,
            page_size: PAGE_SIZE,
            faculty,
            department,
            level,
            session: selectedTerm?.session ?? "",
            semester: selectedTerm?.id ?? "",
            search,
          })
        : Promise.resolve(null),
    [token, scoped, page, faculty, department, level, selectedTerm?.id, search],
  );
  const courses = data?.results ?? [];

  const [editing, setEditing] = useState<Course | "new" | null>(
    (location.state as { create?: boolean } | null)?.create ? "new" : null,
  );
  const [toDelete, setToDelete] = useState<Course | null>(null);

  function pickFaculty(id: string) {
    setFaculty(id);
    if (department && deptMap.get(department)?.faculty !== id) setDepartment("");
  }

  const facultyName = faculties.find((f: Faculty) => f.id === faculty)?.name ?? "";
  const departmentName = deptMap.get(department)?.name ?? "";

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
      key: "level",
      label: "Level",
      placeholder: department ? "Select a level" : "Pick a department first",
      value: level,
      onChange: setLevel,
      options: LEVEL_OPTIONS.map((l) => ({ value: l.value, label: l.label })),
      disabled: !department,
    },
    {
      key: "term",
      label: "Term",
      placeholder: "Any term",
      value: term,
      onChange: setTerm,
      options: termOptions,
      disabled: !level,
      hint: "Optional — narrows to courses taught that semester.",
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        title="Courses"
        subtitle={
          scoped && data
            ? `${data.count.toLocaleString()} ${level} level course${data.count === 1 ? "" : "s"} in ${departmentName || "this department"}.`
            : "Drill to a faculty, a department and a level to list courses."
        }
        actions={
          <Button onClick={() => setEditing("new")}>
            <PlusIcon size={16} /> Add course
          </Button>
        }
      />

      {refData.error ? (
        <ErrorState message={refData.error} onRetry={refData.reload} />
      ) : (
        <ScopeSteps steps={steps} loading={refData.loading} ariaLabel="Catalogue scope" />
      )}

      {scoped ? (
        <div className={styles.toolbar}>
          <SearchBox
            value={query}
            onChange={setQuery}
            placeholder={`Search ${level} level courses in ${departmentName || "this department"} by code or title…`}
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
                  : "Now select a level"
            }
            hint={
              !faculty
                ? "The catalogue covers every department in the university. Narrow it to one faculty first."
                : !department
                  ? "Departments in the faculty you picked are listed above."
                  : `Pick the level you want — 100 through 600 — and only ${departmentName || "this department"}'s courses at that level are listed.`
            }
          />
        ) : loading ? (
          <SkeletonTable rows={6} cols={6} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : courses.length === 0 ? (
          <EmptyState
            title={
              search
                ? `No courses match “${search}”`
                : term
                  ? "No courses taught in this term"
                  : `No ${level} level courses in ${departmentName || "this department"}`
            }
            hint={
              search
                ? "Search only looks inside the department and level you selected. Clear it, or widen the scope above."
                : term
                  ? "Nothing at this level has a lecturer assigned for that semester. Clear the term to see the whole level."
                  : "Add a course to this department, or bulk-import your catalogue."
            }
          />
        ) : (
          <>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Title</th>
                    <th>Units</th>
                    <th>Level</th>
                    <th>Department</th>
                    <th>CA / Exam</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {courses.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <span
                          className={[styles.mono, styles.cellStrong].join(" ")}
                          style={{ color: "var(--accent-eyebrow)" }}
                        >
                          {c.code}
                        </span>
                      </td>
                      <td className={styles.cellStrong}>{c.title}</td>
                      <td>{c.credit_units}</td>
                      <td>{c.level ?? "—"}</td>
                      <td className={styles.cellMuted}>{deptMap.get(c.department)?.code ?? "—"}</td>
                      <td className={styles.cellMuted}>
                        {c.effective_ca_weight} / {c.effective_exam_weight}
                      </td>
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            type="button"
                            className={styles.textBtn}
                            onClick={() => setEditing(c)}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className={[styles.textBtn, styles.textDanger].join(" ")}
                            onClick={() => setToDelete(c)}
                          >
                            Delete
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
                label="courses"
                onPage={setPage}
              />
            ) : null}
          </>
        )}
      </div>

      {editing ? (
        <CourseModal
          course={editing === "new" ? null : editing}
          faculties={faculties}
          departments={departments}
          defaults={{ faculty, department, level }}
          token={token}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      ) : null}

      {toDelete ? (
        <DeleteCourse
          course={toDelete}
          token={token}
          onClose={() => setToDelete(null)}
          onDeleted={() => {
            setToDelete(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

function CourseModal({
  course,
  faculties,
  departments,
  defaults,
  token,
  onClose,
  onSaved,
}: {
  course: Course | null;
  faculties: Faculty[];
  departments: Department[];
  defaults: { faculty: string; department: string; level: string };
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = course !== null;
  const departmentOf = (id: string) => departments.find((d) => d.id === id) ?? null;

  const [faculty, setFaculty] = useState(
    course ? (departmentOf(course.department)?.faculty ?? "") : defaults.faculty,
  );
  const [department, setDepartment] = useState(course?.department ?? defaults.department);
  const [code, setCode] = useState(course?.code ?? "");
  const [title, setTitle] = useState(course?.title ?? "");
  const [units, setUnits] = useState(course ? String(course.credit_units) : "");
  const [level, setLevel] = useState(
    course?.level ? String(course.level) : isEdit ? "" : defaults.level,
  );
  const [ca, setCa] = useState(course?.ca_weight != null ? String(course.ca_weight) : "");
  const [exam, setExam] = useState(course?.exam_weight != null ? String(course.exam_weight) : "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);

  const deptOptions = departments.filter((d) => !faculty || d.faculty === faculty);

  async function submit() {
    setSaving(true);
    setMessage(null);
    setErrors(null);
    const body: Partial<Course> = {
      department,
      code: code.trim(),
      title: title.trim(),
      credit_units: Number(units),
      level: level ? Number(level) : null,
      ca_weight: ca && exam ? Number(ca) : null,
      exam_weight: ca && exam ? Number(exam) : null,
    };
    try {
      if (isEdit && course) await updateCourse(course.id, body, token);
      else await createCourse(body, token);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        setMessage(err.message);
        setErrors(err.fieldErrors);
      } else {
        setMessage("Could not save the course.");
      }
      setSaving(false);
    }
  }

  return (
    <Modal
      title={isEdit ? `Edit ${course.code}` : "Add course"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={saving} onClick={submit}>
            {isEdit ? "Save changes" : "Create course"}
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        {message ? (
          <div className={styles.formError}>
            <Alert variant="error">{message}</Alert>
          </div>
        ) : null}
        <div className={styles.formGrid}>
          <SelectInput
            label="Faculty"
            required
            value={faculty}
            onChange={(v) => {
              setFaculty(v);
              if (departmentOf(department)?.faculty !== v) setDepartment("");
            }}
            placeholder="Select a faculty"
            options={faculties.map((f) => ({ value: f.id, label: `${f.code} — ${f.name}` }))}
          />
          <SelectInput
            label="Department"
            required
            value={department}
            onChange={setDepartment}
            placeholder={faculty ? "Select a department" : "Pick a faculty first"}
            options={deptOptions.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
            error={firstError(errors, "department")}
          />
        </div>
        <div className={styles.formGrid}>
          <TextInput
            label="Course code"
            required
            value={code}
            onChange={setCode}
            placeholder="MTH 101"
            error={firstError(errors, "code")}
          />
          <SelectInput
            label="Level"
            value={level}
            onChange={setLevel}
            placeholder="Select level"
            options={LEVEL_OPTIONS.map((l) => ({ value: l.value, label: l.label }))}
            error={firstError(errors, "level")}
          />
        </div>
        <TextInput
          label="Title"
          required
          value={title}
          onChange={setTitle}
          placeholder="Introduction to Programming"
          error={firstError(errors, "title")}
        />
        <div className={styles.formGrid}>
          <TextInput
            label="Credit units"
            required
            type="number"
            value={units}
            onChange={setUnits}
            placeholder="3"
            error={firstError(errors, "credit_units")}
          />
          <div />
          <TextInput
            label="CA weight"
            type="number"
            value={ca}
            onChange={setCa}
            placeholder="Optional"
            error={firstError(errors, "ca_weight")}
          />
          <TextInput
            label="Exam weight"
            type="number"
            value={exam}
            onChange={setExam}
            placeholder="Optional"
            error={firstError(errors, "exam_weight")}
          />
        </div>
      </div>
    </Modal>
  );
}

function DeleteCourse({
  course,
  token,
  onClose,
  onDeleted,
}: {
  course: Course;
  token: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function confirm() {
    setLoading(true);
    setError(null);
    try {
      await deleteCourse(course.id, token);
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the course.");
      setLoading(false);
    }
  }
  return (
    <ConfirmDialog
      title="Delete course"
      message={`Delete ${course.code} — ${course.title}? This cannot be undone.`}
      loading={loading}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
    />
  );
}
