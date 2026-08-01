import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, SkeletonCards } from "../../components/admin";
import { PageHeader } from "../admin/ui";
import { useAuth } from "../../hooks";
import {
  listAssignments,
  listCourses,
  listEnrolments,
  listSemesters,
  listSessions,
} from "../../services/accounts";
import { useAsyncData } from "../admin/useAsyncData";
import { BookIcon } from "../admin/adminIcons";
import adminStyles from "../admin/admin.module.css";
import styles from "./lms.module.css";
import type { Course, CourseAssignment, Enrolment, Page, Semester, Session } from "../../types";

function currentSemesterOf(session: Session | null, semesters: Semester[]) {
  if (!session) return null;
  const now = Date.now();
  const inSession = semesters.filter((item) => item.session === session.id);
  return (
    inSession.find(
      (item) => new Date(item.start_date).getTime() <= now && now <= new Date(item.end_date).getTime(),
    ) ??
    inSession[0] ??
    null
  );
}

export function LearningCoursesPage({ role }: { role: "lecturer" | "student" }) {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const navigate = useNavigate();
  const [semesterId, setSemesterId] = useState<string | null>(null);

  const { data, loading, error, reload } = useAsyncData(
    () => Promise.all([listSessions(token), listSemesters(token)]),
    [token],
  );
  const [sessions, semesters] = data ?? [[], []];

  const session = useMemo(
    () => sessions.find((item: Session) => item.is_current) ?? sessions[0] ?? null,
    [sessions],
  );
  const sessionSemesters = useMemo(
    () => semesters.filter((item: Semester) => item.session === session?.id),
    [semesters, session],
  );
  const semester = semesterId
    ? (sessionSemesters.find((item: Semester) => item.id === semesterId) ?? null)
    : currentSemesterOf(session, semesters);

  const rosterData = useAsyncData<Page<CourseAssignment> | Page<Enrolment>>(
    async () => {
      if (!session || !semester) {
        return {
          count: 0,
          page: 1,
          page_size: 0,
          total_pages: 0,
          results: [],
        } as Page<CourseAssignment>;
      }
      if (role === "lecturer") {
        const response = await listAssignments(token, {
          session: session.id,
          semester: semester.id,
          page_size: 100,
        });
        return response;
      }
      const response = await listEnrolments(token, {
        session: session.id,
        semester: semester.id,
      });
      return {
        count: response.length,
        page: 1,
        page_size: response.length,
        total_pages: 1,
        results: response,
      } as Page<Enrolment>;
    },
    [token, role, session?.id, semester?.id],
  );

  const courseData = useAsyncData(
    () => (token ? listCourses(token, { page_size: 200 }) : Promise.resolve(null)),
    [token],
  );

  const courses = useMemo(() => courseData.data?.results ?? [], [courseData.data]);
  const courseById = useMemo(
    () => new Map(courses.map((course: Course) => [course.id, course])),
    [courses],
  );

  const entries = useMemo(() => {
    if (!rosterData.data) return [] as Array<CourseAssignment | Enrolment>;
    if (role === "lecturer") {
      return (rosterData.data as Page<CourseAssignment>).results ?? [];
    }
    return (rosterData.data as Page<Enrolment>).results ?? [];
  }, [rosterData.data, role]);

  const courseLabel = role === "lecturer" ? "courses assigned to you" : "courses you are enrolled in";

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title={role === "lecturer" ? "Teaching courses" : "My courses"}
        subtitle={
          session
            ? `Browse ${courseLabel} in ${session.name}${semester ? ` · ${semester.name} semester` : ""}.`
            : "Your course roster for the active term."
        }
        actions={
          sessionSemesters.length > 1 ? (
            <select
              className={adminStyles.filter}
              value={semester?.id ?? ""}
              onChange={(e) => setSemesterId(e.target.value)}
              aria-label="Semester"
            >
              {sessionSemesters.map((item: Semester) => (
                <option key={item.id} value={item.id}>
                  {item.name} semester
                </option>
              ))}
            </select>
          ) : null
        }
      />

      {loading || rosterData.loading || courseData.loading ? (
        <SkeletonCards count={3} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : rosterData.error ? (
        <ErrorState message={rosterData.error} onRetry={rosterData.reload} />
      ) : courseData.error ? (
        <ErrorState message={courseData.error} onRetry={courseData.reload} />
      ) : entries.length === 0 ? (
        <EmptyState
          title={role === "lecturer" ? "No courses assigned this term" : "No courses enrolled this term"}
          hint={
            role === "lecturer"
              ? "When a course is assigned to you for the current session and semester, it will appear here."
              : "Once you are enrolled in a course for this term, it will appear here."
          }
          icon={<BookIcon size={22} />}
        />
      ) : (
        <div className={styles.courseGrid}>
          {entries.map((entry) => {
            const course =
              role === "lecturer"
                ? (entry as CourseAssignment)
                : courseById.get((entry as Enrolment).course);
            const courseId = role === "lecturer" ? (entry as CourseAssignment).course : (entry as Enrolment).course;
            const courseCode =
              role === "lecturer"
                ? (entry as CourseAssignment).course_code
                : (course as Course | undefined)?.code ?? "Course";
            const courseTitle =
              role === "lecturer"
                ? (entry as CourseAssignment).course_title
                : (course as Course | undefined)?.title ?? "Course";
            return (
              <button
                key={courseId}
                type="button"
                className={styles.courseCard}
                onClick={() =>
                  navigate(
                    role === "lecturer"
                      ? `/teach/courses/${courseId}?session=${session?.id ?? ""}&semester=${semester?.id ?? ""}`
                      : `/me/courses/${courseId}?session=${session?.id ?? ""}&semester=${semester?.id ?? ""}`,
                  )
                }
              >
                <span className={styles.courseCode}>{courseCode}</span>
                <span className={styles.courseTitle}>{courseTitle}</span>
                <span className={styles.courseMeta}>Open learning area →</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
