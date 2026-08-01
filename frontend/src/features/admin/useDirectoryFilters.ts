import { useMemo, useState } from "react";
import type { Department } from "../../types";

/**
 * The faculty → department drill every directory listing filters on. Narrowing
 * the faculty drops a department that no longer belongs to it, and any change
 * takes the listing back to its first page, so a page-3 view never survives into
 * a filter with fewer pages.
 */
export function useFacultyDepartmentFilter(departments: Department[], onNarrow: () => void) {
  const [faculty, setFaculty] = useState("");
  const [department, setDepartment] = useState("");

  const departmentsById = useMemo(() => {
    const m = new Map<string, Department>();
    departments.forEach((d) => m.set(d.id, d));
    return m;
  }, [departments]);

  const departmentOptions = useMemo(
    () => departments.filter((d) => !faculty || d.faculty === faculty),
    [departments, faculty],
  );

  function pickFaculty(id: string) {
    setFaculty(id);
    if (id && department && departmentsById.get(department)?.faculty !== id) setDepartment("");
    onNarrow();
  }

  function pickDepartment(id: string) {
    setDepartment(id);
    onNarrow();
  }

  return {
    faculty,
    department,
    departmentsById,
    departmentOptions,
    pickFaculty,
    pickDepartment,
  };
}
