import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, AuthLayout, Button, Field } from "../../components";
import { useAuth } from "../../hooks";
import { ApiError } from "../../services/api";
import styles from "./auth.module.css";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});

  const fieldError = (key: string) => fieldErrors[key]?.[0];

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setFormError(null);
    setFieldErrors({});
    try {
      await login(email.trim(), password);
      navigate("/", { replace: true });
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

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Welcome back. Enter your details to continue."
      footer={
        <>
          New to Senet? <Link to="/register">Create an account</Link>
        </>
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
          error={fieldError("email")}
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          required
          error={fieldError("password")}
        />
        <div className={styles.metaRow}>
          <Link className={styles.smallLink} to="/forgot-password">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" fullWidth loading={loading}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
