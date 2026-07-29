import { Link } from "react-router-dom";
import { Logo } from "./Logo";
import styles from "./SiteFooter.module.css";

const CONTACT_EMAIL = "hello@senet.ng";

export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <div className={styles.brandCol}>
          <Logo compact />
          <p className={styles.tagline}>
            Academic records and examinations for Nigerian universities.
          </p>
        </div>

        <nav className={styles.cols} aria-label="Footer">
          <div className={styles.col}>
            <h2 className={styles.colTitle}>Product</h2>
            <Link className={styles.link} to="/#platform">
              Features
            </Link>
            <Link className={styles.link} to="/login">
              Sign in
            </Link>
          </div>

          <div className={styles.col}>
            <h2 className={styles.colTitle}>Company</h2>
            <Link className={styles.link} to="/#about">
              About
            </Link>
            <a className={styles.link} href={`mailto:${CONTACT_EMAIL}`}>
              Contact
            </a>
          </div>

          <div className={styles.col}>
            <h2 className={styles.colTitle}>Legal</h2>
            <Link className={styles.link} to="/privacy">
              Privacy Policy
            </Link>
            <Link className={styles.link} to="/terms">
              Terms of Service
            </Link>
            <Link className={styles.link} to="/privacy#ndpa">
              NDPA / Data Protection
            </Link>
          </div>
        </nav>
      </div>

      <div className={styles.baseline}>
        <p className={styles.copy}>&copy; {year} Senet. All rights reserved.</p>
        <p className={styles.compliance}>
          Senet is built to comply with the Nigeria Data Protection Act (NDPA) 2023.
        </p>
      </div>
    </footer>
  );
}
