import { useState } from "react";
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
import {
  FilterSelect,
  PageHeader,
  Pager,
  SearchBox,
  SelectInput,
  TextInput,
  firstError,
} from "./ui";
import { PlusIcon } from "./adminIcons";
import styles from "./admin.module.css";

const PAGE_SIZE = 25;

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

  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(query.trim());

  const refData = useAsyncData(
    () => Promise.all([listFaculties(token), listDepartments(token), getInstitutionConfig(token)]),
    [token],
  );
  const [faculties, departments, config] = refData.data ?? [[], [], { lecturer_ranks: [] }];
  const scope = useFacultyDepartmentFilter(departments, () => setPage(1));

  const { data, loading, error, reload } = useAsyncData(
    () =>
      listUsers(token, {
        page,
        page_size: PAGE_SIZE,
        faculty: scope.faculty,
        department: scope.department,
        search,
        is_active: true,
      }),
    [token, page, scope.faculty, scope.department, search],
  );
  const people = data?.results ?? [];
  const hasFilters = Boolean(search || scope.faculty || scope.department);

  const [editing, setEditing] = useState<Person | "new" | null>(
    (location.state as { create?: boolean } | null)?.create ? "new" : null,
  );
  const [toRemove, setToRemove] = useState<Person | null>(null);

  return (
    <div className={styles.page}>
      <PageHeader
        title="People"
        subtitle={
          data
            ? `${data.count.toLocaleString()} active ${data.count === 1 ? "person" : "people"}${hasFilters ? " in this view" : ""}.`
            : "Students, lecturers and staff across the university."
        }
        actions={
          <Button onClick={() => setEditing("new")}>
            <PlusIcon size={16} /> Add person
          </Button>
        }
      />

      <div className={styles.toolbar}>
        <SearchBox
          value={query}
          onChange={(v) => {
            setQuery(v);
            setPage(1);
          }}
          placeholder="Search by name, email or matric number…"
        />
        <FilterSelect
          value={scope.faculty}
          onChange={scope.pickFaculty}
          label="Filter by faculty"
          allLabel="All faculties"
          options={faculties.map((f: Faculty) => ({ value: f.id, label: `${f.code} — ${f.name}` }))}
        />
        <FilterSelect
          value={scope.department}
          onChange={scope.pickDepartment}
          label="Filter by department"
          allLabel="All departments"
          options={scope.departmentOptions.map((d) => ({
            value: d.id,
            label: `${d.code} — ${d.name}`,
          }))}
        />
      </div>

      <div className={styles.panel}>
        {loading ? (
          <SkeletonTable rows={6} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : people.length === 0 ? (
          <EmptyState
            title={hasFilters ? "No matching people" : "No people yet"}
            hint={
              hasFilters
                ? "Try a different search, or clear the faculty and department filters."
                : "Add a person or bulk-import students to populate the directory."
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
                    <th>Role</th>
                    <th>Department</th>
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
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                          {p.role === "lecturer" && p.rank ? (
                            <span className={styles.rankNote}>{p.rank}</span>
                          ) : null}
                        </td>
                        <td className={styles.cellMuted}>
                          {p.department
                            ? (scope.departmentsById.get(p.department)?.code ?? "—")
                            : "—"}
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
                label="people"
                onPage={setPage}
              />
            ) : null}
          </>
        )}
      </div>

      {editing ? (
        <PersonModal
          person={editing === "new" ? null : editing}
          departments={departments}
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
  departments,
  ranks,
  token,
  onClose,
  onSaved,
}: {
  person: Person | null;
  departments: Department[];
  ranks: string[];
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = person !== null;
  const [fullName, setFullName] = useState(person?.full_name ?? "");
  const [email, setEmail] = useState(person?.email ?? "");
  const [role, setRole] = useState<Role>(person?.role ?? "student");
  const [department, setDepartment] = useState(person?.department ?? "");
  const [level, setLevel] = useState(person?.current_level ? String(person.current_level) : "");
  const [rank, setRank] = useState(person?.rank ?? "");
  const save = useAsyncAction("Could not save the person.");
  const { message, errors } = save;

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
            label="Department"
            value={department}
            onChange={setDepartment}
            placeholder="None"
            options={departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
            error={firstError(errors, "department")}
          />
        </div>
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
