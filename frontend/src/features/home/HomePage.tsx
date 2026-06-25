import { Button, Logo } from "../../components";
import { useAuth } from "../../hooks";
import styles from "./home.module.css";

export function HomePage() {
  const { user, logout } = useAuth();

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <Logo />
        <div className={styles.body}>
          <h1 className={styles.title}>You're signed in</h1>
          <p className={styles.text}>
            {user?.email ? (
              <span>
                Signed in as <strong>{user.email}</strong>.
              </span>
            ) : (
              <span>Your session is active.</span>
            )}
            {user?.id ? <span className={styles.id}>User ID: {user.id}</span> : null}
          </p>
        </div>
        <Button variant="ghost" fullWidth onClick={() => void logout()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
