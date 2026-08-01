import { apiRequest, withQuery } from "./api";
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
  return apiRequest<Page<AcademicStanding>>(withQuery(`${GRADING}/standings`, params), {
    token,
  }).then((r) => r.data ?? (EMPTY_PAGE as Page<AcademicStanding>));
}

export function myStanding(token: string, params: { session?: string; semester?: string } = {}) {
  return apiRequest<StudentStanding>(withQuery(`${GRADING}/my-standing`, params), {
    token,
  }).then((r) => r.data as StudentStanding);
}
