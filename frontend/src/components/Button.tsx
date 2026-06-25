import type { ReactNode } from "react";
import { Spinner } from "./Spinner";
import styles from "./Button.module.css";

interface ButtonProps {
  type?: "button" | "submit";
  variant?: "primary" | "ghost";
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  onClick?: () => void;
  children: ReactNode;
}

export function Button({
  type = "button",
  variant = "primary",
  loading = false,
  disabled = false,
  fullWidth = false,
  onClick,
  children,
}: ButtonProps) {
  const className = [styles.button, styles[variant], fullWidth ? styles.full : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type={type === "submit" ? "submit" : "button"}
      className={className}
      onClick={onClick}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <Spinner size={16} label="Submitting" /> : null}
      <span>{children}</span>
    </button>
  );
}
