import { Button, Logo } from "../../components";
import { useAuth } from "../../hooks";
import styles from "./forbidden.module.css";

export function ForbiddenPage() {
  const { user, logout } = useAuth();
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <Logo />
        <div className={styles.code}>403</div>
        <h1 className={styles.title}>Admin access only</h1>
        <p className={styles.text}>
          {user?.email ? (
            <>
              You&rsquo;re signed in as <strong>{user.email}</strong>, which doesn&rsquo;t have
              access to the administration console.
            </>
          ) : (
            "Your account doesn't have access to the administration console."
          )}
        </p>
        <Button variant="ghost" fullWidth onClick={() => void logout()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
