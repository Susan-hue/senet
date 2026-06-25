import styles from "./Logo.module.css";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={styles.logo}>
      <span className={styles.mark} aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" fill="var(--accent-solid)" />
          <path
            d="M14.4 8.6c-.2-1-1.2-1.7-2.6-1.7-1.5 0-2.6.8-2.6 1.9 0 2.6 5.4 1.2 5.4 4 0 1.2-1.2 2-2.8 2-1.5 0-2.6-.7-2.8-1.8"
            stroke="#fff"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </span>
      {compact ? null : <span className={styles.word}>Senet</span>}
    </span>
  );
}
