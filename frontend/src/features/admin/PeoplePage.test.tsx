import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Department, Faculty, Page, Person, Role } from "../../types";

vi.mock("../../hooks", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

const listUsers = vi.fn();
vi.mock("../../services/accounts", () => ({
  listUsers: (...args: unknown[]) => listUsers(...args),
  listFaculties: () => Promise.resolve(FACULTIES),
  listDepartments: () => Promise.resolve(DEPARTMENTS),
  getInstitutionConfig: () => Promise.resolve({ lecturer_ranks: [] }),
  createUser: vi.fn(),
  updateUser: vi.fn(),
}));

import { PeoplePage } from "./PeoplePage";

const FACULTIES: Faculty[] = [
  {
    id: "fac-1",
    institution: "inst-1",
    name: "Natural and Applied Sciences",
    code: "NAS",
    created_at: "",
    updated_at: "",
  },
];

const DEPARTMENTS: Department[] = [
  {
    id: "dep-1",
    institution: "inst-1",
    faculty: "fac-1",
    name: "Computer Science",
    code: "CSC",
    created_at: "",
    updated_at: "",
  },
];

function person(id: string, name: string, role: Role): Person {
  return {
    id,
    email: `${id}@veritas.edu.ng`,
    full_name: name,
    role,
    department: "dep-1",
    department_name: "Computer Science",
    current_level: role === "student" ? 100 : null,
    identifier: role === "student" ? "VUA/CSC/21/0001" : "",
    rank: null,
    is_active: true,
    is_verified: true,
    created_at: "",
    updated_at: "",
  };
}

function page<T>(results: T[]): Page<T> {
  return { count: results.length, page: 1, page_size: 25, total_pages: 1, results };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PeoplePage />
    </MemoryRouter>,
  );
}

describe("PeoplePage drill-down", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listUsers.mockResolvedValue(page([person("p1", "Chidi Okafor", "student")]));
  });

  it("lists nobody until a faculty, department and role are chosen", async () => {
    renderPage();

    expect(await screen.findByText("Select a faculty to begin")).toBeInTheDocument();
    expect(listUsers).not.toHaveBeenCalled();

    fireEvent.change(await screen.findByLabelText("Faculty"), { target: { value: "fac-1" } });
    expect(await screen.findByText(/Now select a department/)).toBeInTheDocument();
    expect(listUsers).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Department"), { target: { value: "dep-1" } });
    expect(await screen.findByText("Now select a role")).toBeInTheDocument();
    expect(listUsers).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "student" } });
    expect(await screen.findByText("Chidi Okafor")).toBeInTheDocument();
  });

  it("asks the server for one role inside one department", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Faculty"), { target: { value: "fac-1" } });
    fireEvent.change(screen.getByLabelText("Department"), { target: { value: "dep-1" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "lecturer" } });

    await waitFor(() => expect(listUsers).toHaveBeenCalled());
    const params = listUsers.mock.calls.at(-1)?.[1];
    expect(params).toMatchObject({
      faculty: "fac-1",
      department: "dep-1",
      role: "lecturer",
      is_active: true,
      page_size: 25,
    });
  });
});
