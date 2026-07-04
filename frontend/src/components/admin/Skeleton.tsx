import styles from "./Skeleton.module.css";

export function Skeleton({ width, height = 14 }: { width?: number | string; height?: number }) {
  return (
    <span className={styles.bar} style={{ width: width ?? "100%", height }} aria-hidden="true" />
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div
      className={styles.table}
      role="status"
      aria-label="Loading data"
      style={{ ["--cols" as string]: String(cols) }}
    >
      <div className={styles.head}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} width={i === 0 ? "45%" : "60%"} height={10} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className={styles.row} style={{ animationDelay: `${r * 90}ms` }}>
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} width={c === 0 ? "70%" : `${45 + ((r + c) % 3) * 15}%`} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className={styles.cards} role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={styles.card} style={{ animationDelay: `${i * 90}ms` }}>
          <Skeleton width="55%" height={10} />
          <Skeleton width="40%" height={26} />
          <Skeleton width="65%" height={10} />
        </div>
      ))}
    </div>
  );
}
