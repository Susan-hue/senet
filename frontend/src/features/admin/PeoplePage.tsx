import { useMemo, useState } from "react";
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
import { ApiError } from "../../services/api";
import { createUser, listDepartments, listUsers, updateUser } from "../../services/accounts";
import { LEVEL_OPTIONS, PERSON_ROLE_OPTIONS, ROLE_META } from "../../types";
import type { Department, Person, Role } from "../../types";
import { useAuth } from "../../hooks";
import { useAsyncData } from "./useAsyncData";
import { PageHeader, SearchBox, SelectInput, TextInput, firstError } from "./ui";
import { PlusIcon } from "./adminIcons";
import styles from "./admin.module.css";

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

  const { data, loading, error, reload } = useAsyncData(
    () => Promise.all([listUsers(token), listDepartments(token)]),
    [token],
  );
  const [people, departments] = data ?? [[], []];

  const deptMap = useMemo(() => {
    const m = new Map<string, Department>();
    departments.forEach((d) => m.set(d.id, d));
    return m;
  }, [departments]);

  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Person | "new" | null>(
    (location.state as { create?: boolean } | null)?.create ? "new" : null,
  );
  const [toRemove, setToRemove] = useState<Person | null>(null);

  const active = people.filter((p) => p.is_active !== false);
  const filtered = active.filter((p) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      p.full_name.toLowerCase().includes(q) ||
      (p.email ?? "").toLowerCase().includes(q) ||
      p.identifier.toLowerCase().includes(q)
    );
  });

  return (
    <div className={styles.page}>
      <PageHeader
        title="People"
        subtitle="Students, lecturers and staff across the university."
        actions={
          <Button onClick={() => setEditing("new")}>
            <PlusIcon size={16} /> Add person
          </Button>
        }
      />

      <div className={styles.toolbar}>
        <SearchBox value={query} onChange={setQuery} placeholder="Search by name or email…" />
      </div>

      <div className={styles.panel}>
        {loading ? (
          <SkeletonTable rows={6} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={active.length === 0 ? "No people yet" : "No matching people"}
            hint={
              active.length === 0
                ? "Add a person or bulk-import students to populate the directory."
                : "Try a different name, email or matric number."
            }
          />
        ) : (
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
                {filtered.map((p) => {
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
                      </td>
                      <td className={styles.cellMuted}>
                        {p.department ? (deptMap.get(p.department)?.code ?? "—") : "—"}
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
        )}
      </div>

      {editing ? (
        <PersonModal
          person={editing === "new" ? null : editing}
          departments={departments}
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
  token,
  onClose,
  onSaved,
}: {
  person: Person | null;
  departments: Department[];
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
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);

  async function submit() {
    setSaving(true);
    setMessage(null);
    setErrors(null);
    const body: Partial<Person> = {
      full_name: fullName.trim(),
      role,
      department: department || null,
      current_level: role === "student" && level ? Number(level) : null,
    };
    if (!isEdit) body.email = email.trim();
    try {
      if (isEdit && person) await updateUser(person.id, body, token);
      else await createUser(body, token);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        setMessage(err.message);
        setErrors(err.fieldErrors);
      } else {
        setMessage("Could not save the person.");
      }
      setSaving(false);
    }
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
          <Button loading={saving} onClick={submit}>
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function confirm() {
    setLoading(true);
    setError(null);
    try {
      await updateUser(person.id, { is_active: false }, token);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove the person.");
      setLoading(false);
    }
  }
  return (
    <ConfirmDialog
      title="Remove person"
      message={`Deactivate ${person.full_name}? They will be removed from the active directory and can no longer sign in. Their records are preserved.`}
      confirmLabel="Remove"
      loading={loading}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
    />
  );
}
