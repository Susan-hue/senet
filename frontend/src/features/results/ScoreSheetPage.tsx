import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Alert, Button } from "../../components";
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  SkeletonTable,
} from "../../components/admin";
import { useAuth } from "../../hooks";
import { ApiError } from "../../services/api";
import { getCourse, listEnrolments } from "../../services/accounts";
import {
  createResult,
  getResult,
  listResults,
  recordScore,
  submitResult,
} from "../../services/results";
import { RESULT_STATUS_META } from "../../types";
import type { Course, CourseResult, Enrolment, StudentScore } from "../../types";
import { useAsyncData, useDebounced } from "../admin/useAsyncData";
import { PageHeader, Pager, SearchBox, firstError } from "../admin/ui";
import adminStyles from "../admin/admin.module.css";
import styles from "./results.module.css";

const PAGE_SIZE = 50;

interface DraftRow {
  ca: string;
  exam: string;
}

function sameScore(draft: string, saved: string | undefined) {
  if (draft.trim() === "") return saved === undefined;
  if (saved === undefined) return false;
  return Number(draft) === Number(saved);
}

function scoreError(row: DraftRow, caMax: number, examMax: number): string | null {
  if (row.ca.trim() !== "") {
    const ca = Number(row.ca);
    if (Number.isNaN(ca) || ca < 0 || ca > caMax) return `CA must be between 0 and ${caMax}.`;
  }
  if (row.exam.trim() === "") return "Exam score is required to save this row.";
  const exam = Number(row.exam);
  if (Number.isNaN(exam) || exam < 0 || exam > examMax) {
    return `Exam must be between 0 and ${examMax}.`;
  }
  return null;
}

