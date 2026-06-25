import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, AuthLayout, Button, Field } from "../../components";
import { ArrowLeftIcon } from "../../components/icons";
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
      title="Reset your password"
      subtitle="Enter your email and we'll send you a reset link."
      footer={
        <Link className={styles.backLink} to="/login">
          <ArrowLeftIcon size={16} />
          Back to sign in
        </Link>
      }
    >
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {formError ? <Alert variant="error">{formError}</Alert> : null}
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          inputMode="email"
          placeholder="you@school.edu"
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
