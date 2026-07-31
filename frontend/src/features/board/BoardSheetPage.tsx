import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
import { listStandings } from "../../services/grading";
import {
  approveResult,
  downloadResultExport,
  getResult,
  returnResult,
} from "../../services/results";
import { RESULT_STATUS_META } from "../../types";
import type { AcademicStanding, ExportKind } from "../../types";
import { useAsyncData, useDebounced } from "../admin/useAsyncData";
import { PageHeader, Pager, SearchBox } from "../admin/ui";
import { ReturnDialog } from "./ReturnDialog";
import { SheetVetting } from "./SheetVetting";
import adminStyles from "../admin/admin.module.css";
import styles from "./board.module.css";

const PAGE_SIZE = 50;

export type BoardKind = "hod" | "dean" | "senate";

interface BoardCopy {
  /** The route back to this board's worklist. */
  home: string;
  homeLabel: string;
  /** The state a sheet must be in for this board to act on it. */
  actsOn: string;
  approveLabel: string;
  approveTitle: string;
  approveMessage: (course: string, students: number) => string;
  approveConfirm: string;
  approvedToast: string;
  /** The Faculty Board vets a sheet against what it does to each CGPA. */
  showCgpa: boolean;
}

const BOARD: Record<BoardKind, BoardCopy> = {
  hod: {
    home: "/board",
    homeLabel: "Departmental Board",
    actsOn: "submitted_to_hod",
    approveLabel: "Approve — send to Dean",
    approveTitle: "Approve and send to the Dean?",
    approveMessage: (course, students) =>
      `The Departmental Board approves ${course} (${students} student${students === 1 ? "" : "s"}) and passes it to the Faculty Board of Examiners. It leaves your queue and you will not be able to edit or re-approve it.`,
    approveConfirm: "Approve and send",
    approvedToast: "Approved. The sheet has moved to the Dean's queue.",
    showCgpa: false,
  },
  dean: {
    home: "/faculty",
    homeLabel: "Faculty Board",
    actsOn: "approved_by_hod",
    approveLabel: "Approve — send to Senate",
    approveTitle: "Approve and send to Senate?",
    approveMessage: (course, students) =>
      `The Faculty Board of Examiners approves ${course} (${students} student${students === 1 ? "" : "s"}) and passes it to Senate for ratification. It leaves your queue and you will not be able to edit or re-approve it.`,
    approveConfirm: "Approve and send",
    approvedToast: "Approved. The sheet has moved to Senate for ratification.",
    showCgpa: true,
  },
  senate: {
    home: "/senate",
    homeLabel: "Senate Ratification",
    actsOn: "approved_by_dean",
    approveLabel: "Ratify — publish and lock",
    approveTitle: "Ratify, publish and lock this result?",
    approveMessage: (course, students) =>
      `Ratifying ${course} publishes it to all ${students} student${students === 1 ? "" : "s"} immediately and locks the sheet permanently. Ratified results cannot be edited, returned or withdrawn — a correction afterwards requires a formal amendment through the full approval chain. This is Senate's final decision on this result.`,
    approveConfirm: "Ratify and publish",
    approvedToast: "Ratified. The result is published to students and locked.",
    showCgpa: false,
  },
};

