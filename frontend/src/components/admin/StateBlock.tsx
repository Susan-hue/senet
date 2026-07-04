import type { ReactNode } from "react";
import { Spinner } from "../Spinner";
import styles from "./StateBlock.module.css";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className={styles.block} role="status" aria-live="polite">
      <Spinner size={22} label={label} />
      <p className={styles.text}>{label}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={styles.block} role="alert">
      <div className={[styles.icon, styles.danger].join(" ")} aria-hidden="true">
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M10.3 3.7 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z" />
          <path d="M12 9v4M12 17h.01" />
        </svg>
      </div>
      <p className={styles.title}>Something went wrong</p>
      <p className={styles.text}>{message}</p>
      {onRetry ? (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={styles.block}>
      <div className={styles.icon} aria-hidden="true">
        {icon ?? (
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
          </svg>
        )}
      </div>
      <p className={styles.title}>{title}</p>
      {hint ? <p className={styles.text}>{hint}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
