import type { ReactNode } from "react";
import styles from "./scope.module.css";

export interface ScopeStep {
  key: string;
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  locked?: string;
  disabled?: boolean;
  hint?: string;
  render?: ReactNode;
}

export function ScopeSteps({
  steps,
  loading = false,
  ariaLabel = "Scope",
}: {
  steps: ScopeStep[];
  loading?: boolean;
  ariaLabel?: string;
}) {
  return (
    <section className={styles.bar} aria-label={ariaLabel}>
      {steps.map((step, index) => (
        <div key={step.key} className={styles.step}>
          <span
            className={[styles.index, step.value ? styles.indexDone : ""].join(" ")}
            aria-hidden="true"
          >
            {index + 1}
          </span>
          <div className={styles.field}>
            <span className={styles.label}>{step.label}</span>
            {step.locked ? (
              <span className={styles.locked} title="Scoped to you — set by your role">
                {step.locked}
              </span>
            ) : step.render ? (
              step.render
            ) : (
              <select
                className={styles.select}
                value={step.value}
                aria-label={step.label}
                disabled={step.disabled || loading}
                onChange={(e) => step.onChange(e.target.value)}
              >
                <option value="">{step.placeholder}</option>
                {step.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
            {step.hint ? <span className={styles.hint}>{step.hint}</span> : null}
          </div>
        </div>
      ))}
    </section>
  );
}

export function ScopeGate({
  stages,
  doneCount,
  title,
  hint,
}: {
  stages: string[];
  doneCount: number;
  title: string;
  hint: string;
}) {
  return (
    <div className={styles.gate}>
      <div className={styles.gateSteps}>
        {stages.map((stage, i) => (
          <span
            key={stage}
            className={[
              styles.gateChip,
              i < doneCount ? styles.gateChipDone : "",
              i === doneCount ? styles.gateChipNext : "",
            ].join(" ")}
          >
            {stage}
          </span>
        ))}
      </div>
      <p className={styles.gateTitle}>{title}</p>
      <p className={styles.gateHint}>{hint}</p>
    </div>
  );
}
