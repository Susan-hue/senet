import styles from "./landing.module.css";

/**
 * A restrained product-style panel for the hero: a result sheet part-way
 * through the approval chain. Decorative — it repeats what the copy already
 * says, so it is hidden from assistive technology and from small screens,
 * where the text alone carries the hero.
 */

const STAGES = [
  { label: "Lecturer", state: "done" },
  { label: "HOD", state: "done" },
  { label: "Dean", state: "done" },
  { label: "Senate", state: "current" },
] as const;

const ROWS = [
  { matric: "CSC/2021/014", ca: "32", exam: "46", total: "78", grade: "A" },
  { matric: "CSC/2021/027", ca: "26", exam: "37", total: "63", grade: "B" },
  { matric: "CSC/2021/031", ca: "21", exam: "34", total: "55", grade: "C" },
  { matric: "CSC/2021/046", ca: "29", exam: "42", total: "71", grade: "A" },
];

export function HeroVisual() {
  return (
    <div className={styles.visual} aria-hidden="true">
      <div className={styles.panelBack} />
      <div className={styles.panel}>
        <div className={styles.panelBar}>
          <span className={styles.panelTitle}>CSC 101 &middot; 2025/2026 First</span>
          <span className={styles.panelPill}>Awaiting Senate</span>
        </div>

        <div className={styles.pipeline}>
          {STAGES.map((stage) => (
            <div className={styles.stage} key={stage.label}>
              <span
                className={[
                  styles.stageDot,
                  stage.state === "done" ? styles.stageDone : styles.stageCurrent,
                ].join(" ")}
              />
              <span className={styles.stageLabel}>{stage.label}</span>
            </div>
          ))}
        </div>

        <div className={styles.sheet}>
          <div className={styles.sheetHead}>
            <span>Student</span>
            <span>CA</span>
            <span>Exam</span>
            <span>Total</span>
            <span>Grade</span>
          </div>
          {ROWS.map((row) => (
            <div className={styles.sheetRow} key={row.matric}>
              <span className={styles.matric}>{row.matric}</span>
              <span>{row.ca}</span>
              <span>{row.exam}</span>
              <span className={styles.total}>{row.total}</span>
              <span className={styles.grade}>{row.grade}</span>
            </div>
          ))}
        </div>

        <div className={styles.panelFoot}>
          <span className={styles.footDot} />
          Append-only &mdash; 4 entries in the audit trail
        </div>
      </div>
    </div>
  );
}
