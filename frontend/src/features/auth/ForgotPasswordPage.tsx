import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, AuthLayout, Button, Field } from "../../components";
import { ArrowLeftIcon, MailIcon } from "../../components/icons";
import { requestPasswordReset } from "../../services/auth";
import { ApiError } from "../../services/api";
import styles from "./auth.module.css";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setFormError(null);
    setFieldErrors({});
    try {
      await requestPasswordReset(email.trim());
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

  if (done) {
    return (
      <AuthLayout title="Check your inbox">
        <div className={styles.center}>
          <Alert variant="success">
            If an account exists for <strong>{email.trim()}</strong>, a password reset link is on
            its way.
          </Alert>
          <Link className={styles.backLink} to="/login">
            <ArrowLeftIcon size={16} />
            Back to sign in
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      footer={
        <Link className={styles.backLink} to="/login">
          <ArrowLeftIcon size={16} />
          Back to sign in
        </Link>
      }
    >
      <div className={styles.head}>
        <div className={styles.iconTile}>
          <MailIcon size={22} />
        </div>
        <h2 className={styles.h2}>Forgot password?</h2>
        <p className={styles.sub}>
          Enter the email tied to your account and we'll send a secure link to reset your password.
        </p>
      </div>

      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {formError ? <Alert variant="error">{formError}</Alert> : null}
        <Field
          label="Email address"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          inputMode="email"
          placeholder="you@university.edu.ng"
          required
          error={fieldErrors.email?.[0]}
        />
        <Button type="submit" fullWidth loading={loading}>
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  );
}
