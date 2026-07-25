from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from cbt.models import CheatingFlag
from cbt.proctoring import flag_notification_recipients
from cbt.services import finalize_expired_attempts


@shared_task(name="cbt.tasks.finalize_expired_attempts_task")
def finalize_expired_attempts_task(limit=500):
    """Periodic safety net: auto-submit and grade attempts whose deadline has
    passed, regardless of whether the student ever reconnected. Idempotent and
    concurrency-safe (row-locked with a status guard), so it is safe to run on a
    short interval and to overlap with itself. Returns the number finalized."""
    return finalize_expired_attempts(limit=limit)


def _flag_for(flag_id):
    return (
        CheatingFlag.all_objects.select_related(
            "attempt__exam__course", "attempt__student", "escalated_to"
        )
        .filter(pk=flag_id)
        .first()
    )


@shared_task(name="cbt.tasks.notify_cheating_flag")
def notify_cheating_flag(flag_id):
    """Notify the lecturer(s) and the exam officer that an integrity flag was
    raised. Reuses the standard email path; the flag itself is review-only."""
    flag = _flag_for(flag_id)
    if flag is None:
        return
    recipients = flag_notification_recipients(flag)
    if not recipients:
        return
    exam = flag.attempt.exam
    reasons = ", ".join(reason.get("detail", reason.get("code", "")) for reason in flag.reasons)
    send_mail(
        subject=f"[Integrity review] Flag raised — {exam.title}",
        message=(
            "An exam attempt has been automatically flagged for integrity review.\n\n"
            f"Exam: {exam.title}\n"
            f"Student: {flag.attempt.student.full_name}\n"
            f"Reasons: {reasons}\n\n"
            "This is for review only — no score or attempt has been changed. "
            "Please review the integrity report and dismiss or escalate as appropriate."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


@shared_task(name="cbt.tasks.notify_flag_escalation")
def notify_flag_escalation(flag_id):
    """Notify the HOD that a lecturer escalated an integrity flag to them."""
    flag = _flag_for(flag_id)
    if flag is None or flag.escalated_to is None or not flag.escalated_to.email:
        return
    exam = flag.attempt.exam
    send_mail(
        subject=f"[Integrity review] Flag escalated — {exam.title}",
        message=(
            "An integrity flag has been escalated to you for review.\n\n"
            f"Exam: {exam.title}\n"
            f"Student: {flag.attempt.student.full_name}\n"
            f"Reviewer notes: {flag.review_notes or '(none)'}\n\n"
            "This is for review only — no score or attempt has been changed."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[flag.escalated_to.email],
        fail_silently=True,
    )
