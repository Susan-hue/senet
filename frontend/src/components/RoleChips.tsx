import styles from "./RoleChips.module.css";

interface Option {
  value: string;
  label: string;
}

interface RoleChipsProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<Option>;
  required?: boolean;
}

export function RoleChips({ label, value, onChange, options, required = false }: RoleChipsProps) {
  return (
    <div className={styles.group} role="group" aria-label={label}>
      <span className={styles.label}>
        {label}
        {required ? (
          <span className={styles.req} aria-hidden="true">
            {" *"}
          </span>
        ) : null}
      </span>
      <div className={styles.chips}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            className={[styles.chip, value === option.value ? styles.chipActive : ""]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
