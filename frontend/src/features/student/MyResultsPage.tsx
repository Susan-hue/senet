import { useMemo, useState } from "react";
import { Alert } from "../../components";
import { Badge, EmptyState, ErrorState, SkeletonTable } from "../../components/admin";
import { useAuth } from "../../hooks";
import { listSemesters, listSessions } from "../../services/accounts";
import { listItems } from "../../services/assessments";
import { myStanding } from "../../services/grading";
import { STANDING_META } from "../../types";
import type { Semester, Session, StandingCourseLine } from "../../types";
import { useAsyncData } from "../admin/useAsyncData";
import { PageHeader, StatCard } from "../admin/ui";
import { AwardIcon } from "../admin/adminIcons";
import adminStyles from "../admin/admin.module.css";
import styles from "./student.module.css";

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

function fmt(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isNaN(n)
    ? String(value)
    : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function MyResultsPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [semesterId, setSemesterId] = useState<string | null>(null);

  const terms = useAsyncData(
    () => Promise.all([listSessions(token), listSemesters(token)]),
    [token],
  );
  const [sessions, semesters] = terms.data ?? [[], []];

  const session = useMemo(() => {
    if (sessionId) return sessions.find((s) => s.id === sessionId) ?? null;
    return sessions.find((s) => s.is_current) ?? sessions[0] ?? null;
  }, [sessions, sessionId]);

  const sessionSemesters = useMemo(
    () => semesters.filter((s) => s.session === session?.id),
    [semesters, session],
  );
  const semester = useMemo(() => {
    if (semesterId) {
      const inSession = sessionSemesters.find((s) => s.id === semesterId);
      if (inSession) return inSession;
    }
    return currentSemesterOf(session, semesters);
  }, [semesterId, sessionSemesters, session, semesters]);

  const standing = useAsyncData(async () => {
    if (!session || !semester) return null;
    // Only the published standing endpoint is queried: the backend aggregates
    // exclusively senate-ratified results into it. Assessment items are used
    // solely to know which enrolled courses are still awaiting publication.
    const [summary, itemsPage] = await Promise.all([
      myStanding(token, { session: session.id, semester: semester.id }),
      listItems(token, { session: session.id, semester: semester.id, page_size: 100 }),
    ]);
    return { summary, items: itemsPage.results };
  }, [token, session?.id, semester?.id]);

  const summary = standing.data?.summary ?? null;
  const published: StandingCourseLine[] = useMemo(() => summary?.term?.courses ?? [], [summary]);

  const awaiting = useMemo(() => {
    const publishedIds = new Set(published.map((c) => c.course));
    const seen = new Map<string, string>();
    (standing.data?.items ?? []).forEach((item) => {
      if (!publishedIds.has(item.course)) seen.set(item.course, item.course_code);
    });
    return [...seen.entries()].map(([course, code]) => ({ course, code }));
  }, [published, standing.data]);

  const standingMeta = summary && summary.standing ? STANDING_META[summary.standing] : null;
  const loading = terms.loading || standing.loading;
  const error = terms.error ?? standing.error;

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="My Results"
        subtitle={
          session && semester
            ? `Published results for ${session.name} · ${semester.name} semester.`
            : "Your published results, GPA and CGPA."
        }
        actions={
          <div className={styles.termPickers}>
            {sessions.length > 1 ? (
              <select
                className={adminStyles.filter}
                value={session?.id ?? ""}
                onChange={(e) => {
                  setSessionId(e.target.value);
                  setSemesterId(null);
                }}
                aria-label="Session"
              >
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            ) : null}
            {sessionSemesters.length > 1 ? (
              <select
                className={adminStyles.filter}
                value={semester?.id ?? ""}
                onChange={(e) => setSemesterId(e.target.value)}
                aria-label="Semester"
              >
                {sessionSemesters.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} semester
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
        <ErrorState message={error} onRetry={terms.error ? terms.reload : standing.reload} />
      ) : !summary ? (
        <EmptyState
          title="No academic terms found"
          hint="Once your institution opens a session, your results will appear here."
          icon={<AwardIcon size={22} />}
        />
      ) : (
        <>
          <div className={adminStyles.statGrid}>
            <StatCard
              label="Semester GPA"
              value={fmt(summary.term?.gpa)}
              foot={`${summary.term?.credit_units ?? 0} credit units this term`}
              tone="accent"
            />
            <StatCard
              label="CGPA"
              value={fmt(summary.cumulative.cgpa)}
              foot={`${summary.cumulative.credit_units} credit units overall`}
              tone="accent"
            />
            <StatCard
              label="Classification"
              value={summary.classification.name ?? "—"}
              foot={
                summary.classification.is_borderline
                  ? `Borderline for ${summary.classification.borderline_band} — Senate review`
                  : "Based on published results only"
              }
              tone={summary.classification.is_borderline ? "warning" : "muted"}
            />
            <div className={styles.standingCard}>
              <span className={styles.standingLabel}>Academic standing</span>
              {standingMeta ? (
                <Badge tone={standingMeta.tone}>{standingMeta.label}</Badge>
              ) : (
                <span className={adminStyles.cellMuted}>Not yet computed</span>
              )}
              <span className={styles.standingFoot}>
                GPA and CGPA are computed by your institution from senate-ratified results and are
                read-only here.
              </span>
            </div>
          </div>

          <div className={styles.noticeBlock}>
            <Alert variant="info">
              Scores appear here only after the Senate ratifies them. Courses marked &ldquo;awaiting
              publication&rdquo; are still moving through lecturer → HOD → Dean → Senate approval.
            </Alert>
          </div>

          {published.length === 0 && awaiting.length === 0 ? (
            <EmptyState
              title="No results for this term yet"
              hint="Nothing has been published for this session and semester, and no course activity was found. Check back after results are ratified."
              icon={<AwardIcon size={22} />}
            />
          ) : (
            <section className={adminStyles.panel}>
              <div className={adminStyles.panelHead}>
                <h2 className={adminStyles.panelTitle}>Courses this term</h2>
              </div>
              <div className={adminStyles.tableWrap}>
                <table className={[adminStyles.table, styles.resultsTable].join(" ")}>
                  <thead>
                    <tr>
                      <th>Course</th>
                      <th>Units</th>
                      <th>Total</th>
                      <th>Grade</th>
                      <th>Grade points</th>
                      <th>Quality points</th>
                    </tr>
                  </thead>
                  <tbody>
                    {published.map((row) => (
                      <tr key={row.course}>
                        <td className={[adminStyles.mono, adminStyles.cellStrong].join(" ")}>
                          {row.course_code}
                        </td>
                        <td className={adminStyles.mono}>{row.credit_units}</td>
                        <td className={adminStyles.mono}>{fmt(row.total_score)}</td>
                        <td>
                          <span className={styles.gradeChip}>{row.grade}</span>
                        </td>
                        <td className={adminStyles.mono}>{fmt(row.grade_points)}</td>
                        <td className={adminStyles.mono}>{fmt(row.quality_points)}</td>
                      </tr>
                    ))}
                    {awaiting.map((row) => (
                      <tr key={row.course} className={styles.awaitingRow}>
                        <td className={[adminStyles.mono, adminStyles.cellStrong].join(" ")}>
                          {row.code}
                        </td>
                        <td className={adminStyles.cellMuted}>—</td>
                        <td className={adminStyles.cellMuted}>—</td>
                        <td colSpan={3}>
                          <Badge tone="neutral">Awaiting publication</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {summary.outstanding_carryovers.length > 0 ? (
            <section className={[adminStyles.panel, styles.carryoverPanel].join(" ")}>
              <div className={adminStyles.panelHead}>
                <h2 className={adminStyles.panelTitle}>Outstanding carryovers</h2>
              </div>
              <ul className={styles.carryoverList}>
                {summary.outstanding_carryovers.map((c) => (
                  <li key={c.code}>
                    <span className={adminStyles.mono}>{c.code}</span> — {c.title}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
