import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, Button } from "../../components";
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Modal,
  SkeletonTable,
} from "../../components/admin";
import { ScopeGate, ScopeSteps } from "../../components/scope";
import type { ScopeStep } from "../../components/scope";
import {
  createUser,
  getInstitutionConfig,
  listDepartments,
  listFaculties,
  listUsers,
  updateUser,
} from "../../services/accounts";
import { LEVEL_OPTIONS, PERSON_ROLE_OPTIONS, ROLE_META } from "../../types";
import type { Department, Faculty, Person, Role } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncAction, useAsyncData, useDebounced } from "./useAsyncData";
import { useFacultyDepartmentFilter } from "./useDirectoryFilters";
import { PageHeader, Pager, SearchBox, SelectInput, TextInput, firstError } from "./ui";
import { PlusIcon } from "./adminIcons";
import styles from "./admin.module.css";

const PAGE_SIZE = 25;
const STAGES = ["Faculty", "Department", "Role"];

function initials(name: string) {
  const p = name.trim().split(/\s+/).filter(Boolean);
  if (!p.length) return "?";
  return (p.length === 1 ? p[0].slice(0, 2) : p[0][0] + p[p.length - 1][0]).toUpperCase();
}

const roleOptions = PERSON_ROLE_OPTIONS.map((r) => ({ value: r, label: ROLE_META[r].label }));

