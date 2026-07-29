import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { Logo } from "./Logo";
import { SiteFooter } from "./SiteFooter";
import { useAuth } from "../hooks";
import styles from "./PublicLayout.module.css";

/** Router navigation does not honour a #hash on its own; do it here so footer
 *  links into a section work from any public page. */
function useHashScroll() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (!hash) {
      window.scrollTo(0, 0);
      return;
    }
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [pathname, hash]);
}

/**
 * Chrome for the signed-out pages: landing, privacy, terms. The header CTA
 * follows the session — an already-signed-in visitor is offered their workspace
 * rather than a sign-in form they do not need.
 */
export function PublicLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const authenticated = status === "authenticated";
  useHashScroll();

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.brand} aria-label="Senet home">
            <Logo compact />
          </Link>
          <nav className={styles.nav}>
            <Link className={styles.navLink} to="/#platform">
              Features
            </Link>
            <Link className={styles.cta} to={authenticated ? "/app" : "/login"}>
              {status === "loading" ? " " : authenticated ? "Go to workspace" : "Sign in"}
            </Link>
          </nav>
        </div>
      </header>
      <main className={styles.main}>{children}</main>
      <SiteFooter />
    </div>
  );
}
