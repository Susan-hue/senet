import { apiRequest, apiUpload } from "./api";
import type {
  Course,
  CourseAssignment,
  CurrentUser,
  Department,
  Enrolment,
  Faculty,
  ImportJob,
  ImportKind,
  ImportOutcome,
  ImportRowError,
  ImportSummary,
  InstitutionConfig,
  Page,
  Person,
  Programme,
  QueuedImport,
  Role,
  Semester,
  Session,
} from "../types";
import { EMPTY_PAGE } from "../types";

const ACCOUNTS = "/api/v1/accounts";

type QueryParams = Record<string, string | number | boolean | undefined>;

function withQuery(path: string, params: QueryParams) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

export function getMe(token: string) {
  return apiRequest<CurrentUser>("/api/v1/auth/me", { token }).then((r) => r.data);
}

function listOf<T>(path: string, token: string) {
  return apiRequest<T[]>(path, { token }).then((r) => r.data ?? []);
}

function pageOf<T>(path: string, params: QueryParams, token: string) {
  return apiRequest<Page<T>>(withQuery(path, params), { token }).then(
    (r) => r.data ?? (EMPTY_PAGE as Page<T>),
  );
}

function createOf<T>(path: string, body: unknown, token: string) {
  return apiRequest<T>(path, { method: "POST", body, token }).then((r) => r.data as T);
}

function patchOf<T>(path: string, body: unknown, token: string) {
  return apiRequest<T>(path, { method: "PATCH", body, token }).then((r) => r.data as T);
}

function removeOf(path: string, token: string) {
  return apiRequest<null>(path, { method: "DELETE", token });
}

// --- Faculties ---
export const listFaculties = (t: string) => listOf<Faculty>(`${ACCOUNTS}/faculties`, t);
export const createFaculty = (b: Partial<Faculty>, t: string) =>
  createOf<Faculty>(`${ACCOUNTS}/faculties`, b, t);
export const updateFaculty = (id: string, b: Partial<Faculty>, t: string) =>
  patchOf<Faculty>(`${ACCOUNTS}/faculties/${id}`, b, t);
export const deleteFaculty = (id: string, t: string) => removeOf(`${ACCOUNTS}/faculties/${id}`, t);

// --- Departments ---
export const listDepartments = (t: string) => listOf<Department>(`${ACCOUNTS}/departments`, t);
export const createDepartment = (b: Partial<Department>, t: string) =>
  createOf<Department>(`${ACCOUNTS}/departments`, b, t);
export const updateDepartment = (id: string, b: Partial<Department>, t: string) =>
  patchOf<Department>(`${ACCOUNTS}/departments/${id}`, b, t);
export const deleteDepartment = (id: string, t: string) =>
  removeOf(`${ACCOUNTS}/departments/${id}`, t);

// --- Programmes ---
export const listProgrammes = (t: string) => listOf<Programme>(`${ACCOUNTS}/programmes`, t);
export const createProgramme = (b: Partial<Programme>, t: string) =>
  createOf<Programme>(`${ACCOUNTS}/programmes`, b, t);
export const updateProgramme = (id: string, b: Partial<Programme>, t: string) =>
  patchOf<Programme>(`${ACCOUNTS}/programmes/${id}`, b, t);
export const deleteProgramme = (id: string, t: string) =>
  removeOf(`${ACCOUNTS}/programmes/${id}`, t);

// --- Sessions ---
export const listSessions = (t: string) => listOf<Session>(`${ACCOUNTS}/sessions`, t);
export const createSession = (b: Partial<Session>, t: string) =>
  createOf<Session>(`${ACCOUNTS}/sessions`, b, t);
export const updateSession = (id: string, b: Partial<Session>, t: string) =>
  patchOf<Session>(`${ACCOUNTS}/sessions/${id}`, b, t);
export const deleteSession = (id: string, t: string) => removeOf(`${ACCOUNTS}/sessions/${id}`, t);

