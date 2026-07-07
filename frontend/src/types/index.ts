export interface ApiEnvelope<T> {
  status: "success" | "error";
  data: T | null;
  message: string;
  errors: Record<string, string[]> | null;
}

export interface Page<T> {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  results: T[];
}

export const EMPTY_PAGE = {
  count: 0,
  page: 1,
  page_size: 25,
  total_pages: 1,
  results: [],
};

export type Role =
  | "student"
  | "course_rep"
  | "lecturer"
  | "course_adviser"
  | "dean"
  | "hod"
  | "exam_officer"
  | "senate_admin"
  | "school_admin"
  | "super_admin";

export const ROLE_OPTIONS = [
  { value: "student", label: "Student" },
  { value: "course_rep", label: "Course Rep" },
  { value: "lecturer", label: "Lecturer" },
  { value: "course_adviser", label: "Course Adviser" },
  { value: "dean", label: "Dean" },
  { value: "hod", label: "HOD" },
  { value: "exam_officer", label: "Exam Officer" },
] as const satisfies ReadonlyArray<{ value: Role; label: string }>;

export interface AuthUser {
  id: string;
  email: string | null;
  fullName: string;
  role: Role | null;
  institutionName: string | null;
  departmentId: string | null;
}

export interface RegisterPayload {
  email: string;
  full_name: string;
  password: string;
  role: Role;
}

