import { apiRequest } from "./api";
import type {
  AssessmentGrade,
  AssessmentItem,
  AssessmentSubmission,
  CaSummaryRow,
  Page,
} from "../types";
import { EMPTY_PAGE } from "../types";

const ASSESSMENTS = "/api/v1/assessments";

type QueryParams = Record<string, string | number | undefined>;

function withQuery(path: string, params: QueryParams) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

export interface ItemListParams {
  course?: string;
  session?: string;
  semester?: string;
  page?: number;
  page_size?: number;
}

export function listItems(token: string, params: ItemListParams = {}) {
  return apiRequest<Page<AssessmentItem>>(
    withQuery(`${ASSESSMENTS}/items`, params as QueryParams),
    { token },
  ).then((r) => r.data ?? (EMPTY_PAGE as Page<AssessmentItem>));
}

export function getItem(id: string, token: string) {
  return apiRequest<AssessmentItem>(`${ASSESSMENTS}/items/${id}`, { token }).then(
    (r) => r.data as AssessmentItem,
  );
}

export interface CreateItemBody {
  course: string;
  session: string;
  semester: string;
  title: string;
  kind: string;
  max_score: string;
  weight: string;
  due_date: string;
}

export function createItem(body: CreateItemBody, token: string) {
  return apiRequest<AssessmentItem>(`${ASSESSMENTS}/items`, {
    method: "POST",
    body,
    token,
  }).then((r) => r.data as AssessmentItem);
}

export function listSubmissions(
  itemId: string,
  token: string,
  params: { page?: number; page_size?: number } = {},
) {
  return apiRequest<Page<AssessmentSubmission>>(
    withQuery(`${ASSESSMENTS}/items/${itemId}/submissions`, params as QueryParams),
    { token },
  ).then((r) => r.data ?? (EMPTY_PAGE as Page<AssessmentSubmission>));
}

export interface GradeBody {
  student: string;
  score: string;
  feedback: string;
  is_released: boolean;
}

export function gradeStudent(itemId: string, body: GradeBody, token: string) {
  return apiRequest<AssessmentGrade>(`${ASSESSMENTS}/items/${itemId}/grade`, {
    method: "POST",
    body,
    token,
  }).then((r) => r.data as AssessmentGrade);
}

export interface CaSummaryParams {
  course: string;
  session: string;
  semester: string;
  page?: number;
  page_size?: number;
}

export function caSummary(token: string, params: CaSummaryParams) {
  return apiRequest<Page<CaSummaryRow>>(
    withQuery(`${ASSESSMENTS}/ca-summary`, params as unknown as QueryParams),
    { token },
  ).then((r) => r.data ?? (EMPTY_PAGE as Page<CaSummaryRow>));
}
