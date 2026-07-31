import { apiRequest } from "./api";
import type { AcademicStanding, Page, StudentStanding } from "../types";
import { EMPTY_PAGE } from "../types";

const GRADING = "/api/v1/grading";

export interface StandingListParams {
  page?: number;
  page_size?: number;
  department?: string;
  session?: string;
  semester?: string;
}

/**
 * Computed standings for a department and term, role-scoped by the backend.
 * The Faculty Board reads these alongside a broadsheet so a sheet is vetted
 * against what it does to each student's CGPA, not just its own spread.
 */
export function listStandings(token: string, params: StandingListParams = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const qs = search.toString();
  return apiRequest<Page<AcademicStanding>>(
    qs ? `${GRADING}/standings?${qs}` : `${GRADING}/standings`,
    { token },
  ).then((r) => r.data ?? (EMPTY_PAGE as Page<AcademicStanding>));
}

export function myStanding(token: string, params: { session?: string; semester?: string } = {}) {
  const search = new URLSearchParams();
  if (params.session) search.set("session", params.session);
  if (params.semester) search.set("semester", params.semester);
  const qs = search.toString();
  return apiRequest<StudentStanding>(
    qs ? `${GRADING}/my-standing?${qs}` : `${GRADING}/my-standing`,
    {
      token,
    },
  ).then((r) => r.data as StudentStanding);
}
