import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert } from "../../components";
import { EmptyState, ErrorState } from "../../components/admin";
import { useAuth } from "../../hooks";
import { listCourses } from "../../services/accounts";
import { listWorklist } from "../../services/results";
import type { CourseResult } from "../../types";
import { useAsyncData, useDebounced } from "../admin/useAsyncData";
import { PageHeader, SearchBox } from "../admin/ui";
import { ScopeBar } from "./ScopeBar";
import { WorklistPanel } from "./WorklistPanel";
import { useScope } from "./useScope";
import adminStyles from "../admin/admin.module.css";
import styles from "./board.module.css";

const PAGE_SIZE = 25;

/**
 * The Departmental Board's worklist: sheets the department's lecturers have
 * submitted, awaiting the HOD's vetting. The department is pinned to the HOD's
 * own — the API scopes it that way too — so the drill here is term, then course.
 */
export function HodBoardPage() {
  const { accessToken, user } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();
  const toast = (location.state as { toast?: string } | null)?.toast ?? null;

  const scope = useScope(token, { fixedDepartment: user?.departmentId ?? "" });
  const { session, semester } = scope.scope;

  const [course, setCourse] = useState("");
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim());
  const [page, setPage] = useState(1);

  // Reset to the first page whenever the scope narrows, so a page-3 view never
  // survives into a filter that has fewer pages.
  useEffect(() => setPage(1), [session, semester, course, search]);

  const courses = useAsyncData(
    () =>
      user?.departmentId
        ? listCourses(token, { department: user.departmentId, page_size: 100 })
        : Promise.resolve(null),
    [token, user?.departmentId],
  );

  const ready = Boolean(session && semester);

  const worklist = useAsyncData(
    () =>
      ready
        ? listWorklist(token, {
            session,
            semester,
            course,
            search,
            page,
            page_size: PAGE_SIZE,
          })
        : Promise.resolve(null),
    [token, ready, session, semester, course, search, page],
  );

  const courseOptions = useMemo(() => courses.data?.results ?? [], [courses.data]);
  const count = worklist.data?.count ?? 0;

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="Departmental Board"
        subtitle={
          user?.departmentName
            ? `Result sheets submitted by ${user.departmentName} lecturers, awaiting your vetting.`
            : "Result sheets submitted by your department's lecturers, awaiting your vetting."
        }
      />

      {toast ? <Alert variant="success">{toast}</Alert> : null}

      <ScopeBar
        scope={scope}
        levels={["department"]}
        lockedDepartmentName={user?.departmentName ?? "Your department"}
      />

      {scope.error ? (
        <ErrorState message={scope.error} onRetry={scope.reload} />
      ) : (
        <>
          <div className={adminStyles.toolbar}>
            <SearchBox
              value={query}
              onChange={setQuery}
              placeholder="Search by course code, title or lecturer…"
            />
            <select
              className={adminStyles.filter}
              value={course}
              onChange={(e) => setCourse(e.target.value)}
              aria-label="Filter by course"
            >
              <option value="">All courses</option>
              {courseOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} — {c.title}
                </option>
              ))}
            </select>
            {ready ? (
              <span className={styles.countNote}>
                {count.toLocaleString()} sheet{count === 1 ? "" : "s"} awaiting you
              </span>
            ) : null}
          </div>

          <section className={adminStyles.panel}>
            {!ready ? (
              <EmptyState
                title="Choose a session and semester"
                hint="Pick the term above to see the sheets your lecturers submitted for it."
              />
            ) : (
              <WorklistPanel
                page={worklist.data}
                loading={worklist.loading}
                error={worklist.error}
                onRetry={worklist.reload}
                onPage={setPage}
                detailPath={(result: CourseResult) => `/board/sheet/${result.id}`}
                emptyTitle="No sheets awaiting your review"
                emptyHint="Nothing has been submitted to you for this term and course filter. Sheets appear here the moment a lecturer submits one."
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}
