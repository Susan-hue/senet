import { ApiError, requestFileOrJob, saveBlob } from "./api";
import { apiRequest } from "./api";
import type {
  CourseResult,
  CourseResultDetail,
  ExportJob,
  ExportKind,
  ExternalExaminerReport,
  Page,
  StudentScore,
} from "../types";
import { EMPTY_PAGE } from "../types";

const RESULTS = "/api/v1/results";

const EXPORT_PATH: Record<ExportKind, string> = {
  broadsheet: "broadsheet",
  ogr: "ogr",
};

function withQuery(path: string, params: object) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

/**
 * Scope a listing to one slice of the hierarchy. Result sheets run to the
 * thousands institution-wide, so every board request carries the faculty /
 * department / term it drilled into and a page number — never an unbounded read.
 */
export interface ResultListParams {
  page?: number;
  page_size?: number;
  faculty?: string;
  department?: string;
  session?: string;
  semester?: string;
  course?: string;
  search?: string;
}

export function listResults(token: string, params: ResultListParams = {}) {
  return apiRequest<Page<CourseResult>>(withQuery(RESULTS, params), { token }).then(
    (r) => r.data ?? (EMPTY_PAGE as Page<CourseResult>),
  );
}

/**
 * The sheets awaiting the caller's own decision. The backend picks the stage
 * from their role — HODs get submissions in their department, deans HOD-approved
 * sheets in their faculty, senate admins dean-approved sheets institution-wide —
 * so the same call backs all three boards.
 */
export function listWorklist(token: string, params: ResultListParams = {}) {
  return apiRequest<Page<CourseResult>>(withQuery(`${RESULTS}/worklist`, params), { token }).then(
    (r) => r.data ?? (EMPTY_PAGE as Page<CourseResult>),
  );
}

/** Advance a sheet one stage for the caller's role. */
export function approveResult(resultId: string, token: string) {
  return apiRequest<CourseResult>(`${RESULTS}/${resultId}/approve`, {
    method: "POST",
    token,
  }).then((r) => r.data as CourseResult);
}

/** Send a sheet back to its lecturer. The reason is mandatory server-side too. */
export function returnResult(resultId: string, reason: string, token: string) {
  return apiRequest<CourseResult>(`${RESULTS}/${resultId}/return`, {
    method: "POST",
    body: { reason },
    token,
  }).then((r) => r.data as CourseResult);
}

/**
 * Senate ratification. All-or-nothing on the server: if any sheet in the batch
 * cannot be ratified, none of them are.
 */
export function batchRatify(resultIds: string[], token: string, reason = "") {
  return apiRequest<CourseResult[]>(`${RESULTS}/ratify`, {
    method: "POST",
    body: { result_ids: resultIds, reason },
    token,
  }).then((r) => r.data ?? []);
}

export interface ExaminerReportParams {
  page?: number;
  page_size?: number;
  programme?: string;
  session?: string;
  semester?: string;
}

export function listExaminerReports(token: string, params: ExaminerReportParams = {}) {
  return apiRequest<Page<ExternalExaminerReport>>(
    withQuery(`${RESULTS}/external-examiner-reports`, params),
    { token },
  ).then((r) => r.data ?? (EMPTY_PAGE as Page<ExternalExaminerReport>));
}

export interface ExaminerReportPayload {
  programme: string;
  session: string;
  semester: string;
  examiner_name: string;
  examiner_institution: string;
  audit_date: string;
  remarks: string;
}

export function createExaminerReport(body: ExaminerReportPayload, token: string) {
  return apiRequest<ExternalExaminerReport>(`${RESULTS}/external-examiner-reports`, {
    method: "POST",
    body,
    token,
  }).then((r) => r.data as ExternalExaminerReport);
}

export function getResult(id: string, token: string) {
  return apiRequest<CourseResultDetail>(`${RESULTS}/${id}`, { token }).then(
    (r) => r.data as CourseResultDetail,
  );
}

export function createResult(
  body: { course: string; session: string; semester: string },
  token: string,
) {
  return apiRequest<CourseResult>(RESULTS, { method: "POST", body, token }).then(
    (r) => r.data as CourseResult,
  );
}

export function recordScore(
  resultId: string,
  body: { student: string; ca_score: string | null; exam_score: string },
  token: string,
) {
  return apiRequest<StudentScore>(`${RESULTS}/${resultId}/scores`, {
    method: "POST",
    body,
    token,
  }).then((r) => r.data as StudentScore);
}

export function submitResult(resultId: string, token: string) {
  return apiRequest<CourseResult>(`${RESULTS}/${resultId}/submit`, {
    method: "POST",
    token,
  }).then((r) => r.data as CourseResult);
}

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 2 * 60 * 1000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export interface ExportProgress {
  onQueued?: (job: ExportJob) => void;
}

/**
 * Download a result export. Small classes stream the file immediately; large
 * ones come back as a job that we poll until the worker finishes, then the
 * completed job endpoint streams the file. The browser download is triggered on
 * success and the resolved filename is returned.
 */
export async function downloadResultExport(
  resultId: string,
  kind: ExportKind,
  token: string,
  progress: ExportProgress = {},
): Promise<string> {
  const started = await requestFileOrJob<ExportJob>(
    `${RESULTS}/${resultId}/${EXPORT_PATH[kind]}`,
    token,
  );
  if ("file" in started) {
    saveBlob(started.file);
    return started.file.filename;
  }

  progress.onQueued?.(started.job);
  const jobId = started.job.id;
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await sleep(POLL_INTERVAL_MS);
    const polled = await requestFileOrJob<ExportJob>(`${RESULTS}/export-jobs/${jobId}`, token);
    if ("file" in polled) {
      saveBlob(polled.file);
      return polled.file.filename;
    }
    if (polled.job.status === "failed") {
      throw new ApiError(polled.job.message || "The export could not be generated.", 500, null);
    }
  }
  throw new ApiError("The export is taking longer than expected. Try again shortly.", 0, null);
}
