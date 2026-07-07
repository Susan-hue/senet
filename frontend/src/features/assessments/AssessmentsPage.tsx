import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Button } from "../../components";
import { Badge, EmptyState, ErrorState, Modal, SkeletonTable } from "../../components/admin";
import { useAuth } from "../../hooks";
import { ApiError } from "../../services/api";
import { getCourse, listAssignments, listSemesters, listSessions } from "../../services/accounts";
import { caSummary, createItem, listItems } from "../../services/assessments";
import { ASSESSMENT_KIND_META, ASSESSMENT_KIND_OPTIONS } from "../../types";
import type { AssessmentItem, CaSummaryRow, Course, Page, Semester, Session } from "../../types";
import { useAsyncData } from "../admin/useAsyncData";
import { PageHeader, Pager, SelectInput, TextInput, firstError } from "../admin/ui";
import { ClipboardIcon } from "../admin/adminIcons";
import adminStyles from "../admin/admin.module.css";
import styles from "./assessments.module.css";

function currentSemesterOf(session: Session | null, semesters: Semester[]) {
  if (!session) return null;
  const now = Date.now();
  const inSession = semesters.filter((s) => s.session === session.id);
  return (
    inSession.find(
      (s) => new Date(s.start_date).getTime() <= now && now <= new Date(s.end_date).getTime(),
    ) ??
    inSession[0] ??
    null
  );
}

