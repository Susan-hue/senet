import { useEffect, useRef, useState } from "react";
import { Alert, Button } from "../../components";
import { ApiError } from "../../services/api";
import { getImportJob, runImport } from "../../services/accounts";
import type { ImportKind, ImportRowError } from "../../types";
import { useAuth } from "../../hooks";
import { PageHeader } from "./ui";
import { UploadIcon } from "./adminIcons";
import { recordImport } from "./importHistory";
import styles from "./admin.module.css";
import ux from "./imports.module.css";

interface TypeDef {
  kind: ImportKind;
  title: string;
  desc: string;
  columns: string[];
}

const TYPES: TypeDef[] = [
  {
    kind: "students",
    title: "Students",
    desc: "Matric no, names, department, level",
    columns: ["full_name", "email", "matric_number", "department_code", "current_level"],
  },
  {
    kind: "courses",
    title: "Courses",
    desc: "Code, title, units, level, weights",
    columns: [
      "code",
      "title",
      "credit_units",
      "level",
      "department_code",
      "ca_weight",
      "exam_weight",
    ],
  },
  {
    kind: "assignments",
    title: "Lecturer assignments",
    desc: "Lecturer email, course code, term",
    columns: ["lecturer_email", "lecturer_identifier", "course_code", "session", "semester"],
  },
];

interface Result {
  filename: string;
  total: number;
  created: number;
  skipped: number;
  message: string;
  errors: ImportRowError[];
}

type Phase =
  | { name: "idle" }
  | { name: "working"; note: string }
  | { name: "done"; result: Result }
  | { name: "error"; message: string };

function extOf(filename: string) {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : "csv";
}

