import styles from "./StrengthMeter.module.css";

const LABELS = ["Enter a password", "Weak", "Fair", "Good", "Strong"];
const COLORS = ["#5A5A66", "#F1646C", "#F5A623", "#6366F1", "#3DD68C"];

export function StrengthMeter({ password }: { password: string }) {
  let score = 0;
  if (password.length >= 8) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;

  const idx = password.length === 0 ? 0 : Math.max(1, score);
  const color = COLORS[idx];

  return (
    <div>
      <div className={styles.track}>
        <div className={styles.fill} style={{ width: `${(idx / 4) * 100}%`, background: color }} />
      </div>
      <div className={styles.label} style={{ color }}>
        {LABELS[idx]}
      </div>
    </div>
  );
}
