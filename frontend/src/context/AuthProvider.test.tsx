import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../services/api";

const refresh = vi.fn();
const logout = vi.fn();
vi.mock("../services/auth", () => ({
  login: (...args: unknown[]) => login(...args),
  logout: (...args: unknown[]) => logout(...args),
  refresh: () => refresh(),
}));

const login = vi.fn();
const getMe = vi.fn();
vi.mock("../services/accounts", () => ({
  getMe: (...args: unknown[]) => getMe(...args),
}));

import { AuthProvider } from "./AuthProvider";
import { useAuth } from "../hooks";

// A token whose payload decodes to {"user_id": "user-1"}.
const TOKEN = `header.${btoa(JSON.stringify({ user_id: "user-1" }))}.signature`;

function Probe() {
  const { status, user } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="role">{user?.role ?? "none"}</span>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  refresh.mockResolvedValue({
    status: "success",
    data: { access: TOKEN },
    message: "",
    errors: null,
  });
});

describe("AuthProvider", () => {
  it("signs the session out when the profile call rejects the token", async () => {
    getMe.mockRejectedValue(new ApiError("Unauthorized", 401, null));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(await screen.findByText("unauthenticated")).toBeTruthy();
    expect(screen.getByTestId("role").textContent).toBe("none");
  });

  it("keeps the session on a transient profile failure", async () => {
    getMe.mockRejectedValue(new ApiError("Network error.", 0, null));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(await screen.findByText("authenticated")).toBeTruthy();
  });

  it("uses the profile role once the call succeeds", async () => {
    getMe.mockResolvedValue({
      id: "user-1",
      email: "lecturer@example.edu",
      full_name: "A Lecturer",
      role: "lecturer",
      institution_name: "Veritas",
      department: null,
      department_name: null,
      faculty: null,
      faculty_name: null,
    });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(await screen.findByText("lecturer")).toBeTruthy();
  });
});
