from celery import shared_task

from cbt.services import finalize_expired_attempts


@shared_task(name="cbt.tasks.finalize_expired_attempts_task")
def finalize_expired_attempts_task(limit=500):
    """Periodic safety net: auto-submit and grade attempts whose deadline has
    passed, regardless of whether the student ever reconnected. Idempotent and
    concurrency-safe (row-locked with a status guard), so it is safe to run on a
    short interval and to overlap with itself. Returns the number finalized."""
    return finalize_expired_attempts(limit=limit)


# Integrity-flag notifications used to be sent from here. They now go through the
# notifications app (``notifications.tasks.notify_cheating_flag`` /
# ``notify_flag_escalation``) so every message the platform sends is logged,
# multi-channel and retried the same way.
