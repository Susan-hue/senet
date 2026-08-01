import { useMemo, useState } from "react";
import type { Department } from "../../types";

/**
 * The faculty → department step every scoped directory listing starts with.
 * Departments are offered only once a faculty is chosen, and narrowing to a
 * different faculty drops a department that no longer belongs to it.
 */
export function useFacultyDepartmentFilter(departments: Department[]) {
  const [faculty, setFaculty] = useState("");
  const [department, setDepartment] = useState("");

  const departmentsById = useMemo(() => {
    const m = new Map<string, Department>();
    departments.forEach((d) => m.set(d.id, d));
    return m;
  }, [departments]);

  const departmentOptions = useMemo(
    () => departments.filter((d) => d.faculty === faculty),
    [departments, faculty],
  );

  function pickFaculty(id: string) {
    setFaculty(id);
    if (department && departmentsById.get(department)?.faculty !== id) setDepartment("");
  }

  return {
    faculty,
    department,
    setDepartment,
    departmentsById,
    departmentOptions,
    pickFaculty,
  };
}
