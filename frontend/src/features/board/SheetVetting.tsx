import type { AnomalyStats } from "../../types";
import styles from "./board.module.css";

function percent(rate: string) {
  const value = Number(rate);
  if (Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

const FLAG_COPY = {
  high_failure_rate: {
    title: "High failure rate",
    detail:
      "More than half the class scored below the pass mark. Confirm the marking scheme and script totals before approving.",
  },
  abnormally_high_grades: {
    title: "Abnormally high grades",
    detail:
      "More than half the class sits in the top grade band. Confirm this reflects the scripts and not a scaling or entry error.",
  },
} as const;

/**
 * The indicators the board vets a sheet on, all computed server-side from the
 * current score rows. The flags are the backend's own judgement and lead, so a
 * questionable spread is visible without reading the broadsheet.
 */
export function SheetVetting({ stats }: { stats: AnomalyStats }) {
  const raised = (Object.keys(FLAG_COPY) as Array<keyof typeof FLAG_COPY>).filter(
    (key) => stats.flags[key],
  );
  const distribution = Object.entries(stats.grade_distribution);
  const peak = Math.max(1, ...distribution.map(([, count]) => count));

  return (
    <section className={styles.vetting} aria-label="Vetting indicators">
      {raised.length > 0 ? (
        <div className={styles.flagStack} role="alert">
          {raised.map((key) => (
            <div key={key} className={styles.flag}>
              <span className={styles.flagDot} aria-hidden="true" />
              <div>
                <p className={styles.flagTitle}>{FLAG_COPY[key].title}</p>
                <p className={styles.flagDetail}>{FLAG_COPY[key].detail}</p>
              </div>
            </div>
          ))}
        </div>
      ) : stats.total_students > 0 ? (
        <div className={[styles.flag, styles.flagClear].join(" ")}>
          <span className={styles.flagDot} aria-hidden="true" />
          <div>
            <p className={styles.flagTitle}>No anomalies flagged</p>
            <p className={styles.flagDetail}>
              The failure rate and grade spread are both within the expected range for this
              institution.
            </p>
          </div>
        </div>
      ) : null}

      <div className={styles.metricGrid}>
        <Metric label="Students" value={stats.total_students.toLocaleString()} />
        <Metric label="Class average" value={stats.class_average ?? "—"} />
        <Metric
          label="Failure rate"
          value={percent(stats.failure_rate)}
          foot={`${stats.failure_count} below pass mark`}
          tone={stats.flags.high_failure_rate ? "danger" : undefined}
        />
        <Metric label="Highest" value={stats.highest_score ?? "—"} />
        <Metric label="Lowest" value={stats.lowest_score ?? "—"} />
      </div>

      <div className={styles.distribution}>
        <p className={styles.distTitle}>Grade distribution</p>
        <div className={styles.distRows}>
          {distribution.map(([letter, count]) => (
            <div key={letter} className={styles.distRow}>
              <span className={styles.distLetter}>{letter}</span>
              <span className={styles.distTrack}>
                <span
                  className={styles.distFill}
                  style={{ width: `${(count / peak) * 100}%` }}
                  aria-hidden="true"
                />
              </span>
              <span className={styles.distCount}>{count}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  foot,
  tone,
}: {
  label: string;
  value: string;
  foot?: string;
  tone?: "danger";
}) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span
        className={[styles.metricValue, tone === "danger" ? styles.metricDanger : ""].join(" ")}
      >
        {value}
      </span>
      {foot ? <span className={styles.metricFoot}>{foot}</span> : null}
    </div>
  );
}
