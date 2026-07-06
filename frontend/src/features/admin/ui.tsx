import type { ReactNode } from "react";
import { SearchIcon } from "./adminIcons";
import styles from "./admin.module.css";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className={styles.pageHead}>
      <div>
        <h1 className={styles.pageTitle}>{title}</h1>
        {subtitle ? <p className={styles.pageSub}>{subtitle}</p> : null}
      </div>
      {actions ? <div className={styles.headActions}>{actions}</div> : null}
    </div>
  );
}

export function Panel({
  title,
  linkLabel,
  onLink,
  children,
}: {
  title: string;
  linkLabel?: string;
  onLink?: () => void;
  children: ReactNode;
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>{title}</h2>
        {linkLabel && onLink ? (
          <button type="button" className={styles.panelLink} onClick={onLink}>
            {linkLabel}
          </button>
        ) : null}
      </div>
      {children}
    </section>
  );
}

type StatTone = "muted" | "accent" | "success" | "warning";

export function StatCard({
  label,
  value,
  foot,
  tone = "muted",
}: {
  label: string;
  value: string | number;
  foot?: string;
  tone?: StatTone;
}) {
  const footClass =
    tone === "accent"
      ? styles.footAccent
      : tone === "success"
        ? styles.footSuccess
        : tone === "warning"
          ? styles.footWarning
          : "";
  return (
    <div className={styles.statCard}>
      <span className={styles.statGlow} aria-hidden="true" />
      <div className={styles.statLabel}>{label}</div>
      <div className={styles.statValue}>{value}</div>
      {foot ? <div className={[styles.statFoot, footClass].join(" ")}>{foot}</div> : null}
    </div>
  );
}

export function TextInput({
  label,
  value,
  onChange,
  required,
  error,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  error?: string;
  placeholder?: string;
  type?: "text" | "date" | "number" | "email";
}) {
  return (
    <label className={styles.formFull}>
      <span className={styles.fieldLabel}>
        {label}
        {required ? <span className={styles.req}> *</span> : null}
      </span>
      <input
        className={styles.input}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
      />
      {error ? <span className={styles.pageSub}>{error}</span> : null}
    </label>
  );
}

export function SelectInput({
  label,
  value,
  onChange,
  options,
  required,
  error,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  required?: boolean;
  error?: string;
  placeholder?: string;
}) {
  return (
    <label className={styles.formFull}>
      <span className={styles.fieldLabel}>
        {label}
        {required ? <span className={styles.req}> *</span> : null}
      </span>
      <select
        className={styles.selectInput}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error ? <span className={styles.pageSub}>{error}</span> : null}
    </label>
  );
}

export function firstError(
  errors: Record<string, string[]> | null | undefined,
  ...keys: string[]
): string | undefined {
  if (!errors) return undefined;
  for (const k of keys) {
    const v = errors[k];
    if (v && v.length) return v[0];
  }
  return undefined;
}

export function Pager({
  page,
  totalPages,
  count,
  label,
  onPage,
}: {
  page: number;
  totalPages: number;
  count: number;
  label: string;
  onPage: (page: number) => void;
}) {
  if (count === 0) return null;
  return (
    <div className={styles.pager}>
      <span className={styles.pagerInfo}>
        {count.toLocaleString()} {label} · page {page} of {totalPages}
      </span>
      <div className={styles.pagerButtons}>
        <button
          type="button"
          className={styles.pagerBtn}
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </button>
        <button
          type="button"
          className={styles.pagerBtn}
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder = "Search…",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className={styles.search}>
      <SearchIcon size={16} />
      <input
        className={styles.searchInput}
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        aria-label={placeholder}
      />
    </div>
  );
}
