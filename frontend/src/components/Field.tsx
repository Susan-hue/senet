import { useId, useState } from "react";
import { EyeIcon, EyeOffIcon } from "./icons";
import styles from "./Field.module.css";

interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password";
  error?: string;
  hint?: string;
  autoComplete?: string;
  placeholder?: string;
  required?: boolean;
  inputMode?: "text" | "email";
}

export function Field({
  label,
  value,
  onChange,
  type = "text",
  error,
  hint,
  autoComplete,
  placeholder,
  required = false,
  inputMode,
}: FieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const [reveal, setReveal] = useState(false);

  const isPassword = type === "password";
  const inputType = isPassword ? (reveal ? "text" : "password") : type;
  const describedBy =
    [error ? errorId : null, hint && !error ? hintId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
        {required ? (
          <span className={styles.req} aria-hidden="true">
            {" *"}
          </span>
        ) : null}
      </label>
      <div className={styles.inputWrap}>
        <input
          id={id}
          type={inputType}
          className={[
            styles.input,
            error ? styles.inputError : "",
            isPassword ? styles.hasToggle : "",
          ]
            .filter(Boolean)
            .join(" ")}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          inputMode={inputMode}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
        />
        {isPassword ? (
          <button
            type="button"
            className={styles.toggle}
            onClick={() => setReveal((value) => !value)}
            aria-label={reveal ? "Hide password" : "Show password"}
            aria-pressed={reveal}
          >
            {reveal ? <EyeOffIcon size={18} /> : <EyeIcon size={18} />}
          </button>
        ) : null}
      </div>
      {hint && !error ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
