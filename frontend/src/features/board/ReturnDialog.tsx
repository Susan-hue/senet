import { useEffect, useRef, useState } from "react";
import { Alert, Button } from "../../components";
import { Modal } from "../../components/admin";
import styles from "./board.module.css";

const MIN_REASON_LENGTH = 10;

/**
 * Returning a sheet always carries a reason: it is the only thing the lecturer
 * receives to act on, and the API rejects a blank one. The same rule is
 * enforced here so the board is told before the round trip, not after.
 */
export function ReturnDialog({
  title,
  subject,
  recipient,
  loading,
  error,
  onCancel,
  onConfirm,
}: {
  title: string;
  subject: string;
  recipient: string;
  loading: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);

  // The reason is the only thing this dialog asks for, so it takes focus when
  // the dialog opens — which also moves focus into the modal for a screen reader.
  useEffect(() => field.current?.focus(), []);

  const trimmed = reason.trim();
  const problem =
    trimmed.length === 0
      ? "A reason is required to return a result."
      : trimmed.length < MIN_REASON_LENGTH
        ? "Give the lecturer enough detail to act on — at least a short sentence."
        : null;

  function submit() {
    setTouched(true);
    if (problem) return;
    onConfirm(trimmed);
  }

  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={submit} loading={loading} disabled={problem !== null}>
            Return with reason
          </Button>
        </>
      }
    >
      <div className={styles.dialogBody}>
        <p className={styles.dialogText}>
          {subject} goes back to <strong>{recipient}</strong> for correction and unlocks for
          editing. The reason below is sent with it and recorded in the audit trail.
        </p>
        <label className={styles.dialogField}>
          <span className={styles.scopeLabel}>
            Reason for returning <span className={styles.req}>*</span>
          </span>
          <textarea
            className={styles.textarea}
            rows={5}
            ref={field}
            value={reason}
            placeholder="e.g. The failure rate is 68% and the CA column is missing for 14 students. Please re-check the exam scores against the scripts and resubmit."
            onChange={(e) => setReason(e.target.value)}
            onBlur={() => setTouched(true)}
            aria-invalid={touched && problem ? true : undefined}
          />
          <span className={styles.dialogHint}>
            {touched && problem ? (
              <span className={styles.dialogError}>{problem}</span>
            ) : (
              "Required. The lecturer sees this verbatim."
            )}
          </span>
        </label>
        {error ? <Alert variant="error">{error}</Alert> : null}
      </div>
    </Modal>
  );
}