export function BoardSheetPage({ board }: { board: BoardKind }) {
  const copy = BOARD[board];
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const { resultId = "" } = useParams();
  const navigate = useNavigate();

  const { data, loading, error, reload } = useAsyncData(
    () => getResult(resultId, token),
    [resultId, token],
  );

  const standings = useAsyncData(async () => {
    if (!copy.showCgpa || !data) return [] as AcademicStanding[];
    const page = await listStandings(token, {
      department: data.department,
      session: data.session,
      semester: data.semester,
      page_size: 100,
    });
    return page.results;
  }, [copy.showCgpa, data, token]);

  const cgpaByStudent = useMemo(() => {
    const map = new Map<string, AcademicStanding>();
    (standings.data ?? []).forEach((row) => map.set(row.student, row));
    return map;
  }, [standings.data]);

  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim().toLowerCase());
  const [page, setPage] = useState(1);

  const [confirmApprove, setConfirmApprove] = useState(false);
  const [confirmReturn, setConfirmReturn] = useState(false);
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [exporting, setExporting] = useState<ExportKind | null>(null);

  const scores = useMemo(() => data?.scores ?? [], [data]);
  const filtered = useMemo(() => {
    if (!search) return scores;
    return scores.filter(
      (s) =>
        s.student_name.toLowerCase().includes(search) ||
        s.student_identifier.toLowerCase().includes(search),
    );
  }, [scores, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const meta = data ? RESULT_STATUS_META[data.status] : null;
  // A sheet only carries actions while it is sitting at this board's stage.
  // Anything else is being viewed for reference — history, or already moved on.
  const actionable = data?.status === copy.actsOn;

  async function doApprove() {
    setWorking(true);
    setActionError(null);
    try {
      await approveResult(resultId, token);
      navigate(copy.home, { state: { toast: `${data?.course_code}: ${copy.approvedToast}` } });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not approve this result.");
      setWorking(false);
    }
  }

  async function doReturn(reason: string) {
    setWorking(true);
    setActionError(null);
    try {
      await returnResult(resultId, reason, token);
      navigate(copy.home, {
        state: { toast: `${data?.course_code}: returned to the lecturer for correction.` },
      });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not return this result.");
      setWorking(false);
    }
  }

  async function doExport(kind: ExportKind) {
    if (exporting) return;
    setExporting(kind);
    setBanner(null);
    const label = kind === "ogr" ? "Grade report" : "Broadsheet";
    try {
      await downloadResultExport(resultId, kind, token, {
        onQueued: () =>
          setBanner("Large class — generating your file. The download will start automatically."),
      });
      setBanner(`${label} downloaded.`);
    } catch (err) {
      setBanner(
        err instanceof ApiError ? err.message : `Could not generate the ${label.toLowerCase()}.`,
      );
    } finally {
      setExporting(null);
    }
  }

  if (loading) {
    return (
      <div className={adminStyles.page}>
        <SkeletonTable rows={8} cols={6} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={adminStyles.page}>
        <ErrorState message={error ?? "This result sheet could not be loaded."} onRetry={reload} />
      </div>
    );
  }

  return (
    <div className={adminStyles.page}>
      <div className={styles.crumbs}>
        <Link to={copy.home} className={styles.crumbLink}>
          {copy.homeLabel}
        </Link>
        <span aria-hidden="true">/</span>
        <span>{data.course_code}</span>
      </div>

      <PageHeader
        title={`${data.course_code} — ${data.course_title}`}
        subtitle={`${data.department_name} · ${data.session_name} ${data.semester_name} semester · submitted by ${data.lecturer_name}`}
        actions={
          <div className={styles.headActions}>
            {meta ? <Badge tone={meta.tone}>{meta.label}</Badge> : null}
            <Button
              variant="ghost"
              onClick={() => void doExport("broadsheet")}
              loading={exporting === "broadsheet"}
              disabled={exporting !== null}
            >
              Broadsheet .xlsx
            </Button>
            <Button
              variant="ghost"
              onClick={() => void doExport("ogr")}
              loading={exporting === "ogr"}
              disabled={exporting !== null}
            >
              Grade report .pdf
            </Button>
          </div>
        }
      />

      {banner ? <Alert variant="info">{banner}</Alert> : null}
      {!actionable ? (
        <Alert variant="info">
          {meta?.hint ?? "This sheet is not awaiting your decision."} You are viewing it for
          reference — no action is available from this board.
        </Alert>
      ) : null}
      {data.status === "returned" && data.returned_reason ? (
        <Alert variant="error">
          <strong>Returned:</strong> {data.returned_reason}
        </Alert>
      ) : null}

      <SheetVetting stats={data.statistics} />

      <section className={adminStyles.panel}>
        <div className={adminStyles.panelHead}>
          <h2 className={adminStyles.panelTitle}>Broadsheet</h2>
          <div className={styles.panelSearch}>
            <SearchBox
              value={query}
              onChange={(v) => {
                setQuery(v);
                setPage(1);
              }}
              placeholder="Search by name or matric number…"
            />
          </div>
        </div>

        {scores.length === 0 ? (
          <EmptyState
            title="No scores on this sheet"
            hint="The lecturer has not recorded any current scores for this course and term."
          />
        ) : filtered.length === 0 ? (
          <EmptyState title="No matching students" hint="Try a different name or matric number." />
        ) : (
          <>
            <div className={adminStyles.tableWrap}>
              <table className={adminStyles.table}>
                <thead>
                  <tr>
                    <th>Matric No.</th>
                    <th>Student</th>
                    <th>CA</th>
                    <th>Exam</th>
                    <th>Total</th>
                    <th>Grade</th>
                    {copy.showCgpa ? <th>CGPA</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => {
                    const standing = cgpaByStudent.get(row.student);
                    return (
                      <tr key={row.id}>
                        <td className={[adminStyles.mono, adminStyles.cellMuted].join(" ")}>
                          {row.student_identifier}
                        </td>
                        <td className={adminStyles.cellStrong}>{row.student_name}</td>
                        <td className={adminStyles.mono}>{row.ca_score}</td>
                        <td className={adminStyles.mono}>{row.exam_score}</td>
                        <td className={[adminStyles.mono, adminStyles.cellStrong].join(" ")}>
                          {row.total}
                        </td>
                        <td>
                          <span className={styles.gradeChip}>{row.grade}</span>
                        </td>
                        {copy.showCgpa ? (
                          <td className={adminStyles.mono}>
                            {standing?.cgpa ?? <span className={adminStyles.cellMuted}>—</span>}
                          </td>
                        ) : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pager
              page={page}
              totalPages={totalPages}
              count={filtered.length}
              label={search ? "matching students" : "students"}
              onPage={setPage}
            />
          </>
        )}
      </section>

      {copy.showCgpa && standings.data !== null && standings.data.length === 0 ? (
        <Alert variant="info">
          No academic standings have been computed for this department and term yet, so the CGPA
          column is empty. Ratified results feed the next computation run.
        </Alert>
      ) : null}

      {actionable ? (
        <div className={styles.actionBar}>
          <span className={styles.actionHint}>
            {board === "senate"
              ? "Ratifying publishes this result to students and locks it permanently."
              : "Approving passes the sheet to the next stage. Returning sends it back to the lecturer with your reason."}
          </span>
          <div className={styles.actionButtons}>
            <Button variant="ghost" onClick={() => setConfirmReturn(true)} disabled={working}>
              Return to lecturer
            </Button>
            <Button onClick={() => setConfirmApprove(true)} disabled={working}>
              {copy.approveLabel}
            </Button>
          </div>
        </div>
      ) : null}

      {confirmApprove ? (
        <ConfirmDialog
          title={copy.approveTitle}
          message={copy.approveMessage(data.course_code, data.statistics.total_students)}
          confirmLabel={copy.approveConfirm}
          tone={board === "senate" ? "danger" : "primary"}
          loading={working}
          error={actionError}
          onConfirm={() => void doApprove()}
          onCancel={() => {
            setConfirmApprove(false);
            setActionError(null);
          }}
        />
      ) : null}

      {confirmReturn ? (
        <ReturnDialog
          title={`Return ${data.course_code} to the lecturer`}
          subject={`${data.course_code} — ${data.course_title}`}
          recipient={data.lecturer_name}
          loading={working}
          error={actionError}
          onConfirm={(reason) => void doReturn(reason)}
          onCancel={() => {
            setConfirmReturn(false);
            setActionError(null);
          }}
        />
      ) : null}
    </div>
  );
}