export function ScoreSheetPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const [params] = useSearchParams();
  const courseId = params.get("course") ?? "";
  const sessionId = params.get("session") ?? "";
  const semesterId = params.get("semester") ?? "";

  const { data, loading, error, reload } = useAsyncData(async () => {
    const [course, roster, resultsPage] = await Promise.all([
      getCourse(courseId, token),
      listEnrolments(token, { course: courseId, session: sessionId, semester: semesterId }),
      listResults(token, { page_size: 100 }),
    ]);
    const existing = resultsPage.results.find(
      (r) => r.course === courseId && r.session === sessionId && r.semester === semesterId,
    );
    const detail = existing ? await getResult(existing.id, token) : null;
    return { course, roster, detail };
  }, [token, courseId, sessionId, semesterId]);

  const course: Course | null = data?.course ?? null;
  const roster: Enrolment[] = useMemo(() => data?.roster ?? [], [data]);

  const [result, setResult] = useState<CourseResult | null>(null);
  const [saved, setSaved] = useState<Map<string, StudentScore>>(new Map());
  const [drafts, setDrafts] = useState<Map<string, DraftRow>>(new Map());
  const [rowErrors, setRowErrors] = useState<Map<string, string>>(new Map());
  const [banner, setBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveProgress, setSaveProgress] = useState(0);
  const [saveTotal, setSaveTotal] = useState(0);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim().toLowerCase());
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!data) return;
    setResult(data.detail);
    setSaved(new Map((data.detail?.scores ?? []).map((s) => [s.student, s])));
    setDrafts(new Map());
    setRowErrors(new Map());
    setBanner(null);
  }, [data]);

  const caMax = Number(course?.effective_ca_weight ?? 100);
  const examMax = Number(course?.effective_exam_weight ?? 100);
  const status = result?.status ?? null;
  const meta = status ? RESULT_STATUS_META[status] : null;
  const editable = !status || status === "draft" || status === "returned";

  const draftFor = useCallback(
    (studentId: string): DraftRow => {
      const draft = drafts.get(studentId);
      if (draft) return draft;
      const row = saved.get(studentId);
      return { ca: row?.ca_score ?? "", exam: row?.exam_score ?? "" };
    },
    [drafts, saved],
  );

  const isDirty = useCallback(
    (studentId: string) => {
      const draft = drafts.get(studentId);
      if (!draft) return false;
      const row = saved.get(studentId);
      return !(sameScore(draft.ca, row?.ca_score) && sameScore(draft.exam, row?.exam_score));
    },
    [drafts, saved],
  );

  const dirtyIds = useMemo(() => [...drafts.keys()].filter((id) => isDirty(id)), [drafts, isDirty]);

  useEffect(() => {
    if (dirtyIds.length === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyIds.length]);

  const filteredRoster = useMemo(() => {
    if (!search) return roster;
    return roster.filter(
      (e) =>
        e.student_name.toLowerCase().includes(search) ||
        e.student_identifier.toLowerCase().includes(search),
    );
  }, [roster, search]);

  const totalPages = Math.max(1, Math.ceil(filteredRoster.length / PAGE_SIZE));
  const pageRows = filteredRoster.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  function setField(studentId: string, field: keyof DraftRow, value: string) {
    setDrafts((prev) => {
      const next = new Map(prev);
      next.set(studentId, { ...draftFor(studentId), [field]: value });
      return next;
    });
  }

  async function saveDraft() {
    const toSave = dirtyIds.filter((id) => {
      const err = scoreError(draftFor(id), caMax, examMax);
      return err === null;
    });
    const blocked = dirtyIds.length - toSave.length;
    if (toSave.length === 0) {
      setBanner({
        kind: "error",
        text: blocked
          ? "No rows could be saved — fix the highlighted scores first."
          : "Nothing to save yet.",
      });
      return;
    }

    setSaving(true);
    setSaveProgress(0);
    setSaveTotal(toSave.length);
    setBanner(null);
    let target = result;
    try {
      if (!target) {
        target = await createResult(
          { course: courseId, session: sessionId, semester: semesterId },
          token,
        );
        setResult(target);
      }
    } catch (err) {
      setSaving(false);
      setBanner({
        kind: "error",
        text: err instanceof ApiError ? err.message : "Could not create the result sheet.",
      });
      return;
    }

    const resultId = target.id;
    const failures = new Map<string, string>();
    let done = 0;

    for (const studentId of toSave) {
      const draft = draftFor(studentId);
      try {
        const row = await recordScore(
          resultId,
          {
            student: studentId,
            ca_score: draft.ca.trim() === "" ? null : draft.ca,
            exam_score: draft.exam,
          },
          token,
        );
        setSaved((prev) => new Map(prev).set(studentId, row));
        setDrafts((prev) => {
          const next = new Map(prev);
          next.delete(studentId);
          return next;
        });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? (firstError(err.fieldErrors, "ca_score", "exam_score", "student") ?? err.message)
            : "Could not save this row.";
        failures.set(studentId, message);
      } finally {
        done += 1;
        setSaveProgress(done);
      }
    }
    setRowErrors(failures);
    setSaving(false);
    const savedCount = toSave.length - failures.size;
    if (failures.size === 0 && blocked === 0) {
      setBanner({
        kind: "success",
        text: `Draft saved — ${savedCount} score${savedCount === 1 ? "" : "s"} recorded.`,
      });
    } else {
      setBanner({
        kind: "error",
        text: `Saved ${savedCount} of ${toSave.length + blocked} rows. ${failures.size ? "Some rows were rejected by the server." : ""} ${blocked ? `${blocked} row${blocked === 1 ? " has" : "s have"} invalid scores.` : ""}`.trim(),
      });
    }
  }

  async function doSubmit() {
    if (!result) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await submitResult(result.id, token);
      setResult(updated);
      setConfirmSubmit(false);
      setBanner({ kind: "success", text: "Result submitted to your HOD for approval." });
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Could not submit the result.");
    } finally {
      setSubmitting(false);
    }
  }

  const savedCount = saved.size;
  const canSubmit = editable && result !== null && savedCount > 0 && dirtyIds.length === 0;
  const submitHint = !editable
    ? null
    : dirtyIds.length > 0
      ? "Save your draft before submitting."
      : savedCount === 0
        ? "Enter and save at least one score first."
        : null;

  if (!courseId || !sessionId || !semesterId) {
    return (
      <div className={adminStyles.page}>
        <ErrorState message="This sheet link is incomplete. Open it from My Courses." />
      </div>
    );
  }

  return (
    <div className={adminStyles.page}>
      <div className={styles.crumbs}>
        <Link to="/teach" className={styles.crumbLink}>
          My Courses
        </Link>
        <span aria-hidden="true">/</span>
        <span>{course ? course.code : "Score sheet"}</span>
      </div>

      <PageHeader
        title={course ? `${course.code} — ${course.title}` : "Score sheet"}
        subtitle={
          course
            ? `CA out of ${caMax} · Exam out of ${examMax} · ${roster.length.toLocaleString()} enrolled student${roster.length === 1 ? "" : "s"}.`
            : undefined
        }
        actions={
          meta ? (
            <Badge tone={meta.tone}>{meta.label}</Badge>
          ) : (
            <Badge tone="neutral">Not started</Badge>
          )
        }
      />

      {status === "returned" && result?.returned_reason ? (
        <div className={styles.reasonBlock}>
          <Alert variant="error">
            <strong>Returned by your HOD:</strong> {result.returned_reason}
          </Alert>
        </div>
      ) : null}
      {meta && status !== "returned" && !editable ? (
        <div className={styles.reasonBlock}>
          <Alert variant="info">{meta.hint}</Alert>
        </div>
      ) : null}
      {banner ? (
        <div className={styles.reasonBlock}>
          <Alert variant={banner.kind === "success" ? "success" : "error"}>{banner.text}</Alert>
        </div>
      ) : null}

      {loading ? (
        <SkeletonTable rows={8} cols={6} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : roster.length === 0 ? (
        <EmptyState
          title="No students enrolled"
          hint="Once students are enrolled in this course for the term, they will appear here for score entry."
        />
      ) : (
        <>
          <div className={adminStyles.toolbar}>
            <SearchBox
              value={query}
              onChange={(v) => {
                setQuery(v);
                setPage(1);
              }}
              placeholder="Search by name or matric number…"
            />
            <span className={adminStyles.spacer} />
            {editable ? (
              <span className={styles.dirtyNote} aria-live="polite">
                {saving
                  ? `Saving ${saveProgress} of ${saveTotal}…`
                  : dirtyIds.length > 0
                    ? `${dirtyIds.length} unsaved change${dirtyIds.length === 1 ? "" : "s"}`
                    : savedCount > 0
                      ? "All changes saved"
                      : ""}
              </span>
            ) : null}
          </div>

          <section className={adminStyles.panel}>
            <div className={adminStyles.tableWrap}>
              <table className={[adminStyles.table, styles.sheetTable].join(" ")}>
                <thead>
                  <tr>
                    <th>Matric No.</th>
                    <th>Student</th>
                    <th>CA ({caMax})</th>
                    <th>Exam ({examMax})</th>
                    <th>Total</th>
                    <th>Grade</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((enrolment) => {
                    const id = enrolment.student;
                    const draft = draftFor(id);
                    const row = saved.get(id);
                    const dirty = isDirty(id);
                    const localError = dirty ? scoreError(draft, caMax, examMax) : null;
                    const serverError = rowErrors.get(id) ?? null;
                    const problem = localError ?? serverError;
                    return (
                      <tr key={enrolment.id} className={dirty ? styles.dirtyRow : undefined}>
                        <td className={[adminStyles.mono, adminStyles.cellMuted].join(" ")}>
                          {enrolment.student_identifier}
                        </td>
                        <td className={adminStyles.cellStrong}>{enrolment.student_name}</td>
                        <td>
                          <input
                            className={[
                              styles.scoreInput,
                              problem ? styles.scoreInputError : "",
                            ].join(" ")}
                            inputMode="decimal"
                            value={draft.ca}
                            placeholder={editable ? "auto" : undefined}
                            disabled={!editable || saving}
                            onChange={(e) => setField(id, "ca", e.target.value)}
                            aria-label={`CA score for ${enrolment.student_name}`}
                            aria-invalid={problem ? true : undefined}
                          />
                        </td>
                        <td>
                          <input
                            className={[
                              styles.scoreInput,
                              problem ? styles.scoreInputError : "",
                            ].join(" ")}
                            inputMode="decimal"
                            value={draft.exam}
                            disabled={!editable || saving}
                            onChange={(e) => setField(id, "exam", e.target.value)}
                            aria-label={`Exam score for ${enrolment.student_name}`}
                            aria-invalid={problem ? true : undefined}
                          />
                          {problem ? <span className={styles.rowError}>{problem}</span> : null}
                        </td>
                        <td className={adminStyles.mono}>{!dirty && row ? row.total : "—"}</td>
                        <td>
                          {!dirty && row ? (
                            <span className={styles.gradeChip}>{row.grade}</span>
                          ) : (
                            <span className={adminStyles.cellMuted}>—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pager
              page={page}
              totalPages={totalPages}
              count={filteredRoster.length}
              label={search ? "matching students" : "students"}
              onPage={setPage}
            />
          </section>

          {editable ? (
            <div className={styles.actionBar}>
              <span className={styles.actionHint}>
                Leave CA blank to aggregate it from graded assessment items.
                {submitHint ? ` ${submitHint}` : ""}
              </span>
              <div className={styles.actionButtons}>
                <Button
                  variant="ghost"
                  onClick={() => void saveDraft()}
                  loading={saving}
                  disabled={dirtyIds.length === 0}
                >
                  Save as draft
                </Button>
                <Button onClick={() => setConfirmSubmit(true)} disabled={!canSubmit || saving}>
                  {status === "returned" ? "Resubmit to HOD" : "Submit to HOD"}
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}

      {confirmSubmit ? (
        <ConfirmDialog
          title={status === "returned" ? "Resubmit result to HOD?" : "Submit result to HOD?"}
          message={`This sends the ${course?.code ?? ""} result sheet (${savedCount} score${savedCount === 1 ? "" : "s"}) to your HOD for approval and locks it for editing. You will only be able to edit again if the sheet is returned to you.`}
          confirmLabel={submitting ? "Submitting…" : "Submit and lock"}
          loading={submitting}
          error={submitError}
          onConfirm={() => void doSubmit()}
          onCancel={() => {
            setConfirmSubmit(false);
            setSubmitError(null);
          }}
        />
      ) : null}
    </div>
  );
}