export function fmtPoints(value: string | number) {
  const n = Number(value);
  return Number.isNaN(n)
    ? String(value)
    : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function fmtDateTime(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function AssessmentsPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const semesterParam = params.get("semester") ?? "";
  const courseParam = params.get("course") ?? "";

  const term = useAsyncData(
    () => Promise.all([listSessions(token), listSemesters(token), listAssignments(token)]),
    [token],
  );
  const [sessions, semesters, assignments] = term.data ?? [[], [], []];

  const session = useMemo(
    () => sessions.find((s) => s.is_current) ?? sessions[0] ?? null,
    [sessions],
  );
  const sessionSemesters = useMemo(
    () => semesters.filter((s) => s.session === session?.id),
    [semesters, session],
  );
  const semester = semesterParam
    ? (sessionSemesters.find((s) => s.id === semesterParam) ?? null)
    : currentSemesterOf(session, semesters);

  const termAssignments = useMemo(
    () => assignments.filter((a) => a.session === session?.id && a.semester === semester?.id),
    [assignments, session, semester],
  );
  const assignment =
    termAssignments.find((a) => a.course === courseParam) ?? termAssignments[0] ?? null;
  const courseId = assignment?.course ?? "";
  const sessionId = session?.id ?? "";
  const semesterId = semester?.id ?? "";

  const [caPage, setCaPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const scoped = useAsyncData(async () => {
    if (!courseId || !sessionId || !semesterId) return null;
    const [course, items] = await Promise.all([
      getCourse(courseId, token),
      listItems(token, {
        course: courseId,
        session: sessionId,
        semester: semesterId,
        page_size: 100,
      }),
    ]);
    let ca: Page<CaSummaryRow> | null = null;
    if (items.count > 0) {
      try {
        ca = await caSummary(token, {
          course: courseId,
          session: sessionId,
          semester: semesterId,
          page: caPage,
          page_size: 50,
        });
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      }
    }
    return { course, items, ca };
  }, [token, courseId, sessionId, semesterId, caPage]);

  const course: Course | null = scoped.data?.course ?? null;
  const items: AssessmentItem[] = scoped.data?.items.results ?? [];
  const ca = scoped.data?.ca ?? null;

  const caBudget = Number(course?.effective_ca_weight ?? 0);
  const weightUsed = items.reduce((sum, item) => sum + Number(item.weight), 0);
  const budgetPct = caBudget > 0 ? Math.min(100, (weightUsed / caBudget) * 100) : 0;

  function setParam(key: "semester" | "course", value: string) {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (key === "semester") next.delete("course");
    setParams(next, { replace: true });
    setCaPage(1);
  }

  const loading = term.loading || scoped.loading;
  const error = term.error ?? scoped.error;

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="Continuous Assessment"
        subtitle={
          assignment && session
            ? `CA items and grading for ${assignment.course_code} · ${session.name}${semester ? ` · ${semester.name} semester` : ""}.`
            : "Create weighted CA items and grade student work for your assigned courses."
        }
        actions={
          <div className={styles.termPickers}>
            {sessionSemesters.length > 1 ? (
              <select
                className={adminStyles.filter}
                value={semester?.id ?? ""}
                onChange={(e) => setParam("semester", e.target.value)}
                aria-label="Semester"
              >
                {sessionSemesters.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} semester
                  </option>
                ))}
              </select>
            ) : null}
            {termAssignments.length > 0 ? (
              <select
                className={adminStyles.filter}
                value={courseId}
                onChange={(e) => setParam("course", e.target.value)}
                aria-label="Course"
              >
                {termAssignments.map((a) => (
                  <option key={a.id} value={a.course}>
                    {a.course_code} — {a.course_title}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
        }
      />

      {loading ? (
        <SkeletonTable rows={6} cols={5} />
      ) : error ? (
        <ErrorState message={error} onRetry={term.error ? term.reload : scoped.reload} />
      ) : termAssignments.length === 0 ? (
        <EmptyState
          title="No courses assigned this term"
          hint="Once you are assigned a course for this session and semester, you can create CA items for it here."
          icon={<ClipboardIcon size={22} />}
        />
      ) : !course ? null : (
        <>
          <section className={[adminStyles.panel, styles.budgetPanel].join(" ")}>
            <div className={styles.budgetHead}>
              <div>
                <h2 className={adminStyles.panelTitle}>CA weight budget</h2>
                <p className={styles.budgetSub}>
                  {course.code} grades CA out of <strong>{caBudget}</strong> of 100 course points
                  (exam covers the remaining {Number(course.effective_exam_weight)}). Items below
                  claim <strong>{fmtPoints(weightUsed)}</strong> of those {caBudget} points — the
                  server rejects any item that would push the total past the budget.
                </p>
              </div>
              <Button onClick={() => setCreating(true)}>New CA item</Button>
            </div>
            <div
              className={styles.budgetBar}
              role="img"
              aria-label={`CA weight used: ${fmtPoints(weightUsed)} of ${caBudget}`}
            >
              <span className={styles.budgetFill} style={{ width: `${budgetPct}%` }} />
            </div>
            <span className={styles.budgetLegend}>
              {fmtPoints(weightUsed)} / {caBudget} points allocated
            </span>
          </section>

          {items.length === 0 ? (
            <EmptyState
              title="No CA items yet"
              hint={`Create an assignment, test or project for ${course.code}. Its weight is the share of the final course mark it carries.`}
              icon={<ClipboardIcon size={22} />}
              action={<Button onClick={() => setCreating(true)}>New CA item</Button>}
            />
          ) : (
            <section className={adminStyles.panel}>
              <div className={adminStyles.panelHead}>
                <h2 className={adminStyles.panelTitle}>Assessment items</h2>
              </div>
              <div className={adminStyles.tableWrap}>
                <table className={[adminStyles.table, styles.itemsTable].join(" ")}>
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Type</th>
                      <th>Weight</th>
                      <th>Marked out of</th>
                      <th>Due</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const kind = ASSESSMENT_KIND_META[item.kind];
                      return (
                        <tr key={item.id}>
                          <td className={adminStyles.cellStrong}>{item.title}</td>
                          <td>
                            <Badge tone={kind.tone}>{kind.label}</Badge>
                          </td>
                          <td className={adminStyles.mono}>{fmtPoints(item.weight)} pts</td>
                          <td className={adminStyles.mono}>{fmtPoints(item.max_score)}</td>
                          <td className={adminStyles.cellMuted}>{fmtDateTime(item.due_date)}</td>
                          <td className={adminStyles.rowActions}>
                            <button
                              type="button"
                              className={adminStyles.textBtn}
                              onClick={() => navigate(`/teach/assessments/grade?item=${item.id}`)}
                            >
                              Grade submissions →
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {items.length > 0 && ca ? (
            <section className={adminStyles.panel}>
              <div className={adminStyles.panelHead}>
                <h2 className={adminStyles.panelTitle}>
                  Aggregated CA — feeds the results pipeline
                </h2>
              </div>
              <p className={styles.caExplain}>
                Each graded item contributes{" "}
                <span className={adminStyles.mono}>score ÷ marked-out-of × weight</span>. The
                backend sums those into the CA score below (out of {caBudget}) — when you leave the
                CA column blank on the score sheet, this is the number that flows in. Ungraded items
                contribute 0 until you grade them.
              </p>
              <div className={adminStyles.tableWrap}>
                <table className={adminStyles.table}>
                  <thead>
                    <tr>
                      <th>Matric No.</th>
                      <th>Student</th>
                      <th>CA score (of {caBudget})</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ca.results.map((row) => (
                      <tr key={row.student}>
                        <td className={[adminStyles.mono, adminStyles.cellMuted].join(" ")}>
                          {row.student_identifier}
                        </td>
                        <td className={adminStyles.cellStrong}>{row.student_name}</td>
                        <td className={adminStyles.mono}>{fmtPoints(row.ca_score)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager
                page={ca.page}
                totalPages={ca.total_pages}
                count={ca.count}
                label="enrolled students"
                onPage={setCaPage}
              />
            </section>
          ) : null}
        </>
      )}

      {creating && course && session && semester ? (
        <CreateItemModal
          course={course}
          sessionId={sessionId}
          semesterId={semesterId}
          weightLeft={Math.max(0, caBudget - weightUsed)}
          token={token}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            scoped.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function CreateItemModal({
  course,
  sessionId,
  semesterId,
  weightLeft,
  token,
  onClose,
  onSaved,
}: {
  course: Course;
  sessionId: string;
  semesterId: string;
  weightLeft: number;
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("assignment");
  const [weight, setWeight] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);

  async function submit() {
    const missing: Record<string, string[]> = {};
    if (!title.trim()) missing.title = ["A title is required."];
    if (!weight.trim()) missing.weight = ["A weight is required."];
    if (!maxScore.trim()) missing.max_score = ["A maximum score is required."];
    if (!dueDate) missing.due_date = ["A due date is required."];
    if (Object.keys(missing).length > 0) {
      setErrors(missing);
      setMessage(null);
      return;
    }

    setSaving(true);
    setMessage(null);
    setErrors(null);
    try {
      await createItem(
        {
          course: course.id,
          session: sessionId,
          semester: semesterId,
          title: title.trim(),
          kind,
          max_score: maxScore,
          weight,
          due_date: new Date(dueDate).toISOString(),
        },
        token,
      );
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        setMessage(err.message);
        setErrors(err.fieldErrors);
      } else {
        setMessage("Could not create the assessment item.");
      }
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`New CA item — ${course.code}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={saving} onClick={() => void submit()}>
            Create item
          </Button>
        </>
      }
    >
      <div className={adminStyles.form}>
        {message ? (
          <div className={adminStyles.formError}>
            <Alert variant="error">{message}</Alert>
          </div>
        ) : null}
        <TextInput
          label="Title"
          required
          value={title}
          onChange={setTitle}
          placeholder="Assignment 1"
          error={firstError(errors, "title")}
        />
        <div className={adminStyles.formGrid}>
          <SelectInput
            label="Type"
            required
            value={kind}
            onChange={setKind}
            options={ASSESSMENT_KIND_OPTIONS.map((k) => ({ value: k.value, label: k.label }))}
            error={firstError(errors, "kind")}
          />
          <TextInput
            label={`Weight (${fmtPoints(weightLeft)} pts left)`}
            required
            type="number"
            value={weight}
            onChange={setWeight}
            placeholder="10"
            error={firstError(errors, "weight")}
          />
          <TextInput
            label="Marked out of"
            required
            type="number"
            value={maxScore}
            onChange={setMaxScore}
            placeholder="20"
            error={firstError(errors, "max_score")}
          />
          <label className={adminStyles.formFull}>
            <span className={adminStyles.fieldLabel}>
              Due date <span className={adminStyles.req}>*</span>
            </span>
            <input
              className={adminStyles.input}
              type="datetime-local"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              aria-invalid={firstError(errors, "due_date") ? true : undefined}
            />
            {firstError(errors, "due_date") ? (
              <span className={adminStyles.pageSub}>{firstError(errors, "due_date")}</span>
            ) : null}
          </label>
        </div>
        <p className={styles.modalHint}>
          Weight is the item&apos;s share of the final course mark ({course.code} reserves{" "}
          {Number(course.effective_ca_weight)} points for CA). &ldquo;Marked out of&rdquo; is the
          raw scale you grade on — a 15-point weight can still be marked out of 20.
        </p>
      </div>
    </Modal>
  );
}
