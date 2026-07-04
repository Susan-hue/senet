import { useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, Button } from "../../components";
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Modal,
  SkeletonTable,
} from "../../components/admin";
import { ApiError } from "../../services/api";
import * as api from "../../services/accounts";
import type { Department, Faculty, Programme, Semester, Session } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncData } from "./useAsyncData";
import { PageHeader, TextInput, firstError } from "./ui";
import { PlusIcon } from "./adminIcons";
import styles from "./admin.module.css";
import s from "./structure.module.css";

type EntityKind = "faculty" | "department" | "programme" | "session" | "semester";

interface ModalSpec {
  kind: EntityKind;
  facultyId?: string;
  departmentId?: string;
  sessionId?: string;
  entity?: Faculty | Department | Programme | Session | Semester;
}

interface DeleteSpec {
  title: string;
  message: string;
  run: (token: string) => Promise<unknown>;
}

const md = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const mdy = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });

function d(value: string) {
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? null : dt;
}
function shortRange(a: string, b: string) {
  const da = d(a);
  const db = d(b);
  return `${da ? md.format(da) : a} – ${db ? md.format(db) : b}`;
}
function fullRange(a: string, b: string) {
  const da = d(a);
  const db = d(b);
  return `${da ? mdy.format(da) : a} — ${db ? mdy.format(db) : b}`;
}
function semesterStatus(sem: Semester): { label: string; active: boolean } {
  const now = new Date();
  const start = d(sem.start_date);
  const end = d(sem.end_date);
  if (end && end < now) return { label: "Completed", active: false };
  if (start && start > now) return { label: "Upcoming", active: false };
  return { label: "In progress", active: true };
}

function Chevron() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

