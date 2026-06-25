import type { ReactNode } from "react";
import { AlertIcon, CheckCircleIcon, InfoIcon } from "./icons";
import styles from "./Alert.module.css";

interface AlertProps {
  variant: "error" | "success" | "info";
  children: ReactNode;
}

export function Alert({ variant, children }: AlertProps) {
  const Icon = variant === "success" ? CheckCircleIcon : variant === "error" ? AlertIcon : InfoIcon;

  return (
    <div
      className={[styles.alert, styles[variant]].join(" ")}
      role={variant === "error" ? "alert" : "status"}
      aria-live={variant === "error" ? "assertive" : "polite"}
    >
      <Icon size={18} />
      <span className={styles.text}>{children}</span>
    </div>
  );
}
