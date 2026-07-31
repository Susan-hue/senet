import { Link } from "react-router-dom";
import { Badge, EmptyState, ErrorState, SkeletonTable } from "../../components/admin";
import { RESULT_STATUS_META } from "../../types";
import type { CourseResult, Page } from "../../types";
import { Pager } from "../admin/ui";
import adminStyles from "../admin/admin.module.css";
import styles from "./board.module.css";

function relativeDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export interface WorklistSelection {
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[]) => void;
}

/**
 * The paginated list of sheets a board has drilled to. Never rendered unscoped:
 * the page gates it behind the scope drill and passes only one page at a time.
 */
export function WorklistPanel({
  page,
  loading,
  error,
  onRetry,
  onPage,
  detailPath,
  emptyTitle,
  emptyHint,
  showDepartment = false,
  selection,
}: {
  page: Page<CourseResult> | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onPage: (page: number) => void;
  /** Builds the sheet detail route for this board. */
  detailPath: (result: CourseResult) => string;
  emptyTitle: string;
  emptyHint: string;
  showDepartment?: boolean;
  selection?: WorklistSelection;
}) {
  if (loading) return <SkeletonTable rows={6} cols={showDepartment ? 6 : 5} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;

  const rows = page?.results ?? [];
  if (rows.length === 0) return <EmptyState title={emptyTitle} hint={emptyHint} />;

  const ids = rows.map((r) => r.id);
  const allSelected = selection ? ids.every((id) => selection.selected.has(id)) : false;

  return (
    <>
      <div className={adminStyles.tableWrap}>
        <table className={adminStyles.table}>
          <thead>
            <tr>
              {selection ? (
                <th className={styles.checkCell}>
                  <input
                    type="checkbox"
                    className={styles.check}
                    checked={allSelected}
                    onChange={() => selection.onToggleAll(ids)}
                    aria-label="Select every sheet on this page"
                  />
                </th>
              ) : null}
              <th>Course</th>
              {showDepartment ? <th>Department</th> : null}
              <th>Term</th>
              <th>Lecturer</th>
              <th>State</th>
              <th>Submitted</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((result) => {
              const meta = RESULT_STATUS_META[result.status];
              const checked = selection?.selected.has(result.id) ?? false;
              return (
                <tr key={result.id} className={checked ? styles.rowSelected : undefined}>
                  {selection ? (
                    <td className={styles.checkCell}>
                      <input
                        type="checkbox"
                        className={styles.check}
                        checked={checked}
                        onChange={() => selection.onToggle(result.id)}
                        aria-label={`Select ${result.course_code}`}
                      />
                    </td>
                  ) : null}
                  <td>
                    <Link to={detailPath(result)} className={styles.courseLink}>
                      <span className={styles.courseCode}>{result.course_code}</span>
                      <span className={styles.courseTitle}>{result.course_title}</span>
                    </Link>
                  </td>
                  {showDepartment ? (
                    <td className={adminStyles.cellMuted}>{result.department_name}</td>
                  ) : null}
                  <td className={adminStyles.cellMuted}>
                    {result.session_name} · {result.semester_name}
                  </td>
                  <td className={adminStyles.cellMuted}>{result.lecturer_name}</td>
                  <td>
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                  </td>
                  <td className={adminStyles.cellMuted}>{relativeDate(result.updated_at)}</td>
                  <td>
                    <div className={adminStyles.rowActions}>
                      <Link to={detailPath(result)} className={adminStyles.textBtn}>
                        Review
                      </Link>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {page ? (
        <Pager
          page={page.page}
          totalPages={page.total_pages}
          count={page.count}
          label="sheets"
          onPage={onPage}
        />
      ) : null}
    </>
  );
}