export function AcademicStructurePage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();

  const { data, loading, error, reload } = useAsyncData(
    () =>
      Promise.all([
        api.listFaculties(token),
        api.listDepartments(token),
        api.listProgrammes(token),
        api.listSessions(token),
        api.listSemesters(token),
      ]),
    [token],
  );
  const [faculties, departments, programmes, sessions, semesters] = data ?? [[], [], [], [], []];

  const deptsByFaculty = useMemo(() => groupBy(departments, (x) => x.faculty), [departments]);
  const progsByDept = useMemo(() => groupBy(programmes, (x) => x.department), [programmes]);
  const semsBySession = useMemo(() => groupBy(semesters, (x) => x.session), [semesters]);

  const [openF, setOpenF] = useState<Set<string>>(new Set());
  const [openD, setOpenD] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<ModalSpec | null>(
    (location.state as { create?: boolean } | null)?.create ? { kind: "session" } : null,
  );
  const [del, setDel] = useState<DeleteSpec | null>(null);

  function toggle(set: Set<string>, id: string, setter: (s: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Academic structure"
        subtitle="Faculties, departments and programmes, plus your academic calendar."
        actions={
          <Button onClick={() => setModal({ kind: "faculty" })}>
            <PlusIcon size={16} /> Add faculty
          </Button>
        }
      />

      {loading ? (
        <div className={styles.panel}>
          <SkeletonTable rows={5} cols={3} />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        <div className={s.cols}>
          {/* Faculties */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>Faculties</h2>
            </div>
            {faculties.length === 0 ? (
              <EmptyState
                title="No faculties yet"
                hint="Add your first faculty to start building the academic structure."
              />
            ) : (
              faculties.map((f) => {
                const depts = deptsByFaculty.get(f.id) ?? [];
                const progCount = depts.reduce(
                  (n, dep) => n + (progsByDept.get(dep.id)?.length ?? 0),
                  0,
                );
                const isOpen = openF.has(f.id);
                return (
                  <div key={f.id}>
                    <div className={s.accRow}>
                      <button
                        type="button"
                        className={[s.chev, isOpen ? s.chevOpen : ""].join(" ")}
                        onClick={() => toggle(openF, f.id, setOpenF)}
                        aria-label={isOpen ? "Collapse" : "Expand"}
                        aria-expanded={isOpen}
                      >
                        <Chevron />
                      </button>
                      <span className={styles.fileBadge}>{f.code}</span>
                      <div className={s.accMain}>
                        <div className={s.accName}>{f.name}</div>
                        <div className={s.accMeta}>
                          {depts.length} department{depts.length === 1 ? "" : "s"} · {progCount}{" "}
                          programme{progCount === 1 ? "" : "s"}
                        </div>
                      </div>
                      <div className={s.accActions}>
                        <button
                          type="button"
                          className={s.linkBtn}
                          onClick={() => setModal({ kind: "faculty", entity: f })}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={[s.linkBtn, s.danger].join(" ")}
                          onClick={() =>
                            setDel({
                              title: "Delete faculty",
                              message: `Delete ${f.name}? Its departments and programmes must be removed first.`,
                              run: (t) => api.deleteFaculty(f.id, t),
                            })
                          }
                        >
                          Delete
                        </button>
                      </div>
                    </div>

                    {isOpen ? (
                      <div className={s.nest}>
                        {depts.map((dep) => {
                          const progs = progsByDept.get(dep.id) ?? [];
                          const dOpen = openD.has(dep.id);
                          return (
                            <div key={dep.id}>
                              <div className={s.subRow}>
                                <button
                                  type="button"
                                  className={[s.chev, dOpen ? s.chevOpen : ""].join(" ")}
                                  onClick={() => toggle(openD, dep.id, setOpenD)}
                                  aria-label={dOpen ? "Collapse" : "Expand"}
                                  aria-expanded={dOpen}
                                >
                                  <Chevron />
                                </button>
                                <span className={s.subName}>
                                  {dep.name}
                                  <span className={s.subCode}>{dep.code}</span>
                                </span>
                                <span className={styles.cellMuted} style={{ fontSize: "0.78rem" }}>
                                  {progs.length} prog{progs.length === 1 ? "" : "s"}
                                </span>
                                <button
                                  type="button"
                                  className={s.linkBtn}
                                  onClick={() =>
                                    setModal({ kind: "department", facultyId: f.id, entity: dep })
                                  }
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className={[s.linkBtn, s.danger].join(" ")}
                                  onClick={() =>
                                    setDel({
                                      title: "Delete department",
                                      message: `Delete ${dep.name}? Its programmes and courses must be removed first.`,
                                      run: (t) => api.deleteDepartment(dep.id, t),
                                    })
                                  }
                                >
                                  Delete
                                </button>
                              </div>
                              {dOpen ? (
                                <div className={s.progList}>
                                  {progs.map((p) => (
                                    <div key={p.id} className={s.progRow}>
                                      <span className={s.progName}>{p.name}</span>
                                      {p.degree_type ? (
                                        <span className={s.degreeTag}>{p.degree_type}</span>
                                      ) : null}
                                      <button
                                        type="button"
                                        className={s.linkBtn}
                                        onClick={() =>
                                          setModal({
                                            kind: "programme",
                                            departmentId: dep.id,
                                            entity: p,
                                          })
                                        }
                                      >
                                        Edit
                                      </button>
                                      <button
                                        type="button"
                                        className={[s.linkBtn, s.danger].join(" ")}
                                        onClick={() =>
                                          setDel({
                                            title: "Delete programme",
                                            message: `Delete ${p.name}?`,
                                            run: (t) => api.deleteProgramme(p.id, t),
                                          })
                                        }
                                      >
                                        Delete
                                      </button>
                                    </div>
                                  ))}
                                  <button
                                    type="button"
                                    className={s.addRow}
                                    onClick={() =>
                                      setModal({ kind: "programme", departmentId: dep.id })
                                    }
                                  >
                                    <PlusIcon size={14} /> Add programme
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                        <div style={{ padding: "6px 18px 4px" }}>
                          <button
                            type="button"
                            className={s.addRow}
                            onClick={() => setModal({ kind: "department", facultyId: f.id })}
                          >
                            <PlusIcon size={14} /> Add department
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </section>

          {/* Sessions & semesters */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>Sessions &amp; semesters</h2>
              <button
                type="button"
                className={styles.panelLink}
                onClick={() => setModal({ kind: "session" })}
              >
                + New session
              </button>
            </div>
            {sessions.length === 0 ? (
              <EmptyState
                title="No sessions yet"
                hint="Create an academic session to define your calendar."
              />
            ) : (
              sessions.map((sess) => {
                const sems = semsBySession.get(sess.id) ?? [];
                return (
                  <div key={sess.id} className={s.sessionBlock}>
                    <div className={s.sessionTop}>
                      <span className={s.sessionName}>{sess.name}</span>
                      {sess.is_current ? (
                        <Badge tone="success">Active</Badge>
                      ) : (
                        <Badge tone="neutral">Closed</Badge>
                      )}
                      <span className={s.sessionSpacer} />
                      <button
                        type="button"
                        className={s.linkBtn}
                        onClick={() => setModal({ kind: "session", entity: sess })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className={[s.linkBtn, s.danger].join(" ")}
                        onClick={() =>
                          setDel({
                            title: "Delete session",
                            message: `Delete ${sess.name}? Its semesters must be removed first.`,
                            run: (t) => api.deleteSession(sess.id, t),
                          })
                        }
                      >
                        Delete
                      </button>
                    </div>
                    <div className={s.sessionDates}>
                      {fullRange(sess.start_date, sess.end_date)}
                    </div>
                    <div className={s.semList}>
                      {sems.map((sem) => {
                        const st = semesterStatus(sem);
                        return (
                          <div key={sem.id} className={s.semRow}>
                            <span
                              className={[s.semDot, st.active ? s.semDotActive : ""].join(" ")}
                              aria-hidden="true"
                            />
                            <span className={s.semName}>{sem.name}</span>
                            <span className={s.semRange}>
                              {shortRange(sem.start_date, sem.end_date)}
                            </span>
                            <span className={s.semSpacer} />
                            <span
                              className={[s.semStatus, st.active ? s.statusActive : ""].join(" ")}
                            >
                              {st.label}
                            </span>
                            <button
                              type="button"
                              className={[s.linkBtn, s.danger].join(" ")}
                              onClick={() =>
                                setDel({
                                  title: "Delete semester",
                                  message: `Delete the ${sem.name} of ${sess.name}?`,
                                  run: (t) => api.deleteSemester(sem.id, t),
                                })
                              }
                            >
                              Delete
                            </button>
                          </div>
                        );
                      })}
                      <button
                        type="button"
                        className={s.addRow}
                        onClick={() => setModal({ kind: "semester", sessionId: sess.id })}
                      >
                        <PlusIcon size={14} /> Add semester
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </section>
        </div>
      )}

      {modal ? (
        <EntityModal
          spec={modal}
          token={token}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            reload();
          }}
        />
      ) : null}

      {del ? (
        <GenericDelete
          spec={del}
          token={token}
          onClose={() => setDel(null)}
          onDone={() => {
            setDel(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

function groupBy<T>(items: T[], key: (item: T) => string) {
  const m = new Map<string, T[]>();
  items.forEach((i) => {
    const k = key(i);
    const arr = m.get(k);
    if (arr) arr.push(i);
    else m.set(k, [i]);
  });
  return m;
}

const TITLES: Record<EntityKind, string> = {
  faculty: "faculty",
  department: "department",
  programme: "programme",
  session: "session",
  semester: "semester",
};

function EntityModal({
  spec,
  token,
  onClose,
  onSaved,
}: {
  spec: ModalSpec;
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = spec.entity as Record<string, unknown> | undefined;
  const isEdit = Boolean(editing);
  const [f, setF] = useState<Record<string, string>>(() => ({
    name: (editing?.name as string) ?? "",
    code: (editing?.code as string) ?? "",
    degree_type: (editing?.degree_type as string) ?? "",
    start_date: (editing?.start_date as string) ?? "",
    end_date: (editing?.end_date as string) ?? "",
  }));
  const [isCurrent, setIsCurrent] = useState(Boolean(editing?.is_current));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);

  const set = (k: string) => (v: string) => setF((prev) => ({ ...prev, [k]: v }));

  async function submit() {
    setSaving(true);
    setMessage(null);
    setErrors(null);
    try {
      await save();
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        setMessage(err.message);
        setErrors(err.fieldErrors);
      } else {
        setMessage("Could not save. Please try again.");
      }
      setSaving(false);
    }
  }

  async function save() {
    const id = editing?.id as string | undefined;
    switch (spec.kind) {
      case "faculty": {
        const body = { name: f.name.trim(), code: f.code.trim() };
        return isEdit ? api.updateFaculty(id!, body, token) : api.createFaculty(body, token);
      }
      case "department": {
        const body = { faculty: spec.facultyId, name: f.name.trim(), code: f.code.trim() };
        return isEdit ? api.updateDepartment(id!, body, token) : api.createDepartment(body, token);
      }
      case "programme": {
        const body = {
          department: spec.departmentId,
          name: f.name.trim(),
          code: f.code.trim(),
          degree_type: f.degree_type.trim(),
        };
        return isEdit ? api.updateProgramme(id!, body, token) : api.createProgramme(body, token);
      }
      case "session": {
        const body = {
          name: f.name.trim(),
          start_date: f.start_date,
          end_date: f.end_date,
          is_current: isCurrent,
        };
        return isEdit ? api.updateSession(id!, body, token) : api.createSession(body, token);
      }
      case "semester": {
        const body = {
          session: spec.sessionId,
          name: f.name.trim(),
          start_date: f.start_date,
          end_date: f.end_date,
        };
        return isEdit ? api.updateSemester(id!, body, token) : api.createSemester(body, token);
      }
    }
  }

  const title = `${isEdit ? "Edit" : "Add"} ${TITLES[spec.kind]}`;
  const hasCode =
    spec.kind === "faculty" || spec.kind === "department" || spec.kind === "programme";
  const hasDates = spec.kind === "session" || spec.kind === "semester";

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={saving} onClick={submit}>
            {isEdit ? "Save changes" : "Create"}
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

        <TextInput
          label="Name"
          required
          value={f.name}
          onChange={set("name")}
          placeholder={
            spec.kind === "session"
              ? "2025/2026"
              : spec.kind === "semester"
                ? "First semester"
                : "Faculty of Engineering"
          }
          error={firstError(errors, "name")}
        />

        {hasCode ? (
          <TextInput
            label="Code"
            required
            value={f.code}
            onChange={set("code")}
            placeholder="ENG"
            error={firstError(errors, "code")}
          />
        ) : null}

        {spec.kind === "programme" ? (
          <TextInput
            label="Degree type"
            required
            value={f.degree_type}
            onChange={set("degree_type")}
            placeholder="B.Eng"
            error={firstError(errors, "degree_type")}
          />
        ) : null}

        {hasDates ? (
          <div className={styles.formGrid}>
            <TextInput
              label="Start date"
              required
              type="date"
              value={f.start_date}
              onChange={set("start_date")}
              error={firstError(errors, "start_date")}
            />
            <TextInput
              label="End date"
              required
              type="date"
              value={f.end_date}
              onChange={set("end_date")}
              error={firstError(errors, "end_date")}
            />
          </div>
        ) : null}

        {spec.kind === "session" ? (
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={isCurrent}
              onChange={(e) => setIsCurrent(e.target.checked)}
            />
            Set as the current active session
          </label>
        ) : null}
      </div>
    </Modal>
  );
}

function GenericDelete({
  spec,
  token,
  onClose,
  onDone,
}: {
  spec: DeleteSpec;
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
      await spec.run(token);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete this record.");
      setLoading(false);
    }
  }
  return (
    <ConfirmDialog
      title={spec.title}
      message={spec.message}
      loading={loading}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
    />
  );
}
