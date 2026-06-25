import type { ReactNode } from "react";
import { Logo } from "./Logo";
import styles from "./AuthLayout.module.css";

interface AuthLayoutProps {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  const year = new Date().getFullYear();

  return (
    <div className={styles.page}>
      <aside className={styles.brand}>
        <div className={styles.brandTop}>
          <Logo />
        </div>
        <div className={styles.brandBody}>
          <h2 className={styles.brandHeadline}>Records and examinations, in one place.</h2>
          <p className={styles.brandText}>
            Secure access for students, lecturers, and faculty across your institution.
          </p>
        </div>
        <p className={styles.brandFoot}>&copy; {year} Senet</p>
      </aside>

      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.cardBrand}>
            <Logo />
          </div>
          <header className={styles.header}>
            <h1 className={styles.title}>{title}</h1>
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </header>
          {children}
          {footer ? <footer className={styles.footer}>{footer}</footer> : null}
        </div>
      </main>
    </div>
  );
}
