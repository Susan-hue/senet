import { ApiError, requestFileOrJob, saveBlob } from "./api";
import { apiRequest } from "./api";
import type {
  CourseResult,
  CourseResultDetail,
  ExportJob,
  ExportKind,
  Page,
  StudentScore,
} from "../types";
import { EMPTY_PAGE } from "../types";

const RESULTS = "/api/v1/results";

const EXPORT_PATH: Record<ExportKind, string> = {
  broadsheet: "broadsheet",
  ogr: "ogr",
};

export interface ResultListParams {
  page?: number;
  page_size?: number;
}

export function listResults(token: string, params: ResultListParams = {}) {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return apiRequest<Page<CourseResult>>(qs ? `${RESULTS}?${qs}` : RESULTS, { token }).then(
    (r) => r.data ?? (EMPTY_PAGE as Page<CourseResult>),
  );
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
    const polled = await requestFileOrJob<ExportJob>(
      `${RESULTS}/export-jobs/${jobId}`,
      token,
    );
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