// --- Semesters ---
export const listSemesters = (t: string) => listOf<Semester>(`${ACCOUNTS}/semesters`, t);
export const createSemester = (b: Partial<Semester>, t: string) =>
  createOf<Semester>(`${ACCOUNTS}/semesters`, b, t);
export const updateSemester = (id: string, b: Partial<Semester>, t: string) =>
  patchOf<Semester>(`${ACCOUNTS}/semesters/${id}`, b, t);
export const deleteSemester = (id: string, t: string) => removeOf(`${ACCOUNTS}/semesters/${id}`, t);

// --- Institution config ---
export const getInstitutionConfig = (t: string) =>
  apiRequest<InstitutionConfig>(`${ACCOUNTS}/config`, { token: t }).then(
    (r) => r.data ?? { lecturer_ranks: [] },
  );

// --- Courses ---
export interface CourseListParams {
  page?: number;
  page_size?: number;
  faculty?: string;
  department?: string;
  level?: string;
  search?: string;
}
export const listCourses = (t: string, params: CourseListParams = {}) =>
  pageOf<Course>(`${ACCOUNTS}/courses`, params as QueryParams, t);
export const updateCourse = (id: string, b: Partial<Course>, t: string) =>
  patchOf<Course>(`${ACCOUNTS}/courses/${id}`, b, t);
export const createCourse = (b: Partial<Course>, t: string) =>
  createOf<Course>(`${ACCOUNTS}/courses`, b, t);
export const deleteCourse = (id: string, t: string) => removeOf(`${ACCOUNTS}/courses/${id}`, t);

// --- People (users) ---
export interface UserListParams {
  page?: number;
  page_size?: number;
  faculty?: string;
  department?: string;
  role?: Role;
  search?: string;
  is_active?: boolean;
}
export const listUsers = (t: string, params: UserListParams = {}) =>
  pageOf<Person>(`${ACCOUNTS}/users`, params as QueryParams, t);
export const createUser = (b: Partial<Person>, t: string) =>
  createOf<Person>(`${ACCOUNTS}/users`, b, t);
export const updateUser = (id: string, b: Partial<Person>, t: string) =>
  patchOf<Person>(`${ACCOUNTS}/users/${id}`, b, t);

// --- Lecturer assignments ---
export const listAssignments = (t: string) =>
  listOf<CourseAssignment>(`${ACCOUNTS}/assignments`, t);

// --- Enrolments (course rosters) ---
export const listEnrolments = (
  t: string,
  params: { course?: string; session?: string; semester?: string } = {},
) => listOf<Enrolment>(withQuery(`${ACCOUNTS}/enrolments`, params), t);

export const getCourse = (id: string, t: string) =>
  apiRequest<Course>(`${ACCOUNTS}/courses/${id}`, { token: t }).then((r) => r.data as Course);
export const createAssignment = (b: Partial<CourseAssignment>, t: string) =>
  createOf<CourseAssignment>(`${ACCOUNTS}/assignments`, b, t);
export const deleteAssignment = (id: string, t: string) =>
  removeOf(`${ACCOUNTS}/assignments/${id}`, t);

// --- Bulk import ---
const IMPORT_PATH: Record<ImportKind, string> = {
  students: `${ACCOUNTS}/import/students`,
  courses: `${ACCOUNTS}/import/courses`,
  assignments: `${ACCOUNTS}/import/assignments`,
};

export async function runImport(
  kind: ImportKind,
  file: File,
  token: string,
): Promise<ImportOutcome> {
  const envelope = await apiUpload<ImportSummary | QueuedImport>(IMPORT_PATH[kind], file, token);
  const data = envelope.data;
  if (data && "job_id" in data) {
    return { kind: "queued", jobId: data.job_id };
  }
  return {
    kind: "sync",
    summary: data as ImportSummary,
    message: envelope.message,
    errors: (envelope.errors as unknown as ImportRowError[] | null) ?? null,
  };
}

export const getImportJob = (id: string, t: string) =>
  apiRequest<ImportJob>(`${ACCOUNTS}/import/jobs/${id}`, { token: t }).then(
    (r) => r.data as ImportJob,
  );