export function ImportsPage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";

  const [kind, setKind] = useState<ImportKind>("students");
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | null>(null);
  const activeType = TYPES.find((t) => t.kind === kind)!;

  useEffect(
    () => () => {
      if (pollRef.current) window.clearTimeout(pollRef.current);
    },
    [],
  );

  function finish(filename: string, r: Omit<Result, "filename">, statusPartial: boolean) {
    const result: Result = { filename, ...r };
    setPhase({ name: "done", result });
    recordImport({
      id: `${filename}-${Date.now()}`,
      filename,
      kind,
      ext: extOf(filename),
      created: r.created,
      skipped: r.skipped,
      status: statusPartial ? "partial" : "complete",
      at: Date.now(),
    });
  }

  function pollJob(jobId: string, filename: string) {
    getImportJob(jobId, token)
      .then((job) => {
        if (job.status === "completed" || job.status === "failed") {
          finish(
            filename,
            {
              total: job.total_rows,
              created: job.created_count,
              skipped: job.skipped_count,
              message: job.message || `${job.created_count} created, ${job.skipped_count} skipped.`,
              errors: job.errors ?? [],
            },
            job.status === "failed" || job.skipped_count > 0,
          );
          return;
        }
        setPhase({ name: "working", note: "Processing a large file — this can take a moment…" });
        pollRef.current = window.setTimeout(() => pollJob(jobId, filename), 1500);
      })
      .catch((err) => {
        setPhase({
          name: "error",
          message: err instanceof ApiError ? err.message : "Lost track of the import job.",
        });
      });
  }

  async function handleFile(file: File) {
    setPhase({ name: "working", note: "Uploading and validating rows…" });
    try {
      const outcome = await runImport(kind, file, token);
      if (outcome.kind === "queued") {
        setPhase({ name: "working", note: "Queued for processing…" });
        pollJob(outcome.jobId, file.name);
      } else {
        finish(
          file.name,
          {
            total: outcome.summary.total_rows,
            created: outcome.summary.created,
            skipped: outcome.summary.skipped,
            message: outcome.message,
            errors: outcome.errors ?? [],
          },
          outcome.summary.skipped > 0,
        );
      }
    } catch (err) {
      setPhase({
        name: "error",
        message: err instanceof ApiError ? err.message : "The import could not be processed.",
      });
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  }

  function downloadTemplate() {
    const header = activeType.columns.join(",");
    const blob = new Blob([`${header}\n`], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${activeType.kind}_template.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const busy = phase.name === "working";

  return (
    <div className={styles.page}>
      <PageHeader
        title="Bulk import"
        subtitle="Upload a CSV or XLSX to create many records at once. Rows with problems are skipped and reported — everything else imports."
      />

      <div className={ux.typeGrid}>
        {TYPES.map((t) => (
          <button
            key={t.kind}
            type="button"
            className={[ux.typeCard, kind === t.kind ? ux.typeCardActive : ""].join(" ")}
            onClick={() => {
              if (busy) return;
              setKind(t.kind);
              setPhase({ name: "idle" });
            }}
            aria-pressed={kind === t.kind}
          >
            <div className={ux.typeTitle}>{t.title}</div>
            <div className={ux.typeDesc}>{t.desc}</div>
          </button>
        ))}
      </div>

      {phase.name === "idle" || phase.name === "error" ? (
        <>
          {phase.name === "error" ? <Alert variant="error">{phase.message}</Alert> : null}
          <div
            className={[ux.dropzone, dragOver ? ux.dropzoneOver : ""].join(" ")}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
            }}
          >
            <span className={ux.dropIcon} aria-hidden="true">
              <UploadIcon size={24} />
            </span>
            <div className={ux.dropTitle}>Drop your {activeType.title.toLowerCase()} file here</div>
            <div className={ux.dropHint}>or click to browse — CSV or XLSX, up to 50,000 rows</div>
            <button
              type="button"
              className={ux.templateLink}
              onClick={(e) => {
                e.stopPropagation();
                downloadTemplate();
              }}
            >
              Download the {activeType.title.toLowerCase()} template ↓
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.xlsx"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleFile(file);
                e.target.value = "";
              }}
            />
          </div>
        </>
      ) : null}

      {phase.name === "working" ? (
        <div className={styles.panel}>
          <div className={ux.working}>
            <div className={ux.workingTitle}>Importing {activeType.title.toLowerCase()}</div>
            <div className={ux.workingSub}>{phase.note}</div>
            <div
              className={[ux.track, ux.indeterminate].join(" ")}
              role="progressbar"
              aria-label="Import progress"
            />
          </div>
        </div>
      ) : null}

      {phase.name === "done" ? (
        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>Import complete</h2>
          </div>
          <div className={ux.resultStats}>
            <div className={ux.resultStat}>
              <div className={ux.resultNum}>{phase.result.total}</div>
              <div className={ux.resultLabel}>rows read</div>
            </div>
            <div className={ux.resultStat}>
              <div className={[ux.resultNum, ux.resultNumCreated].join(" ")}>
                {phase.result.created}
              </div>
              <div className={ux.resultLabel}>created</div>
            </div>
            <div className={ux.resultStat}>
              <div className={[ux.resultNum, ux.resultNumSkipped].join(" ")}>
                {phase.result.skipped}
              </div>
              <div className={ux.resultLabel}>skipped</div>
            </div>
          </div>

          {phase.result.errors.length > 0 ? (
            <>
              <div className={ux.errorHead}>
                {phase.result.errors.length} row{phase.result.errors.length === 1 ? "" : "s"}{" "}
                skipped
              </div>
              <div>
                {phase.result.errors.map((row) => (
                  <div key={row.row} className={ux.errorRow}>
                    <span className={ux.rowNum}>Row {row.row}</span>
                    <span className={ux.errorMsgs}>
                      {row.errors.map((msg, i) => (
                        <span key={i} className={ux.errorMsg} style={{ display: "block" }}>
                          {msg}
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          <div className={ux.resetBar}>
            <Button variant="ghost" onClick={() => setPhase({ name: "idle" })}>
              Import another file
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
