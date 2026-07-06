import { useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, Button } from "../../components";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Modal,
  SkeletonTable,
} from "../../components/admin";
import { ApiError } from "../../services/api";
import {
  createCourse,
  deleteCourse,
  listCourses,
  listDepartments,
  listFaculties,
  updateCourse,
} from "../../services/accounts";
import { LEVEL_OPTIONS } from "../../types";
import type { Course, Department } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncData, useDebounced } from "./useAsyncData";
import { PageHeader, Pager, SearchBox, SelectInput, TextInput, firstError } from "./ui";
import { PlusIcon } from "./adminIcons";
import styles from "./admin.module.css";

const PAGE_SIZE = 25;

export function CoursesPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();

  const [query, setQuery] = useState("");
  const [facultyFilter, setFacultyFilter] = useState("");
  const [deptFilter, setDeptFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(query.trim());

  const refData = useAsyncData(
    () => Promise.all([listFaculties(token), listDepartments(token)]),
    [token],
  );
  const [faculties, departments] = refData.data ?? [[], []];

  const { data, loading, error, reload } = useAsyncData(
    () =>
      listCourses(token, {
        page,
        page_size: PAGE_SIZE,
        faculty: facultyFilter,
        department: deptFilter,
        level: levelFilter,
        search,
      }),
    [token, page, facultyFilter, deptFilter, levelFilter, search],
  );
  const courses = data?.results ?? [];
  const hasFilters = Boolean(search || facultyFilter || deptFilter || levelFilter);

  const deptMap = useMemo(() => {
    const m = new Map<string, Department>();
    departments.forEach((d) => m.set(d.id, d));
    return m;
  }, [departments]);

  const deptOptions = useMemo(
    () => departments.filter((d) => !facultyFilter || d.faculty === facultyFilter),
    [departments, facultyFilter],
  );

  const [editing, setEditing] = useState<Course | "new" | null>(
    (location.state as { create?: boolean } | null)?.create ? "new" : null,
  );
  const [toDelete, setToDelete] = useState<Course | null>(null);

  function pickFaculty(id: string) {
    setFacultyFilter(id);
    if (id && deptFilter && deptMap.get(deptFilter)?.faculty !== id) setDeptFilter("");
    setPage(1);
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Courses"
        subtitle={
          data
            ? `${data.count.toLocaleString()} course${data.count === 1 ? "" : "s"}${hasFilters ? " in this view" : " across all departments"}.`
            : "The course catalogue, one page at a time."
        }
        actions={
          <Button onClick={() => setEditing("new")}>
            <PlusIcon size={16} /> Add course
          </Button>
        }
      />

      <div className={styles.toolbar}>
        <SearchBox
          value={query}
          onChange={(v) => {
            setQuery(v);
            setPage(1);
          }}
          placeholder="Search by code or title…"
        />
        <select
          className={styles.filter}
          value={facultyFilter}
          onChange={(e) => pickFaculty(e.target.value)}
          aria-label="Filter by faculty"
        >
          <option value="">All faculties</option>
          {faculties.map((f) => (
            <option key={f.id} value={f.id}>
              {f.code} — {f.name}
            </option>
          ))}
        </select>
        <select
          className={styles.filter}
          value={deptFilter}
          onChange={(e) => {
            setDeptFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by department"
        >
          <option value="">All departments</option>
          {deptOptions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} — {d.name}
            </option>
          ))}
        </select>
        <select
          className={styles.filter}
          value={levelFilter}
          onChange={(e) => {
            setLevelFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by level"
        >
          <option value="">All levels</option>
          {LEVEL_OPTIONS.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      <div className={styles.panel}>
        {loading ? (
          <SkeletonTable rows={6} cols={6} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : courses.length === 0 ? (
          <EmptyState
            title={hasFilters ? "No matching courses" : "No courses yet"}
            hint={
              hasFilters
                ? "Try a different search, or clear the faculty, department or level filters."
                : "Add a course or bulk-import your catalogue to get started."
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
          departments={departments}
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
  departments,
  token,
  onClose,
  onSaved,
}: {
  course: Course | null;
  departments: Department[];
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = course !== null;
  const [department, setDepartment] = useState(course?.department ?? "");
  const [code, setCode] = useState(course?.code ?? "");
  const [title, setTitle] = useState(course?.title ?? "");
  const [units, setUnits] = useState(course ? String(course.credit_units) : "");
  const [level, setLevel] = useState(course?.level ? String(course.level) : "");
  const [ca, setCa] = useState(course?.ca_weight != null ? String(course.ca_weight) : "");
  const [exam, setExam] = useState(course?.exam_weight != null ? String(course.exam_weight) : "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);

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
        <SelectInput
          label="Department"
          required
          value={department}
          onChange={setDepartment}
          placeholder="Select a department"
          options={departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
          error={firstError(errors, "department")}
        />
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
