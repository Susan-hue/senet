import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, SkeletonCards, SkeletonTable } from "../../components/admin";
import { Badge } from "../../components/admin";
import { useAuth } from "../../hooks";
import {
  listAssignments,
  listCourses,
  listDepartments,
  listFaculties,
  listProgrammes,
  listUsers,
} from "../../services/accounts";
import { useAsyncData } from "./useAsyncData";
import { loadImportHistory, relativeTime } from "./importHistory";
import { Panel, StatCard } from "./ui";
import styles from "./admin.module.css";

function greetingWord() {
  const h = new Date().getHours();
  if (h < 12) return "morning";
  if (h < 17) return "afternoon";
  return "evening";
}

export function DashboardPage() {
  const { user, accessToken } = useAuth();
  const navigate = useNavigate();
  const token = accessToken ?? "";

  const { data, loading, error, reload } = useAsyncData(
    () =>
      Promise.all([
        listUsers(token),
        listCourses(token),
        listFaculties(token),
        listDepartments(token),
        listProgrammes(token),
        listAssignments(token),
      ]),
    [token],
  );

  const imports = useMemo(() => loadImportHistory(), []);
  const firstName = (user?.fullName || "there").split(/\s+/)[0];

  const stats = useMemo(() => {
    if (!data) return null;
    const [users, courses, faculties, departments, programmes, assignments] = data;
    const students = users.filter((u) => u.role === "student").length;
    const lecturers = users.filter((u) => u.role === "lecturer");
    const assignedLecturers = new Set(assignments.map((a) => a.lecturer));
    const unassigned = lecturers.filter((l) => !assignedLecturers.has(l.id)).length;
    return {
      students,
      courses: courses.length,
      faculties: faculties.length,
      lecturers: lecturers.length,
      unassigned,
      departments: departments.length,
      programmes: programmes.length,
    };
  }, [data]);

  const quickActions = [
    { label: "Add a course", to: "/courses" },
    { label: "Invite a person", to: "/people" },
    { label: "Start a new session", to: "/academic-structure" },
    { label: "Bulk import data", to: "/imports" },
  ];

  return (
    <div className={styles.page}>
      <div>
        <h1 className={styles.greeting}>
          Good {greetingWord()}, {firstName}
        </h1>
        <p className={styles.greetingSub}>
          Here&rsquo;s how {user?.institutionName ?? "your institution"} is running today.
        </p>
      </div>

      {loading ? (
        <SkeletonCards count={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : stats ? (
        <div className={styles.statGrid}>
          <StatCard
            label="Students enrolled"
            value={stats.students.toLocaleString()}
            foot="student accounts"
          />
          <StatCard
            label="Active courses"
            value={stats.courses.toLocaleString()}
            foot={`across ${stats.faculties} ${stats.faculties === 1 ? "faculty" : "faculties"}`}
          />
          <StatCard
            label="Lecturers"
            value={stats.lecturers.toLocaleString()}
            foot={stats.unassigned > 0 ? `${stats.unassigned} unassigned` : "all assigned"}
            tone={stats.unassigned > 0 ? "warning" : "success"}
          />
          <StatCard
            label="Departments"
            value={stats.departments.toLocaleString()}
            foot={`${stats.programmes} ${stats.programmes === 1 ? "programme" : "programmes"}`}
            tone="accent"
          />
        </div>
      ) : null}

      <div className={styles.twoCol}>
        <Panel
          title="Recent imports"
          linkLabel="Go to Bulk Import →"
          onLink={() => navigate("/imports")}
        >
          {imports.length === 0 ? (
            <EmptyState
              title="No imports yet"
              hint="Bulk imports you run will appear here for quick reference."
            />
          ) : (
            <div>
              {imports.map((imp) => (
                <div key={imp.id} className={styles.listRow}>
                  <span className={styles.fileBadge}>{imp.ext.toUpperCase()}</span>
                  <div className={styles.listMain}>
                    <div className={styles.listName}>{imp.filename}</div>
                    <div className={styles.listMeta}>
                      {imp.created} created · {imp.skipped} skipped
                    </div>
                  </div>
                  <div className={styles.listRight}>
                    {imp.status === "complete" ? (
                      <Badge tone="success">Complete</Badge>
                    ) : imp.status === "partial" ? (
                      <Badge tone="warning">Partial</Badge>
                    ) : imp.status === "failed" ? (
                      <Badge tone="danger">Failed</Badge>
                    ) : (
                      <Badge tone="accent">Processing</Badge>
                    )}
                    <span className={styles.listTime}>{relativeTime(imp.at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Quick actions">
          {quickActions.map((a) => (
            <button
              key={a.label}
              type="button"
              className={styles.actionRow}
              onClick={() => navigate(a.to)}
            >
              <span className={styles.actionDot} aria-hidden="true" />
              {a.label}
            </button>
          ))}
        </Panel>
      </div>

      {loading ? (
        <div className={styles.panel}>
          <SkeletonTable rows={3} cols={4} />
        </div>
      ) : null}
    </div>
  );
}
