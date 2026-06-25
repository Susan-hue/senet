export interface ApiEnvelope<T> {
  status: "success" | "error";
  data: T | null;
  message: string;
  errors: Record<string, string[]> | null;
}

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