export interface RegisterData {
  id: string;
  email: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface TokenData {
  access: string;
}

export interface CurrentUser {
  id: string;
  email: string | null;
  full_name: string;
  role: Role;
  institution_id: string | null;
  institution_name: string | null;
  department: string | null;
  department_name: string | null;
  faculty: string | null;
  faculty_name: string | null;
  current_level: number | null;
  identifier: string;
  is_verified: boolean;
}

export const LEVEL_OPTIONS = [
  { value: "100", label: "100 Level" },
  { value: "200", label: "200 Level" },
  { value: "300", label: "300 Level" },
  { value: "400", label: "400 Level" },
  { value: "500", label: "500 Level" },
  { value: "600", label: "600 Level" },
] as const;

export const ADMIN_ROLES: Role[] = ["school_admin", "super_admin"];

// --------------------------------------------------------------------------- //
// Academic structure                                                          //
// --------------------------------------------------------------------------- //

export interface Faculty {
  id: string;
  institution: string;
  name: string;
  code: string;
  created_at: string;
  updated_at: string;
}

export interface Department {
  id: string;
  institution: string;
  faculty: string;
  name: string;
  code: string;
  created_at: string;
  updated_at: string;
}

export interface Programme {
  id: string;
  institution: string;
  department: string;
  name: string;
  code: string;
  degree_type: string;
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: string;
  institution: string;
  name: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  created_at: string;
  updated_at: string;
}

export interface Semester {
  id: string;
  institution: string;
  session: string;
  name: string;
  start_date: string;
  end_date: string;
  created_at: string;
  updated_at: string;
}

export interface Course {
  id: string;
  institution: string;
  department: string;
  code: string;
  title: string;
  credit_units: number;
  level: number | null;
  ca_weight: number | null;
  exam_weight: number | null;
  effective_ca_weight: number;
  effective_exam_weight: number;
  created_at: string;
  updated_at: string;
}

export interface Person {
  id: string;
  email: string | null;
  full_name: string;
  role: Role;
  department: string | null;
  department_name: string | null;
  current_level: number | null;
  identifier: string;
  rank: string | null;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface InstitutionConfig {
  lecturer_ranks: string[];
}

export const ROLE_META: Record<
  Role,
  { label: string; tone: "neutral" | "accent" | "violet" | "success" | "warning" }
> = {
  student: { label: "Student", tone: "accent" },
  course_rep: { label: "Course Rep", tone: "accent" },
  lecturer: { label: "Lecturer", tone: "violet" },
  course_adviser: { label: "Course Adviser", tone: "violet" },
  dean: { label: "Dean", tone: "success" },
  hod: { label: "HOD", tone: "success" },
  exam_officer: { label: "Exam Officer", tone: "success" },
  senate_admin: { label: "Senate Admin", tone: "warning" },
  school_admin: { label: "Admin", tone: "warning" },
  super_admin: { label: "Super Admin", tone: "warning" },
};

export const PERSON_ROLE_OPTIONS = [
  "student",
  "course_rep",
  "lecturer",
  "course_adviser",
  "hod",
  "dean",
  "exam_officer",
  "senate_admin",
  "school_admin",
] as const satisfies ReadonlyArray<Role>;

export interface CourseAssignment {
  id: string;
  institution: string;
  lecturer: string;
  lecturer_name: string;
  course: string;
  course_code: string;
  course_title: string;
  session: string;
  semester: string;
  created_at: string;
  updated_at: string;
}

// --------------------------------------------------------------------------- //
// Bulk import                                                                 //
// --------------------------------------------------------------------------- //

export type ImportKind = "students" | "courses" | "assignments";

export interface ImportRowError {
  row: number;
  errors: string[];
}

export interface ImportSummary {
  total_rows: number;
  created: number;
  skipped: number;
}

export interface ImportJob {
  id: string;
  kind: string;
  status: "pending" | "processing" | "completed" | "failed";
  filename: string;
  total_rows: number;
  created_count: number;
  skipped_count: number;
  errors: ImportRowError[] | null;
  message: string;
  created_at: string;
  updated_at: string;
}

export interface QueuedImport {
  job_id: string;
  status: string;
}

export type ImportOutcome =
  | { kind: "sync"; summary: ImportSummary; message: string; errors: ImportRowError[] | null }
  | { kind: "queued"; jobId: string };

// --------------------------------------------------------------------------- //
// Results pipeline                                                            //
// --------------------------------------------------------------------------- //

export type ResultStatus =
  | "draft"
  | "submitted_to_hod"
  | "approved_by_hod"
  | "approved_by_dean"
  | "ratified_by_senate"
  | "returned";

export interface CourseResult {
  id: string;
  institution: string;
  course: string;
  course_code: string;
  course_title: string;
  session: string;
  semester: string;
  lecturer: string;
  lecturer_name: string;
  status: ResultStatus;
  returned_reason: string;
  created_at: string;
  updated_at: string;
}

export interface StudentScore {
  id: string;
  student: string;
  student_name: string;
  student_identifier: string;
  ca_score: string;
  exam_score: string;
  total: string;
  grade: string;
  is_current: boolean;
  created_at: string;
  updated_at: string;
}

export interface CourseResultDetail extends CourseResult {
  scores: StudentScore[];
}

export interface Enrolment {
  id: string;
  institution: string;
  student: string;
  student_name: string;
  student_identifier: string;
  course: string;
  session: string;
  semester: string;
  created_at: string;
  updated_at: string;
}

export const RESULT_STATUS_META: Record<
  ResultStatus,
  {
    label: string;
    tone: "neutral" | "accent" | "violet" | "success" | "warning" | "danger";
    hint: string;
  }
> = {
  draft: { label: "Draft", tone: "neutral", hint: "Editable — not yet submitted." },
  submitted_to_hod: {
    label: "Submitted · awaiting HOD",
    tone: "accent",
    hint: "Locked for editing while your HOD reviews it.",
  },
  approved_by_hod: {
    label: "Approved by HOD",
    tone: "violet",
    hint: "Locked — moving through faculty approval.",
  },
  approved_by_dean: {
    label: "Approved by Dean",
    tone: "violet",
    hint: "Locked — awaiting senate ratification.",
  },
  ratified_by_senate: {
    label: "Ratified by Senate",
    tone: "success",
    hint: "Final. Changes now require a formal amendment.",
  },
  returned: {
    label: "Returned",
    tone: "danger",
    hint: "Sent back for corrections — edit and resubmit.",
  },
};

export const LECTURER_ROLES: Role[] = ["lecturer"];
