import { apiRequest } from "./api";
import type { StudentStanding } from "../types";

const GRADING = "/api/v1/grading";

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
