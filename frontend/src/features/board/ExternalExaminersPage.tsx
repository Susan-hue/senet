import { useEffect, useMemo, useState } from "react";
import { Alert, Button } from "../../components";
import { EmptyState, ErrorState, Modal, SkeletonTable } from "../../components/admin";
import { useAuth } from "../../hooks";
import { listProgrammes } from "../../services/accounts";
import { createExaminerReport, listExaminerReports } from "../../services/results";
import type { Programme } from "../../types";
import { useAsyncAction, useAsyncData } from "../admin/useAsyncData";
import { PageHeader, Pager, SelectInput, TextInput, firstError } from "../admin/ui";
import { ScopeBar } from "./ScopeBar";
import { useScope } from "./useScope";
import { PlusIcon } from "../admin/adminIcons";
import adminStyles from "../admin/admin.module.css";
import { formatDate } from "../../utils";
import styles from "./board.module.css";

const PAGE_SIZE = 25;

/**
 * The NUC-required record that an external examiner audited a programme for a
 * term. Captured at faculty level by the Dean, alongside the Faculty Board's
 * approvals, because an accreditation visit asks for it per programme per
 * session.
 */
export function ExternalExaminersPage() {
  const { accessToken, user } = useAuth();
  const token = accessToken ?? "";

  const scope = useScope(token, { fixedFaculty: user?.facultyId ?? "" });
  const { department, session, semester } = scope.scope;

  const [page, setPage] = useState(1);
  const [capturing, setCapturing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => setPage(1), [department, session, semester]);

  const programmes = useAsyncData(() => listProgrammes(token), [token]);

  // A dean captures only for their own faculty, so offer only the programmes
  // whose department sits in it.
  const facultyProgrammes = useMemo(() => {
    const inFaculty = new Set(scope.departments.map((d) => d.id));
    return (programmes.data ?? []).filter((p) => inFaculty.has(p.department));
  }, [programmes.data, scope.departments]);

  const programmeOptions = useMemo(
    () =>
      department ? facultyProgrammes.filter((p) => p.department === department) : facultyProgrammes,
    [facultyProgrammes, department],
  );

  const reports = useAsyncData(
    () =>
      listExaminerReports(token, {
        session,
        semester,
        page,
        page_size: PAGE_SIZE,
      }),
    [token, session, semester, page],
  );

  const scopedReports = useMemo(() => {
    const allowed = new Set(programmeOptions.map((p) => p.id));
    const rows = reports.data?.results ?? [];
    return department ? rows.filter((r) => allowed.has(r.programme)) : rows;
  }, [reports.data, programmeOptions, department]);

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title="External Examiners"
        subtitle={
          user?.facultyName
            ? `External examiner audits recorded for ${user.facultyName}.`
            : "External examiner audits recorded for your faculty."
        }
        actions={
          <Button onClick={() => setCapturing(true)} disabled={facultyProgrammes.length === 0}>
            <PlusIcon size={16} /> Record an audit
          </Button>
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
        <section className={adminStyles.panel}>
          {reports.loading ? (
            <SkeletonTable rows={4} cols={5} />
          ) : reports.error ? (
            <ErrorState message={reports.error} onRetry={reports.reload} />
          ) : scopedReports.length === 0 ? (
            <EmptyState
              title="No examiner audits recorded"
              hint="Record each external examiner's visit here as it happens — NUC accreditation asks for one per programme per session."
            />
          ) : (
            <>
              <div className={adminStyles.tableWrap}>
                <table className={adminStyles.table}>
                  <thead>
                    <tr>
                      <th>Examiner</th>
                      <th>Institution</th>
                      <th>Programme</th>
                      <th>Audit date</th>
                      <th>Remarks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scopedReports.map((report) => (
                      <tr key={report.id}>
                        <td className={adminStyles.cellStrong}>{report.examiner_name}</td>
                        <td className={adminStyles.cellMuted}>{report.examiner_institution}</td>
                        <td className={adminStyles.cellMuted}>{report.programme_name}</td>
                        <td className={adminStyles.cellMuted}>{formatDate(report.audit_date)}</td>
                        <td className={styles.remarkCell}>
                          {report.remarks || <span className={adminStyles.cellMuted}>—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {reports.data && !department ? (
                <Pager
                  page={reports.data.page}
                  totalPages={reports.data.total_pages}
                  count={reports.data.count}
                  label="audits"
                  onPage={setPage}
                />
              ) : null}
            </>
          )}
        </section>
      )}

      {capturing ? (
        <ExaminerModal
          programmes={programmeOptions.length > 0 ? programmeOptions : facultyProgrammes}
          defaultSession={session}
          defaultSemester={semester}
          sessions={scope.sessions}
          semesters={scope.semesters}
          token={token}
          onClose={() => setCapturing(false)}
          onSaved={(name) => {
            setCapturing(false);
            setToast(`Recorded ${name}'s audit.`);
            reports.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function ExaminerModal({
  programmes,
  defaultSession,
  defaultSemester,
  sessions,
  semesters,
  token,
  onClose,
  onSaved,
}: {
  programmes: Programme[];
  defaultSession: string;
  defaultSemester: string;
  sessions: ReadonlyArray<{ id: string; name: string }>;
  semesters: ReadonlyArray<{ id: string; name: string }>;
  token: string;
  onClose: () => void;
  onSaved: (examinerName: string) => void;
}) {
  const [programme, setProgramme] = useState(programmes[0]?.id ?? "");
  const [session, setSession] = useState(defaultSession);
  const [semester, setSemester] = useState(defaultSemester);
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState("");
  const [auditDate, setAuditDate] = useState("");
  const [remarks, setRemarks] = useState("");
  const saving = useAsyncAction("Could not record the audit.");
  const { message, errors } = saving;
  const [touched, setTouched] = useState(false);

  const missing =
    !programme || !session || !semester || !name.trim() || !institution.trim() || !auditDate;

  function submit() {
    setTouched(true);
    if (missing) {
      saving.fail("Fill in the examiner, their institution, the programme, term and audit date.");
      return;
    }
    void saving.run(async () => {
      await createExaminerReport(
        {
          programme,
          session,
          semester,
          examiner_name: name.trim(),
          examiner_institution: institution.trim(),
          audit_date: auditDate,
          remarks: remarks.trim(),
        },
        token,
      );
      onSaved(name.trim());
    });
  }

  const required = (value: string, key: string) =>
    firstError(errors, key) ?? (touched && !value ? "Required." : undefined);

  return (
    <Modal
      title="Record an external examiner audit"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={saving.pending} onClick={submit}>
            Record audit
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
        <SelectInput
          label="Programme"
          required
          value={programme}
          onChange={setProgramme}
          placeholder="Select a programme"
          options={programmes.map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))}
          error={required(programme, "programme")}
        />
        <div className={adminStyles.formGrid}>
          <SelectInput
            label="Session"
            required
            value={session}
            onChange={setSession}
            placeholder="Select a session"
            options={sessions.map((s) => ({ value: s.id, label: s.name }))}
            error={required(session, "session")}
          />
          <SelectInput
            label="Semester"
            required
            value={semester}
            onChange={setSemester}
            placeholder="Select a semester"
            options={semesters.map((s) => ({ value: s.id, label: s.name }))}
            error={required(semester, "semester")}
          />
          <TextInput
            label="Examiner name"
            required
            value={name}
            onChange={setName}
            placeholder="Prof. Chinwe Adeyemi"
            error={required(name, "examiner_name")}
          />
          <TextInput
            label="Examiner institution"
            required
            value={institution}
            onChange={setInstitution}
            placeholder="University of Ibadan"
            error={required(institution, "examiner_institution")}
          />
          <TextInput
            label="Audit date"
            required
            type="date"
            value={auditDate}
            onChange={setAuditDate}
            error={required(auditDate, "audit_date")}
          />
        </div>
        <label className={adminStyles.formFull}>
          <span className={adminStyles.fieldLabel}>Remarks</span>
          <textarea
            className={styles.textarea}
            rows={4}
            value={remarks}
            placeholder="The examiner's findings on the question papers, marking and scripts."
            onChange={(e) => setRemarks(e.target.value)}
          />
        </label>
      </div>
    </Modal>
  );
}
