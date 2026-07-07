import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, EmptyState, ErrorState, SkeletonCards } from "../../components/admin";
import { useAuth } from "../../hooks";
import { listAssignments, listSemesters, listSessions } from "../../services/accounts";
import { listResults } from "../../services/results";
import { RESULT_STATUS_META } from "../../types";
import type { CourseAssignment, CourseResult, Semester, Session } from "../../types";
import { useAsyncData } from "../admin/useAsyncData";
import { PageHeader } from "../admin/ui";
import { BookIcon } from "../admin/adminIcons";
import adminStyles from "../admin/admin.module.css";
import styles from "./results.module.css";

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

export function MyCoursesPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const navigate = useNavigate();
  const [semesterId, setSemesterId] = useState<string | null>(null);

  const { data, loading, error, reload } = useAsyncData(
    () =>
      Promise.all([
        listSessions(token),
        listSemesters(token),
        listAssignments(token),
        listResults(token, { page_size: 100 }),
      ]),
    [token],
  );
  const [sessions, semesters, assignments, resultsPage] = data ?? [[], [], [], null];

  const session = useMemo(
    () => sessions.find((s) => s.is_current) ?? sessions[0] ?? null,
    [sessions],
  );
  const sessionSemesters = useMemo(
    () => semesters.filter((s) => s.session === session?.id),
    [semesters, session],
  );
  const semester = semesterId
    ? (sessionSemesters.find((s) => s.id === semesterId) ?? null)
    : currentSemesterOf(session, semesters);

  const termAssignments = useMemo(
    () => assignments.filter((a) => a.session === session?.id && a.semester === semester?.id),
    [assignments, session, semester],
  );

  const resultByCourse = useMemo(() => {
    const map = new Map<string, CourseResult>();
    (resultsPage?.results ?? []).forEach((r) => {
      map.set(`${r.course}:${r.session}:${r.semester}`, r);
    });
    return map;
  }, [resultsPage]);

  function openSheet(assignment: CourseAssignment) {
    navigate(
      `/teach/sheet?course=${assignment.course}&session=${assignment.session}&semester=${assignment.semester}`,
    );
  }

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="My Courses"
        subtitle={
          session
            ? `Courses you teach in ${session.name}${semester ? ` · ${semester.name} semester` : ""}.`
            : "Courses assigned to you for the current term."
        }
        actions={
          sessionSemesters.length > 1 ? (
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
          ) : null
        }
      />

      {loading ? (
        <SkeletonCards count={3} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : termAssignments.length === 0 ? (
        <EmptyState
          title="No courses assigned this term"
          hint="When your HOD or school admin assigns you a course for this session and semester, it will appear here."
          icon={<BookIcon size={22} />}
        />
      ) : (
        <div className={styles.courseGrid}>
          {termAssignments.map((assignment) => {
            const result = resultByCourse.get(
              `${assignment.course}:${assignment.session}:${assignment.semester}`,
            );
            const meta = result ? RESULT_STATUS_META[result.status] : null;
            return (
              <button
                key={assignment.id}
                type="button"
                className={styles.courseCard}
                onClick={() => openSheet(assignment)}
              >
                <span className={styles.courseCode}>{assignment.course_code}</span>
                <span className={styles.courseTitle}>{assignment.course_title}</span>
                <span className={styles.courseFoot}>
                  {meta ? (
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                  ) : (
                    <Badge tone="neutral">No result sheet yet</Badge>
                  )}
                  <span className={styles.courseCta}>Open sheet →</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
