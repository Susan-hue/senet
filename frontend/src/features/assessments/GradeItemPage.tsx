import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Alert, Button } from "../../components";
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Modal,
  SkeletonTable,
} from "../../components/admin";
import { useAuth } from "../../hooks";
import { ApiError } from "../../services/api";
import { listEnrolments } from "../../services/accounts";
import { getItem, gradeStudent, listSubmissions } from "../../services/assessments";
import { ASSESSMENT_KIND_META } from "../../types";
import type { AssessmentGrade, AssessmentItem, AssessmentSubmission, Enrolment } from "../../types";
import { useAsyncData } from "../admin/useAsyncData";
import { PageHeader, firstError } from "../admin/ui";
import adminStyles from "../admin/admin.module.css";
import resultStyles from "../results/results.module.css";
import { fmtDateTime, fmtPoints } from "./AssessmentsPage";
import styles from "./assessments.module.css";

export function GradeItemPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const [params] = useSearchParams();
  const itemId = params.get("item") ?? "";

  const { data, loading, error, reload } = useAsyncData(async () => {
    if (!itemId) return null;
    const item = await getItem(itemId, token);
    const [roster, submissions] = await Promise.all([
      listEnrolments(token, {
        course: item.course,
        session: item.session,
        semester: item.semester,
      }),
      listSubmissions(itemId, token, { page_size: 100 }),
    ]);
    return { item, roster, submissions: submissions.results };
  }, [token, itemId]);

  const item: AssessmentItem | null = data?.item ?? null;
  const roster: Enrolment[] = data?.roster ?? [];
  const submissionByStudent = useMemo(() => {
    const map = new Map<string, AssessmentSubmission>();
    (data?.submissions ?? []).forEach((s) => map.set(s.student, s));
    return map;
  }, [data]);

  const [grades, setGrades] = useState<Map<string, AssessmentGrade>>(new Map());
  const [gradingStudent, setGradingStudent] = useState<Enrolment | null>(null);

  if (!itemId) {
    return (
      <div className={adminStyles.page}>
        <ErrorState message="This grading link is incomplete. Open it from the Continuous Assessment page." />
      </div>
    );
  }

  const kind = item ? ASSESSMENT_KIND_META[item.kind] : null;

  return (
    <div className={adminStyles.page}>
      <div className={resultStyles.crumbs}>
        <Link
          to={
            item
              ? `/teach/assessments?course=${item.course}&semester=${item.semester}`
              : "/teach/assessments"
          }
          className={resultStyles.crumbLink}
        >
          Continuous Assessment
        </Link>
        <span aria-hidden="true">/</span>
        <span>{item ? item.title : "Grading"}</span>
      </div>

      <PageHeader
        title={item ? `${item.title} — ${item.course_code}` : "Grade submissions"}
        subtitle={
          item
            ? `${item.course_title} · graded work counts ${fmtPoints(item.weight)} points of the final course mark.`
            : undefined
        }
        actions={kind ? <Badge tone={kind.tone}>{kind.label}</Badge> : null}
      />

      {item ? (
        <div className={styles.itemMeta}>
          <div className={styles.itemMetaEntry}>
            <span className={styles.itemMetaLabel}>Marked out of</span>
            <span className={styles.itemMetaValue}>{fmtPoints(item.max_score)}</span>
          </div>
          <div className={styles.itemMetaEntry}>
            <span className={styles.itemMetaLabel}>Weight</span>
            <span className={styles.itemMetaValue}>{fmtPoints(item.weight)} pts</span>
          </div>
          <div className={styles.itemMetaEntry}>
            <span className={styles.itemMetaLabel}>Due</span>
            <span className={styles.itemMetaValue}>{fmtDateTime(item.due_date)}</span>
          </div>
          <div className={styles.itemMetaEntry}>
            <span className={styles.itemMetaLabel}>Submissions</span>
            <span className={styles.itemMetaValue}>
              {submissionByStudent.size} of {roster.length}
            </span>
          </div>
        </div>
      ) : null}

      {loading ? (
        <SkeletonTable rows={8} cols={5} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : roster.length === 0 ? (
        <EmptyState
          title="No students enrolled"
          hint="Once students are enrolled in this course for the term, you can grade their work here."
        />
      ) : (
        <section className={adminStyles.panel}>
          <div className={adminStyles.tableWrap}>
            <table className={[adminStyles.table, styles.gradeTable].join(" ")}>
              <thead>
                <tr>
                  <th>Matric No.</th>
                  <th>Student</th>
                  <th>Submission</th>
                  <th>Score ({item ? fmtPoints(item.max_score) : "—"})</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {roster.map((enrolment) => {
                  const submission = submissionByStudent.get(enrolment.student);
                  const grade = grades.get(enrolment.student);
                  return (
                    <tr key={enrolment.id}>
                      <td className={[adminStyles.mono, adminStyles.cellMuted].join(" ")}>
                        {enrolment.student_identifier}
                      </td>
                      <td className={adminStyles.cellStrong}>{enrolment.student_name}</td>
                      <td>
                        {submission ? (
                          <>
                            {submission.file_url ? (
                              <a
                                className={styles.fileLink}
                                href={submission.file_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {submission.original_filename || "Download file"}
                              </a>
                            ) : (
                              <span>{submission.original_filename || "File submitted"}</span>
                            )}
                            <span className={styles.submissionMeta}>
                              {fmtDateTime(submission.submitted_at)}
                              {submission.is_late ? " · " : ""}
                              {submission.is_late ? <Badge tone="warning">Late</Badge> : null}
                            </span>
                          </>
                        ) : (
                          <span className={adminStyles.cellMuted}>No submission</span>
                        )}
                      </td>
                      <td>
                        {grade ? (
                          <>
                            <span className={styles.scoreChip}>{fmtPoints(grade.score)}</span>{" "}
                            {grade.is_released ? <Badge tone="success">Released</Badge> : null}
                          </>
                        ) : (
                          <span className={adminStyles.cellMuted}>—</span>
                        )}
                      </td>
                      <td className={adminStyles.rowActions}>
                        <button
                          type="button"
                          className={adminStyles.textBtn}
                          onClick={() => setGradingStudent(enrolment)}
                        >
                          {grade ? "Edit grade" : "Grade"}
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

      {gradingStudent && item ? (
        <GradeModal
          item={item}
          enrolment={gradingStudent}
          submission={submissionByStudent.get(gradingStudent.student) ?? null}
          existing={grades.get(gradingStudent.student) ?? null}
          token={token}
          onClose={() => setGradingStudent(null)}
          onSaved={(grade) => {
            setGrades((prev) => new Map(prev).set(grade.student, grade));
            setGradingStudent(null);
          }}
        />
      ) : null}
    </div>
  );
}

function GradeModal({
  item,
  enrolment,
  submission,
  existing,
  token,
  onClose,
  onSaved,
}: {
  item: AssessmentItem;
  enrolment: Enrolment;
  submission: AssessmentSubmission | null;
  existing: AssessmentGrade | null;
  token: string;
  onClose: () => void;
  onSaved: (grade: AssessmentGrade) => void;
}) {
  const [score, setScore] = useState(existing ? existing.score : "");
  const [feedback, setFeedback] = useState(existing?.feedback ?? "");
  const [release, setRelease] = useState(existing?.is_released ?? false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);
  const [confirmRelease, setConfirmRelease] = useState(false);

  const maxScore = Number(item.max_score);

  function validate(): boolean {
    if (score.trim() === "" || Number.isNaN(Number(score))) {
      setErrors({ score: ["Enter a score."] });
      return false;
    }
    if (Number(score) < 0 || Number(score) > maxScore) {
      setErrors({ score: [`Score must be between 0 and ${fmtPoints(item.max_score)}.`] });
      return false;
    }
    return true;
  }

  async function save() {
    setSaving(true);
    setMessage(null);
    setErrors(null);
    try {
      const grade = await gradeStudent(
        item.id,
        { student: enrolment.student, score, feedback, is_released: release },
        token,
      );
      onSaved(grade);
    } catch (err) {
      setConfirmRelease(false);
      if (err instanceof ApiError) {
        setMessage(err.message);
        setErrors(err.fieldErrors);
      } else {
        setMessage("Could not record the grade.");
      }
      setSaving(false);
    }
  }

  function onSubmit() {
    setErrors(null);
    setMessage(null);
    if (!validate()) return;
    if (release && !existing?.is_released) {
      setConfirmRelease(true);
      return;
    }
    void save();
  }

  return (
    <Modal
      title={`Grade ${enrolment.student_name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={saving} onClick={onSubmit}>
            {existing ? "Update grade" : "Save grade"}
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

        <div className={styles.submissionCard}>
          <span className={styles.submissionCardTitle}>Submission</span>
          {submission ? (
            <>
              {submission.file_url ? (
                <a
                  className={styles.fileLink}
                  href={submission.file_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {submission.original_filename || "Download file"}
                </a>
              ) : (
                <span>{submission.original_filename || "File submitted"}</span>
              )}
              <span className={styles.submissionMeta}>
                Submitted {fmtDateTime(submission.submitted_at)}
                {submission.is_late ? " — after the deadline" : ""}
              </span>
              {submission.is_late ? <Badge tone="warning">Late</Badge> : null}
            </>
          ) : (
            <span className={adminStyles.cellMuted}>
              No file was submitted for this item — you can still record a score (for example, an
              in-class test).
            </span>
          )}
        </div>

        <label className={adminStyles.formFull}>
          <span className={adminStyles.fieldLabel}>
            Score (out of {fmtPoints(item.max_score)}) <span className={adminStyles.req}>*</span>
          </span>
          <input
            className={adminStyles.input}
            type="number"
            inputMode="decimal"
            min={0}
            max={maxScore}
            step="0.01"
            value={score}
            onChange={(e) => setScore(e.target.value)}
            aria-invalid={firstError(errors, "score") ? true : undefined}
          />
          {firstError(errors, "score", "student") ? (
            <span className={adminStyles.pageSub}>{firstError(errors, "score", "student")}</span>
          ) : null}
        </label>

        <label className={adminStyles.formFull}>
          <span className={adminStyles.fieldLabel}>Feedback</span>
          <textarea
            className={styles.textarea}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="What went well, what to improve…"
          />
          {firstError(errors, "feedback") ? (
            <span className={adminStyles.pageSub}>{firstError(errors, "feedback")}</span>
          ) : null}
        </label>

        <div className={styles.checkboxText}>
          <label className={styles.checkboxRow}>
            <input
              type="checkbox"
              checked={release}
              onChange={(e) => setRelease(e.target.checked)}
            />
            <span className={styles.checkboxLabel}>Release to student</span>
          </label>
          <span className={styles.checkboxHint}>
            The student sees the score and feedback immediately. Unreleased grades still count
            towards the aggregated CA.
          </span>
        </div>
      </div>

      {confirmRelease ? (
        <ConfirmDialog
          title="Release this grade to the student?"
          message={`${enrolment.student_name} will immediately see ${fmtPoints(score || "0")} / ${fmtPoints(item.max_score)} and your feedback for “${item.title}”. Once graded, their submission can no longer be replaced.`}
          confirmLabel={saving ? "Releasing…" : "Release grade"}
          loading={saving}
          error={null}
          onConfirm={() => void save()}
          onCancel={() => setConfirmRelease(false)}
        />
      ) : null}
    </Modal>
  );
}
