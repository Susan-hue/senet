import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Page } from "../../types";

vi.mock("../../hooks", () => ({
  useAuth: () => ({ accessToken: "test-token", user: { role: "lecturer" } }),
}));

const listAssignments = vi.fn();
const listCourses = vi.fn();
const listEnrolments = vi.fn();
vi.mock("../../services/accounts", () => ({
  listAssignments: (...args: unknown[]) => listAssignments(...args),
  listCourses: (...args: unknown[]) => listCourses(...args),
  listEnrolments: (...args: unknown[]) => listEnrolments(...args),
  listSessions: () => Promise.resolve([]),
  listSemesters: () => Promise.resolve([]),
  getCourse: () => Promise.resolve(null),
}));

import { LearningCoursesPage } from "./LearningCoursesPage";

describe("LearningCoursesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAssignments.mockResolvedValue({ count: 0, page: 1, page_size: 25, total_pages: 1, results: [] } as Page<never>);
    listCourses.mockResolvedValue({ count: 0, page: 1, page_size: 25, total_pages: 1, results: [] } as Page<never>);
    listEnrolments.mockResolvedValue([]);
  });

  it("shows an empty state when no assigned courses are available", async () => {
    render(
      <MemoryRouter>
        <LearningCoursesPage role="lecturer" />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/No courses assigned/i)).toBeInTheDocument();
  });
});
