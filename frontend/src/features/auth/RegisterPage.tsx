import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, AuthLayout, Button, Field, RoleChips } from "../../components";
import { register } from "../../services/auth";
import { ApiError } from "../../services/api";
import { ROLE_OPTIONS } from "../../types";
import type { Role } from "../../types";
import styles from "./auth.module.css";

export function RegisterPage() {
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("student");
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
      await register({ email: trimmedEmail, full_name: fullName.trim(), password, role });
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

  if (submittedEmail) {
    return (
      <AuthLayout title="Check your inbox" subtitle="One more step to activate your account.">
        <div className={styles.center}>
          <Alert variant="success">
            We sent a verification link to <strong>{submittedEmail}</strong>. Open it to verify your
            email, then sign in.
          </Alert>
          <Button fullWidth onClick={() => navigate("/login")}>
            Go to sign in
          </Button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Create your account"
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
        <RoleChips
          label="I am a"
          value={role}
          onChange={(value) => setRole(value as Role)}
          options={ROLE_OPTIONS}
          required
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
        <p className={styles.finePrint}>
          By continuing you agree to Senet's <span className={styles.term}>Terms</span> and{" "}
          <span className={styles.term}>Privacy Policy</span>.
        </p>
      </form>
    </AuthLayout>
  );
}
