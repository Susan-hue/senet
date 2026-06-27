import logoUrl from "../assets/logo.png";
import styles from "./Logo.module.css";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={styles.logo}>
      <span className={[styles.mark, compact ? styles.markCompact : ""].filter(Boolean).join(" ")}>
        <span className={styles.glow} aria-hidden="true" />
        <img
          className={styles.img}
          src={logoUrl}
          alt=""
          width={compact ? 34 : 40}
          height={compact ? 39 : 46}
        />
      </span>
      <span className={[styles.word, compact ? styles.wordCompact : ""].filter(Boolean).join(" ")}>
        Senet
      </span>
    </span>
  );
}
