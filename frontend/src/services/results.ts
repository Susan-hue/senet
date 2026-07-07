import { apiRequest } from "./api";
import type { CourseResult, CourseResultDetail, Page, StudentScore } from "../types";
import { EMPTY_PAGE } from "../types";

const RESULTS = "/api/v1/results";

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