export function PeoplePage() {
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const location = useLocation();

  const [role, setRole] = useState<Role | "">("");
  const [level, setLevel] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(query.trim());

  const refData = useAsyncData(
    () => Promise.all([listFaculties(token), listDepartments(token), getInstitutionConfig(token)]),
    [token],
  );
  const [faculties, departments, config] = refData.data ?? [[], [], { lecturer_ranks: [] }];

  const {
    faculty,
    department,
    setDepartment,
    departmentsById: deptMap,
    departmentOptions: deptOptions,
    pickFaculty,
  } = useFacultyDepartmentFilter(departments);

  const scoped = Boolean(faculty && department && role);
  const doneCount = faculty ? (department ? (role ? 3 : 2) : 1) : 0;

  useEffect(() => setPage(1), [faculty, department, role, level, search]);

  const { data, loading, error, reload } = useAsyncData(
    () =>
      scoped
        ? listUsers(token, {
            page,
            page_size: PAGE_SIZE,
            faculty,
            department,
            role: role as Role,
            level: role === "student" ? level : "",
            search,
            is_active: true,
          })
        : Promise.resolve(null),
    [token, scoped, page, faculty, department, role, level, search],
  );
  const people = data?.results ?? [];

  const [editing, setEditing] = useState<Person | "new" | null>(
    (location.state as { create?: boolean } | null)?.create ? "new" : null,
  );
  const [toRemove, setToRemove] = useState<Person | null>(null);

  const roleLabel = role ? ROLE_META[role as Role].label : "";
  const facultyName = faculties.find((f: Faculty) => f.id === faculty)?.name ?? "";
  const departmentName = deptMap.get(department)?.name ?? "";

  const steps: ScopeStep[] = [
    {
      key: "faculty",
      label: "Faculty",
      placeholder: "Select a faculty",
      value: faculty,
      onChange: pickFaculty,
      options: faculties.map((f: Faculty) => ({ value: f.id, label: `${f.code} — ${f.name}` })),
    },
    {
      key: "department",
      label: "Department",
      placeholder: faculty ? "Select a department" : "Pick a faculty first",
      value: department,
      onChange: setDepartment,
      options: deptOptions.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` })),
      disabled: !faculty,
    },
    {
      key: "role",
      label: "Role",
      placeholder: department ? "Select a role" : "Pick a department first",
      value: role,
      onChange: (v) => {
        setRole(v as Role | "");
        if (v !== "student") setLevel("");
      },
      options: roleOptions,
      disabled: !department,
      hint: "One role at a time — students and staff are never listed together.",
    },
  ];

  if (role === "student") {
    steps.push({
      key: "level",
      label: "Level",
      placeholder: "All levels",
      value: level,
      onChange: setLevel,
      options: LEVEL_OPTIONS.map((l) => ({ value: l.value, label: l.label })),
    });
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="People"
        subtitle={
          scoped && data
            ? `${data.count.toLocaleString()} active ${roleLabel.toLowerCase()}${data.count === 1 ? "" : "s"} in ${departmentName || "this department"}.`
            : "Drill to a faculty, a department and a role to list people."
        }
        actions={
          <Button onClick={() => setEditing("new")}>
            <PlusIcon size={16} /> Add person
          </Button>
        }
      />

      {refData.error ? (
        <ErrorState message={refData.error} onRetry={refData.reload} />
      ) : (
        <ScopeSteps steps={steps} loading={refData.loading} ariaLabel="Directory scope" />
      )}

      {scoped ? (
        <div className={styles.toolbar}>
          <SearchBox
            value={query}
            onChange={setQuery}
            placeholder={`Search ${roleLabel.toLowerCase()}s in ${departmentName || "this department"} by name, email or ID…`}
          />
        </div>
      ) : null}

      <div className={styles.panel}>
        {!scoped ? (
          <ScopeGate
            stages={STAGES}
            doneCount={doneCount}
            title={
              !faculty
                ? "Select a faculty to begin"
                : !department
                  ? `Now select a department in ${facultyName || "this faculty"}`
                  : "Now select a role"
            }
            hint={
              !faculty
                ? "The directory holds every student and staff member in the university. Narrow it to one faculty first."
                : !department
                  ? "Departments in the faculty you picked are listed above."
                  : "Pick the role you are looking for — students, lecturers, HOD, dean, course adviser, exam officer and so on. Only that role is listed."
            }
          />
        ) : loading ? (
          <SkeletonTable rows={6} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : people.length === 0 ? (
          <EmptyState
            title={
              search
                ? `No ${roleLabel.toLowerCase()}s match “${search}”`
                : `No ${roleLabel.toLowerCase()}s in ${departmentName || "this department"}`
            }
            hint={
              search
                ? "Search only looks inside the department and role you selected. Clear it, or widen the scope above."
                : "Add a person to this department, or bulk-import them."
            }
          />
        ) : (
          <>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>{role === "student" ? "Matric no." : "Role"}</th>
                    <th>
                      {role === "student" ? "Level" : role === "lecturer" ? "Rank" : "Department"}
                    </th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {people.map((p) => {
                    const meta = ROLE_META[p.role];
                    return (
                      <tr key={p.id}>
                        <td>
                          <div className={styles.listRow} style={{ padding: 0, border: "none" }}>
                            <span
                              className={styles.fileBadge}
                              style={{
                                background: "var(--accent-grad)",
                                color: "#fff",
                                border: "none",
                                borderRadius: "50%",
                                width: 32,
                                height: 32,
                              }}
                            >
                              {initials(p.full_name)}
                            </span>
                            <span className={styles.cellStrong}>{p.full_name}</span>
                          </div>
                        </td>
                        <td className={[styles.cellMuted, styles.mono].join(" ")}>
                          {p.email ?? "—"}
                        </td>
                        <td>
                          {role === "student" ? (
                            <span className={[styles.cellMuted, styles.mono].join(" ")}>
                              {p.identifier || "—"}
                            </span>
                          ) : (
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                          )}
                        </td>
                        <td className={styles.cellMuted}>
                          {role === "student"
                            ? p.current_level
                              ? `${p.current_level} Level`
                              : "—"
                            : role === "lecturer"
                              ? (p.rank ?? "—")
                              : (deptMap.get(p.department ?? "")?.code ?? "—")}
                        </td>
                        <td>
                          <div className={styles.rowActions}>
                            <button
                              type="button"
                              className={styles.textBtn}
                              onClick={() => setEditing(p)}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className={[styles.textBtn, styles.textDanger].join(" ")}
                              onClick={() => setToRemove(p)}
                            >
                              Remove
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {data ? (
              <Pager
                page={data.page}
                totalPages={data.total_pages}
                count={data.count}
                label={`${roleLabel.toLowerCase()}${data.count === 1 ? "" : "s"}`}
                onPage={setPage}
              />
            ) : null}
          </>
        )}
      </div>

      {editing ? (
        <PersonModal
          person={editing === "new" ? null : editing}
          faculties={faculties}
          departments={departments}
          defaults={{ faculty, department, role: (role || "student") as Role }}
          ranks={config.lecturer_ranks}
          token={token}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      ) : null}

      {toRemove ? (
        <RemovePerson
          person={toRemove}
          token={token}
          onClose={() => setToRemove(null)}
          onDone={() => {
            setToRemove(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

function PersonModal({
  person,
  faculties,
  departments,
  defaults,
  ranks,
  token,
  onClose,
  onSaved,
}: {
  person: Person | null;
  faculties: Faculty[];
  departments: Department[];
  defaults: { faculty: string; department: string; role: Role };
  ranks: string[];
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = person !== null;
  const departmentOf = (id: string | null) => departments.find((d) => d.id === id) ?? null;

  const [fullName, setFullName] = useState(person?.full_name ?? "");
  const [email, setEmail] = useState(person?.email ?? "");
  const [role, setRole] = useState<Role>(person?.role ?? defaults.role);
  const [faculty, setFaculty] = useState(
    person ? (departmentOf(person.department)?.faculty ?? "") : defaults.faculty,
  );
  const [department, setDepartment] = useState(person?.department ?? defaults.department);
  const [level, setLevel] = useState(person?.current_level ? String(person.current_level) : "");
  const [rank, setRank] = useState(person?.rank ?? "");
  const save = useAsyncAction("Could not save the person.");
  const { message, errors } = save;

  const deptOptions = departments.filter((d) => !faculty || d.faculty === faculty);

  function submit() {
    const body: Partial<Person> = {
      full_name: fullName.trim(),
      role,
      department: department || null,
      current_level: role === "student" && level ? Number(level) : null,
      rank: role === "lecturer" && rank ? rank : null,
    };
    if (!isEdit) body.email = email.trim();
    void save.run(async () => {
      if (isEdit && person) await updateUser(person.id, body, token);
      else await createUser(body, token);
      onSaved();
    });
  }

  return (
    <Modal
      title={isEdit ? "Edit person" : "Add person"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.pending} onClick={submit}>
            {isEdit ? "Save changes" : "Add person"}
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        {message ? (
          <div className={styles.formError}>
            <Alert variant="error">{message}</Alert>
          </div>
        ) : null}
        <TextInput
          label="Full name"
          required
          value={fullName}
          onChange={setFullName}
          placeholder="Amaka Obi"
          error={firstError(errors, "full_name")}
        />
        {!isEdit ? (
          <TextInput
            label="Email"
            required
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="amaka@school.edu.ng"
            error={firstError(errors, "email")}
          />
        ) : null}
        <div className={styles.formGrid}>
          <SelectInput
            label="Role"
            required
            value={role}
            onChange={(v) => setRole(v as Role)}
            options={roleOptions}
            error={firstError(errors, "role")}
          />
          <SelectInput
            label="Faculty"
            value={faculty}
            onChange={(v) => {
              setFaculty(v);
              if (departmentOf(department)?.faculty !== v) setDepartment("");
            }}
            placeholder="None"
            options={faculties.map((f) => ({ value: f.id, label: `${f.code} — ${f.name}` }))}
          />
        </div>
        <SelectInput
          label="Department"
          value={department}
          onChange={setDepartment}
          placeholder={faculty ? "None" : "Pick a faculty first"}
          options={deptOptions.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
          error={firstError(errors, "department")}
        />
        {role === "student" ? (
          <SelectInput
            label="Current level"
            value={level}
            onChange={setLevel}
            placeholder="Not set"
            options={LEVEL_OPTIONS.map((l) => ({ value: l.value, label: l.label }))}
            error={firstError(errors, "current_level")}
          />
        ) : null}
        {role === "lecturer" ? (
          <SelectInput
            label="Rank"
            value={rank}
            onChange={setRank}
            placeholder="Not set"
            options={ranks.map((r) => ({ value: r, label: r }))}
            error={firstError(errors, "rank")}
          />
        ) : null}
      </div>
    </Modal>
  );
}

function RemovePerson({
  person,
  token,
  onClose,
  onDone,
}: {
  person: Person;
  token: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const remove = useAsyncAction("Could not remove the person.");
  return (
    <ConfirmDialog
      title="Remove person"
      message={`Deactivate ${person.full_name}? They will be removed from the active directory and can no longer sign in. Their records are preserved.`}
      confirmLabel="Remove"
      loading={remove.pending}
      error={remove.message}
      onCancel={onClose}
      onConfirm={() =>
        void remove.run(async () => {
          await updateUser(person.id, { is_active: false }, token);
          onDone();
        })
      }
    />
  );
}
