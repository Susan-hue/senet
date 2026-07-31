import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, AuthLayout, Button } from "../../components";
import { resendVerification } from "../../services/auth";
import { ApiError } from "../../services/api";
import styles from "./auth.module.css";

const COUNTDOWN_SECONDS = 15;

/**
 * The screen after sign-up. Resending is held behind a countdown rather than a
 * bare button: mail takes a few seconds to land, and an immediately-clickable
 * "Resend" invites people to spend their rate limit before the first email has
 * even arrived. The timer restarts on each send, so the pacing survives repeats.
 */
export function VerificationSent({ email }: { email: string }) {
  const navigate = useNavigate();
  const [secondsLeft, setSecondsLeft] = useState(COUNTDOWN_SECONDS);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setTimeout(() => setSecondsLeft((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  const resend = useCallback(async () => {
    setSending(true);
    setNotice(null);
    try {
      await resendVerification(email);
      setNotice({ kind: "success", text: `A new link is on its way to ${email}.` });
      setSecondsLeft(COUNTDOWN_SECONDS);
    } catch (error) {
      setNotice({
        kind: "error",
        text:
          error instanceof ApiError
            ? error.message
            : "We couldn't send another email. Check your connection and try again.",
      });
      // A failed send costs nothing, so let them retry without waiting again.
      setSecondsLeft(0);
    } finally {
      setSending(false);
    }
  }, [email]);

  const ready = secondsLeft <= 0;

  return (
    <AuthLayout title="Check your inbox" subtitle="One more step to activate your account.">
      <div className={styles.center}>
        <Alert variant="success">
          We sent a verification link to <strong>{email}</strong>. Open it to verify your email,
          then sign in.
        </Alert>

        {notice ? (
          <Alert variant={notice.kind === "success" ? "success" : "error"}>{notice.text}</Alert>
        ) : null}

        <p className={styles.resendHint} aria-live="polite">
          {ready
            ? "Didn't get it? Check your spam folder, or send it again."
            : `You can request another email in ${secondsLeft}s.`}
        </p>

        <Button
          fullWidth
          variant="ghost"
          onClick={() => void resend()}
          disabled={!ready || sending}
          loading={sending}
        >
          {ready ? "Resend email" : `Resend email (${secondsLeft}s)`}
        </Button>

        <Button fullWidth onClick={() => navigate("/login")}>
          Go to sign in
        </Button>
      </div>
    </AuthLayout>
  );
}
