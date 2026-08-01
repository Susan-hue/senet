import { describe, expect, it } from "vitest";
import type { Semester, Session } from "../types";
import { currentSemesterOf, formatNumber } from ".";
import { withQuery } from "../services/api";

const SESSION: Session = {
  id: "session-1",
  institution: "inst-1",
  name: "2024/2025",
  start_date: "2024-09-01",
  end_date: "2025-07-31",
  is_current: true,
  created_at: "2024-09-01T00:00:00Z",
  updated_at: "2024-09-01T00:00:00Z",
};

function semester(id: string, start: string, end: string): Semester {
  return {
    id,
    institution: "inst-1",
    session: SESSION.id,
    name: id,
    start_date: start,
    end_date: end,
    created_at: "2024-09-01T00:00:00Z",
    updated_at: "2024-09-01T00:00:00Z",
  };
}

describe("formatNumber", () => {
  it("renders a decimal string to at most two places", () => {
    expect(formatNumber("12.500")).toBe("12.5");
  });

  it("passes through a value that is not a number", () => {
    expect(formatNumber("n/a")).toBe("n/a");
  });

  it("uses the fallback for an empty value", () => {
    expect(formatNumber(null, "—")).toBe("—");
    expect(formatNumber("", "—")).toBe("—");
  });
});

describe("currentSemesterOf", () => {
  const past = semester("first", "2000-01-01", "2000-06-30");
  const now = semester(
    "second",
    new Date(Date.now() - 86_400_000).toISOString(),
    new Date(Date.now() + 86_400_000).toISOString(),
  );

  it("picks the semester today falls in", () => {
    expect(currentSemesterOf(SESSION, [past, now])?.id).toBe("second");
  });

  it("falls back to the session's first semester", () => {
    expect(currentSemesterOf(SESSION, [past])?.id).toBe("first");
  });

  it("is null without a session", () => {
    expect(currentSemesterOf(null, [past])).toBeNull();
  });
});

describe("withQuery", () => {
  it("drops undefined and empty params", () => {
    expect(withQuery("/results", { page: 2, search: "", course: undefined })).toBe(
      "/results?page=2",
    );
  });

  it("leaves a path with no params alone", () => {
    expect(withQuery("/results", {})).toBe("/results");
  });
});
