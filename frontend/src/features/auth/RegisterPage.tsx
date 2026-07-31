import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, AuthLayout, Button, Field } from "../../components";
import { register } from "../../services/auth";
import { ApiError } from "../../services/api";
import { VerificationSent } from "./VerificationSent";
import styles from "./auth.module.css";

/**
 * Public sign-up — students only. Lecturers, HODs, deans, exam officers,
 * advisers and admins are provisioned by their institution's administrator,
 * because a role that carries authority over other people's results cannot be
 * self-asserted. There is no role selector here and the API rejects one.
 */
export function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

  const fieldError = (key: string) => fieldErrors[key]?.[0];

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setFormError(null);
    setFieldErrors({});
    try {
      const trimmedEmail = email.trim();
      await register({ email: trimmedEmail, full_name: fullName.trim(), password });
      setSubmittedEmail(trimmedEmail);
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

  if (submittedEmail) return <VerificationSent email={submittedEmail} />;

  return (
    <AuthLayout
      title="Create your student account"
      subtitle="Join your university's Senet workspace in minutes."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {formError ? <Alert variant="error">{formError}</Alert> : null}
        <Field
          label="Full name"
          value={fullName}
          onChange={setFullName}
          autoComplete="name"
          placeholder="Adaeze Okonkwo"
          required
          error={fieldError("full_name")}
        />
        <Field
          label="Institution email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          inputMode="email"
          placeholder="you@university.edu.ng"
          required
          error={fieldError("email")}
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          placeholder="Create a strong password"
          required
          hint="At least 8 characters."
          error={fieldError("password")}
        />
        <Button type="submit" fullWidth loading={loading}>
          Create account
        </Button>
        <p className={styles.staffNote}>
          Teaching or administrative staff? Your institution creates your account — ask your
          department or school administrator rather than signing up here.
        </p>
        <p className={styles.finePrint}>
          By continuing you agree to Senet's <span className={styles.term}>Terms</span> and{" "}
          <span className={styles.term}>Privacy Policy</span>.
        </p>
      </form>
    </AuthLayout>
  );
}
