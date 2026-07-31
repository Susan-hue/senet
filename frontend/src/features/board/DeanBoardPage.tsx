import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert } from "../../components";
import { EmptyState, ErrorState } from "../../components/admin";
import { useAuth } from "../../hooks";
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
 * The Faculty Board of Examiners' worklist: HOD-approved sheets from across the
 * dean's faculty. The faculty is pinned to their own, so the drill is
 * department, then term — a faculty spans several departments and a term's worth
 * of sheets from all of them is not a list anyone can read.
 */
export function DeanBoardPage() {
  const { accessToken, user } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();
  const toast = (location.state as { toast?: string } | null)?.toast ?? null;

  const scope = useScope(token, { fixedFaculty: user?.facultyId ?? "" });
  const { department, session, semester } = scope.scope;

  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim());
  const [page, setPage] = useState(1);

  useEffect(() => setPage(1), [department, session, semester, search]);

  const ready = Boolean(department && session && semester);

  const worklist = useAsyncData(
    () =>
      ready
        ? listWorklist(token, {
            department,
            session,
            semester,
            search,
            page,
            page_size: PAGE_SIZE,
          })
        : Promise.resolve(null),
    [token, ready, department, session, semester, search, page],
  );

  const count = worklist.data?.count ?? 0;

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="Faculty Board of Examiners"
        subtitle={
          user?.facultyName
            ? `Sheets approved by the HODs of ${user.facultyName}, awaiting faculty approval.`
            : "Sheets approved by your HODs, awaiting faculty approval."
        }
      />

      {toast ? <Alert variant="success">{toast}</Alert> : null}

      <ScopeBar
        scope={scope}
        levels={["faculty", "department"]}
        lockedFacultyName={user?.facultyName ?? "Your faculty"}
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
            {ready ? (
              <span className={styles.countNote}>
                {count.toLocaleString()} sheet{count === 1 ? "" : "s"} awaiting the board
              </span>
            ) : null}
          </div>

          <section className={adminStyles.panel}>
            {!ready ? (
              <EmptyState
                title="Choose a department and term"
                hint="Your faculty spans several departments. Pick one above, with a session and semester, to see the sheets its HOD has approved."
              />
            ) : (
              <WorklistPanel
                page={worklist.data}
                loading={worklist.loading}
                error={worklist.error}
                onRetry={worklist.reload}
                onPage={setPage}
                detailPath={(result: CourseResult) => `/faculty/sheet/${result.id}`}
                emptyTitle="No sheets awaiting your review"
                emptyHint="No HOD-approved sheets are waiting for this department and term. They appear here as each departmental board approves them."
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}
