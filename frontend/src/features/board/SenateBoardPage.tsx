import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, Button } from "../../components";
import { ConfirmDialog, EmptyState, ErrorState } from "../../components/admin";
import { useAuth } from "../../hooks";
import { ApiError } from "../../services/api";
import { batchRatify, listWorklist } from "../../services/results";
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
 * Senate ratification. Institution-wide in principle, but always drilled:
 * faculty, then department, then term. Ratification is the end of the pipeline —
 * it publishes results to students and locks them — so it is confirmed with the
 * exact count and consequence spelled out, whether one sheet or a batch.
 */
export function SenateBoardPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();
  const [toast, setToast] = useState<string | null>(
    (location.state as { toast?: string } | null)?.toast ?? null,
  );

  const scope = useScope(token, {});
  const { faculty, department, session, semester } = scope.scope;

  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim());
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // A faculty and a term are the minimum scope; department narrows further.
  const ready = Boolean(faculty && session && semester);

  useEffect(() => setPage(1), [faculty, department, session, semester, search]);
  // A selection only means anything within the scope it was made in — carrying
  // ids across a scope change would ratify sheets the board is no longer looking at.
  useEffect(() => setSelected(new Set()), [faculty, department, session, semester, search, page]);

  const worklist = useAsyncData(
    () =>
      ready
        ? listWorklist(token, {
            faculty,
            department,
            session,
            semester,
            search,
            page,
            page_size: PAGE_SIZE,
          })
        : Promise.resolve(null),
    [token, ready, faculty, department, session, semester, search, page],
  );

  const rows = worklist.data?.results ?? [];
  const count = worklist.data?.count ?? 0;

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback((ids: string[]) => {
    setSelected((prev) => {
      const all = ids.every((id) => prev.has(id));
      return all ? new Set() : new Set(ids);
    });
  }, []);

  const selectedRows = rows.filter((r) => selected.has(r.id));
  const students = selectedRows.length;

  async function doRatify() {
    setWorking(true);
    setActionError(null);
    try {
      const ratified = await batchRatify([...selected], token);
      setConfirming(false);
      setSelected(new Set());
      setToast(
        `Ratified ${ratified.length} result sheet${ratified.length === 1 ? "" : "s"}. They are published to students and permanently locked.`,
      );
      worklist.reload();
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not ratify the selected sheets. Nothing was changed.",
      );
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="Senate Ratification"
        subtitle="Faculty-approved sheets awaiting Senate's final decision. Ratification publishes results to students and locks them permanently."
      />

      {toast ? <Alert variant="success">{toast}</Alert> : null}

      <ScopeBar scope={scope} levels={["faculty", "department"]} />

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
                {count.toLocaleString()} sheet{count === 1 ? "" : "s"} awaiting ratification
              </span>
            ) : null}
          </div>

          <section className={adminStyles.panel}>
            {!ready ? (
              <EmptyState
                title="Choose a faculty and term"
                hint="Senate ratifies across the whole institution, so start by picking a faculty and a term. Narrow to a single department to ratify one departmental board's results at a time."
              />
            ) : (
              <WorklistPanel
                page={worklist.data}
                loading={worklist.loading}
                error={worklist.error}
                onRetry={worklist.reload}
                onPage={setPage}
                detailPath={(result: CourseResult) => `/senate/sheet/${result.id}`}
                emptyTitle="No sheets awaiting ratification"
                emptyHint="No dean-approved sheets are waiting for this scope. They arrive here once each Faculty Board of Examiners has approved them."
                showDepartment={!department}
                selection={{ selected, onToggle: toggle, onToggleAll: toggleAll }}
              />
            )}
          </section>

          {students > 0 ? (
            <div className={[styles.actionBar, styles.batchBar].join(" ")}>
              <span className={styles.actionHint}>
                <strong className={styles.batchCount}>
                  {students} sheet{students === 1 ? "" : "s"} selected
                </strong>{" "}
                — ratifying publishes them to students and locks them permanently.
              </span>
              <div className={styles.actionButtons}>
                <Button variant="ghost" onClick={() => setSelected(new Set())}>
                  Clear selection
                </Button>
                <Button onClick={() => setConfirming(true)}>
                  Ratify {students} sheet{students === 1 ? "" : "s"}
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}

      {confirming ? (
        <ConfirmDialog
          title={`Ratify ${students} result sheet${students === 1 ? "" : "s"}?`}
          message={`This is Senate's final decision. Ratifying ${selectedRows.map((r) => r.course_code).join(", ")} publishes ${students === 1 ? "it" : "them"} to every affected student immediately and locks ${students === 1 ? "the sheet" : "the sheets"} permanently — they cannot afterwards be edited, returned or withdrawn, and any correction requires a formal amendment through the full approval chain. If any one sheet cannot be ratified, none of them are.`}
          confirmLabel={`Ratify and publish ${students === 1 ? "" : `${students} sheets`}`.trim()}
          loading={working}
          error={actionError}
          onConfirm={() => void doRatify()}
          onCancel={() => {
            setConfirming(false);
            setActionError(null);
          }}
        />
      ) : null}
    </div>
  );
}
