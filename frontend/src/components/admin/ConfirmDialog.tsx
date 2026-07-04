import { Button } from "../Button";
import { Alert } from "../Alert";
import { Modal } from "./Modal";
import styles from "./ConfirmDialog.module.css";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  loading?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Delete",
  loading = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal
      title={title}
      size="sm"
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <button
            type="button"
            className={styles.danger}
            onClick={onConfirm}
            disabled={loading}
            aria-busy={loading || undefined}
          >
            {loading ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      <p className={styles.message}>{message}</p>
      {error ? (
        <div className={styles.alert}>
          <Alert variant="error">{error}</Alert>
        </div>
      ) : null}
    </Modal>
  );
}
