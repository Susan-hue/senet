import type { ReactNode } from "react";
import { Logo } from "./Logo";
import { IsometricStack } from "./IsometricStack";
import styles from "./AuthLayout.module.css";

interface AuthLayoutProps {
  title?: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

const EYEBROW = "Academic infrastructure";
const HEADLINE = "Everything your university runs on, in one place.";

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <div className={styles.page}>
      <aside className={styles.brandDesktop}>
        <div className={styles.orbA} aria-hidden="true" />
        <div className={styles.orbB} aria-hidden="true" />
        <div className={styles.grid} aria-hidden="true" />
        <div className={styles.isoWrap} aria-hidden="true">
          <IsometricStack variant="desktop" />
        </div>
        <div className={styles.watermark} aria-hidden="true">
          S
        </div>

        <div className={styles.brandInner}>
          <Logo />
          <div className={styles.brandMid}>
            <div className={styles.eyebrow}>{EYEBROW}</div>
            <h1 className={styles.headline}>{HEADLINE}</h1>
            <p className={styles.subcopy}>
              From matriculation to convocation &mdash; courses, computer-based testing, results,
              approvals and academic records, unified for African institutions.
            </p>
            <div className={styles.pills}>
              <span className={styles.pill}>
                <span
                  className={styles.dot}
                  style={{ background: "#6366F1", boxShadow: "0 0 8px #6366F1" }}
                />
                CBT exams
              </span>
              <span className={styles.pill}>
                <span
                  className={styles.dot}
                  style={{ background: "#8B5CF6", boxShadow: "0 0 8px #8B5CF6" }}
                />
                Results
              </span>
              <span className={styles.pill}>
                <span
                  className={styles.dot}
                  style={{ background: "#A78BFA", boxShadow: "0 0 8px #A78BFA" }}
                />
                Records
              </span>
            </div>
          </div>
          <div className={styles.trusted}>
            <span className={styles.trustedDot} />
            Trusted by institutions across Nigeria &amp; Africa
          </div>
        </div>
      </aside>

      <div className={styles.brandMobile}>
        <div className={styles.mobileGlow} aria-hidden="true" />
        <div className={styles.mobileTop}>
          <Logo compact />
        </div>
        <div className={styles.mobileIso} aria-hidden="true">
          <IsometricStack variant="compact" />
        </div>
        <div>
          <div className={styles.eyebrow}>{EYEBROW}</div>
          <h1 className={styles.mobileHeadline}>{HEADLINE}</h1>
        </div>
      </div>

      <main className={styles.formPanel}>
        <div className={styles.formGlow} aria-hidden="true" />
        <div className={styles.formInner}>
          {title ? (
            <header className={styles.headerBlock}>
              <h2 className={styles.title}>{title}</h2>
              {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
            </header>
          ) : null}
          {children}
          {footer ? <p className={styles.footer}>{footer}</p> : null}
        </div>
      </main>
    </div>
  );
}
