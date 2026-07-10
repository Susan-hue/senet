import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssessmentGrade, AssessmentItem, Enrolment, Page } from "../../types";
import { EMPTY_PAGE } from "../../types";

vi.mock("../../hooks", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

const getItem = vi.fn();
const listGrades = vi.fn();
const listSubmissions = vi.fn();
const gradeStudent = vi.fn();
vi.mock("../../services/assessments", () => ({
  getItem: (...args: unknown[]) => getItem(...args),
  listGrades: (...args: unknown[]) => listGrades(...args),
  listSubmissions: (...args: unknown[]) => listSubmissions(...args),
  gradeStudent: (...args: unknown[]) => gradeStudent(...args),
}));

const listEnrolments = vi.fn();
vi.mock("../../services/accounts", () => ({
  listEnrolments: (...args: unknown[]) => listEnrolments(...args),
}));

import { GradeItemPage } from "./GradeItemPage";

const ITEM: AssessmentItem = {
  id: "item-1",
  institution: "inst-1",
  course: "course-1",
  course_code: "CSC 101",
  course_title: "Intro to Computing",
  session: "session-1",
  semester: "semester-1",
  created_by: "lect-1",
  title: "Assignment 1",
  kind: "assignment",
  max_score: "20.00",
  weight: "20.00",
  due_date: "2026-01-01T00:00:00Z",
  created_at: "2025-12-01T00:00:00Z",
  updated_at: "2025-12-01T00:00:00Z",
};

const ENROLMENT: Enrolment = {
  id: "enr-1",
  institution: "inst-1",
  student: "stud-1",
  student_name: "Ada Lovelace",
  student_identifier: "CSC/2025/001",
  course: "course-1",
  session: "session-1",
  semester: "semester-1",
  created_at: "2025-12-01T00:00:00Z",
  updated_at: "2025-12-01T00:00:00Z",
};

const GRADE: AssessmentGrade = {
  id: "grade-1",
  item: "item-1",
  item_title: "Assignment 1",
  item_max_score: "20.00",
  item_weight: "20.00",
  student: "stud-1",
  student_name: "Ada Lovelace",
  submission: null,
  score: "15.00",
  feedback: "Solid work",
  graded_by: "lect-1",
  is_released: true,
  created_at: "2025-12-05T00:00:00Z",
  updated_at: "2025-12-05T00:00:00Z",
};

function page<T>(results: T[]): Page<T> {
  return { count: results.length, page: 1, page_size: 25, total_pages: 1, results };
}

describe("GradeItemPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getItem.mockResolvedValue(ITEM);
    listEnrolments.mockResolvedValue([ENROLMENT]);
    listSubmissions.mockResolvedValue(EMPTY_PAGE);
  });

  it("shows persisted grades from the server on load", async () => {
    listGrades.mockResolvedValue(page([GRADE]));

    render(
      <MemoryRouter initialEntries={["/teach/assessments/grade?item=item-1"]}>
        <GradeItemPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    // The score cell renders the persisted score and its released badge, not "–".
    expect(await screen.findByText("15")).toBeInTheDocument();
    expect(screen.getByText("Released")).toBeInTheDocument();
    expect(listGrades).toHaveBeenCalledWith("item-1", "test-token", { page_size: 100 });
  });

  it("falls back to a placeholder when no grade has been recorded", async () => {
    listGrades.mockResolvedValue(EMPTY_PAGE);

    render(
      <MemoryRouter initialEntries={["/teach/assessments/grade?item=item-1"]}>
        <GradeItemPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("Released")).not.toBeInTheDocument();
  });
});
