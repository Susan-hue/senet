import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Alert, AuthLayout, Button, Field, StrengthMeter } from "../../components";
import { ArrowLeftIcon } from "../../components/icons";
import { resetPassword } from "../../services/auth";
import { ApiError } from "../../services/api";
import styles from "./auth.module.css";

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [confirmError, setConfirmError] = useState<string | undefined>(undefined);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;

    setConfirmError(undefined);
    if (password !== confirm) {
      setConfirmError("Passwords do not match.");
      return;
    }

    setLoading(true);
    setFormError(null);
    setFieldErrors({});
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (error) {
      if (error instanceof ApiError) {
        setFormError(error.message);
        if (error.fieldErrors) setFieldErrors(error.fieldErrors);
      } else {
        setFormError("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <AuthLayout title="Reset password">
        <div className={styles.center}>
          <Alert variant="error">This reset link is missing its token or is invalid.</Alert>
          <Button variant="ghost" fullWidth onClick={() => navigate("/forgot-password")}>
            Request a new link
          </Button>
        </div>
      </AuthLayout>
    );
  }

  if (done) {
    return (
      <AuthLayout title="Password updated">
        <div className={styles.center}>
          <Alert variant="success">Your password has been reset. You can now sign in.</Alert>
          <Button fullWidth onClick={() => navigate("/login")}>
            Continue to sign in
          </Button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Set a new password"
      subtitle="Choose a strong password you haven't used before."
      footer={
        <Link className={styles.backLink} to="/login">
          <ArrowLeftIcon size={16} />
          Back to sign in
        </Link>
      }
    >
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {formError ? <Alert variant="error">{formError}</Alert> : null}
        <div>
          <Field
            label="New password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            placeholder="Enter new password"
            required
            error={fieldErrors.password?.[0]}
          />
          <StrengthMeter password={password} />
        </div>
        <Field
          label="Confirm password"
          type="password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
          placeholder="Re-enter new password"
          required
          error={confirmError}
        />
        <Button type="submit" fullWidth loading={loading}>
          Reset password
        </Button>
      </form>
    </AuthLayout>
  );
}
