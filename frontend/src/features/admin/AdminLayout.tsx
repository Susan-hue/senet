import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import logoUrl from "../../assets/logo.png";
import { useAuth } from "../../hooks";
import { listSemesters, listSessions } from "../../services/accounts";
import type { Semester, Session } from "../../types";
import {
  BookIcon,
  GridIcon,
  LayersIcon,
  LinkIcon,
  LogoutIcon,
  MenuIcon,
  UploadIcon,
  UsersIcon,
} from "./adminIcons";
import styles from "./AdminLayout.module.css";

export interface NavItem {
  to: string;
  label: string;
  Icon: (props: { size?: number }) => ReactElement;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", Icon: GridIcon },
  { to: "/academic-structure", label: "Academic Structure", Icon: LayersIcon },
  { to: "/courses", label: "Courses", Icon: BookIcon },
  { to: "/people", label: "People", Icon: UsersIcon },
  { to: "/assignments", label: "Lecturer Assignments", Icon: LinkIcon },
  { to: "/imports", label: "Bulk Import", Icon: UploadIcon },
];

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatDate(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function AdminLayout({
  nav = NAV,
  brandSub = "Admin Console",
  rolePill = "Admin",
}: {
  nav?: NavItem[];
  brandSub?: string;
  rolePill?: string;
}) {
  const { user, accessToken, logout } = useAuth();
  const [navOpen, setNavOpen] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [semester, setSemester] = useState<Semester | null>(null);
  const location = useLocation();

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!accessToken) return;
    let active = true;
    Promise.all([listSessions(accessToken), listSemesters(accessToken)])
      .then(([sessions, semesters]) => {
        if (!active) return;
        const current = sessions.find((s) => s.is_current) ?? sessions[0] ?? null;
        setSession(current);
        if (!current) return;
        const now = Date.now();
        const inSession = semesters.filter((sem) => sem.session === current.id);
        setSemester(
          inSession.find(
            (sem) =>
              new Date(sem.start_date).getTime() <= now && now <= new Date(sem.end_date).getTime(),
          ) ??
            inSession[0] ??
            null,
        );
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [accessToken]);

  const name = user?.fullName || user?.email || "Administrator";

  return (
    <div className={styles.shell}>
      {navOpen ? (
        <div className={styles.scrim} onClick={() => setNavOpen(false)} aria-hidden="true" />
      ) : null}

      <aside className={[styles.sidebar, navOpen ? styles.sidebarOpen : ""].join(" ")}>
        <div className={styles.brand}>
          <span className={styles.mark}>
            <span className={styles.markGlow} aria-hidden="true" />
            <img src={logoUrl} alt="" width={34} height={39} />
          </span>
          <span className={styles.brandText}>
            <span className={styles.brandName}>Senet</span>
            <span className={styles.brandSub}>{brandSub}</span>
          </span>
        </div>

        <nav className={styles.nav} aria-label="Primary">
          {nav.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                [styles.navItem, isActive ? styles.navActive : ""].join(" ")
              }
            >
              <span className={styles.navDot} aria-hidden="true" />
              <Icon size={17} />
              <span className={styles.navLabel}>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className={styles.sidebarFoot}>
          {session ? (
            <div className={styles.sessionCard}>
              <span className={styles.sessionEyebrow}>Active session</span>
              <span className={styles.sessionName}>{session.name}</span>
              <span className={styles.sessionMeta}>
                {semester ? `${semester.name} · ` : ""}ends{" "}
                {formatDate(semester?.end_date ?? session.end_date)}
              </span>
            </div>
          ) : null}
          <button type="button" className={styles.signOut} onClick={() => void logout()}>
            <LogoutIcon size={17} />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <button
            type="button"
            className={styles.hamburger}
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
          >
            <MenuIcon size={20} />
          </button>
          <div className={styles.institution}>
            <span className={styles.instName}>{user?.institutionName ?? "Senet"}</span>
            <span className={styles.adminPill}>{rolePill}</span>
          </div>
          <div className={styles.topbarRight}>
            <div className={styles.user}>
              <span className={styles.avatar} aria-hidden="true">
                {initials(name)}
              </span>
              <span className={styles.userText}>
                <span className={styles.userName}>{name}</span>
                <span className={styles.userRole}>{user?.email}</span>
              </span>
            </div>
          </div>
        </header>

        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
