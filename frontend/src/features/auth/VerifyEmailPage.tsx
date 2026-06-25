import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Alert, AuthLayout, Button, Spinner } from "../../components";
import { verifyEmail } from "../../services/auth";
import { ApiError } from "../../services/api";
import styles from "./auth.module.css";

type VerifyState = "loading" | "success" | "error";

export function VerifyEmailPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token");
  const [state, setState] = useState<VerifyState>("loading");
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (!token) {
      setState("error");
      setMessage("This verification link is missing its token.");
      return;
    }

    verifyEmail(token)
      .then((res) => {
        setState("success");
        setMessage(res.message || "Your email has been verified.");
      })
      .catch((error) => {
        setState("error");
        setMessage(
          error instanceof ApiError ? error.message : "We couldn't verify your email address.",
        );
      });
  }, [token]);

  return (
    <AuthLayout title="Verify email">
      {state === "loading" ? (
        <div className={styles.loadingRow}>
          <Spinner size={18} label="Verifying" />
          <span>Verifying your email address&hellip;</span>
        </div>
      ) : null}

      {state === "success" ? (
        <div className={styles.center}>
          <Alert variant="success">{message}</Alert>
          <Button fullWidth onClick={() => navigate("/login")}>
            Continue to sign in
          </Button>
        </div>
      ) : null}

      {state === "error" ? (
        <div className={styles.center}>
          <Alert variant="error">{message}</Alert>
          <Button variant="ghost" fullWidth onClick={() => navigate("/login")}>
            Back to sign in
          </Button>
          <p className={styles.smallLink}>
            Need a new link? <Link to="/register">Register again</Link>
          </p>
        </div>
      ) : null}
    </AuthLayout>
  );
}
