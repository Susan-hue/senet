"""Celery tasks: the only place a message is actually sent.

Two layers. The fan-out tasks resolve recipients and write log rows off the
request path — publishing a whole class's results must not make a Senate admin's
HTTP call wait. ``send_notification`` then delivers one row.

``send_notification`` never propagates an exception. A provider outage is
recorded on the row and retried with backoff; when the retries run out the row
settles on FAILED. Nothing about a failing provider can reach the request that
triggered it, and nothing crashes a worker.
"""

import logging
from datetime import timedelta

from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings
from django.utils import timezone

from accounts.models import CourseAssignment, Enrolment, Role, User
from notifications.models import (
    Notification,
    NotificationEvent,
    NotificationStatus,
    ResultCheckRegistration,
)
from notifications.providers import get_provider
from notifications.resultcheck import invalidate_summary
from notifications.services import notify_users
from tenancy.scoping import set_current_institution

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="notifications.tasks.send_notification")
def send_notification(self, notification_id):
    """Deliver one logged notification. Returns its final status."""
    notification = (
        Notification.all_objects.select_related("institution").filter(pk=notification_id).first()
    )
    if notification is None or notification.status == NotificationStatus.SENT:
        return None

    provider_name = "unknown"
    try:
        provider = get_provider(notification.channel)
        provider_name = provider.name
        message_id = provider.send(
            channel=notification.channel,
            to=notification.recipient_address,
            subject=notification.subject,
            body=notification.body,
        )
    except Exception as exc:  # noqa: BLE001 - a send failure is data, never a crash
        return _record_failure(self, notification, provider_name, exc)

    notification.mark_sent(provider=provider_name, message_id=message_id)
    return NotificationStatus.SENT.value


def _record_failure(task, notification, provider_name, exc):
    """Log the failure on the row, then retry unless the attempts are spent.

    Retries are skipped in eager mode (local dev and tests), where a retry would
    raise straight back into the caller — exactly what this task exists to
    prevent.
    """
    retries = task.request.retries or 0
    max_retries = settings.NOTIFICATION_MAX_RETRIES
    eager = settings.CELERY_TASK_ALWAYS_EAGER
    final = eager or retries >= max_retries

    notification.mark_attempt_failed(provider=provider_name, error=exc, final=final)
    logger.warning(
        "Notification %s failed on %s (attempt %s): %s",
        notification.id,
        notification.channel,
        notification.attempts,
        exc,
    )
    if final:
        return NotificationStatus.FAILED.value

    countdown = settings.NOTIFICATION_RETRY_BACKOFF_SECONDS * (2**retries)
    try:
        task.retry(countdown=countdown, max_retries=max_retries)
    except Retry:
        # Celery's own control flow: the worker reschedules this task.
        raise
    except Exception:  # noqa: BLE001 - retries spent or the broker refused
        notification.status = NotificationStatus.FAILED
        notification.save(update_fields=["status", "updated_at"])
        return NotificationStatus.FAILED.value
    return NotificationStatus.QUEUED.value


# --------------------------------------------------------------------------- #
# Fan-out                                                                      #
# --------------------------------------------------------------------------- #


def _activate(institution):
    """Tenant scoping in a worker has no middleware to set it up."""
    set_current_institution(institution)


@shared_task(name="notifications.tasks.notify_result_returned")
def notify_result_returned(result_id, reason=""):
    """A sheet was returned to its lecturer for correction."""
    from results.models import CourseResult

    result = (
        CourseResult.all_objects.select_related(
            "institution", "course", "session", "semester", "lecturer"
        )
        .filter(pk=result_id)
        .first()
    )
    if result is None:
        return 0
    _activate(result.institution)
    queued = notify_users(
        institution=result.institution,
        event=NotificationEvent.RESULT_RETURNED,
        users=[result.lecturer],
        context={
            "course_code": result.course.code,
            "session": result.session.name,
            "semester": result.semester.name,
            "reason": reason or result.returned_reason,
        },
    )
    return len(queued)


@shared_task(name="notifications.tasks.notify_result_published")
def notify_result_published(result_id):
    """A sheet was ratified by Senate: tell every student on it, and drop their
    cached SMS summaries so the new grade is visible on the next check."""
    from results.models import CourseResult, StudentScore

    result = (
        CourseResult.all_objects.select_related("institution", "course", "session", "semester")
        .filter(pk=result_id)
        .first()
    )
    if result is None:
        return 0
    _activate(result.institution)
    students = [
        row.student
        for row in StudentScore.all_objects.filter(result=result, is_current=True).select_related(
            "student"
        )
    ]
    for student in students:
        invalidate_summary(student.id)

    queued = notify_users(
        institution=result.institution,
        event=NotificationEvent.RESULT_PUBLISHED,
        users=students,
        context={
            "course_code": result.course.code,
            "session": result.session.name,
            "semester": result.semester.name,
        },
        dedupe_prefix=f"result_published:{result.id}",
    )
    return len(queued)


def _exam_students(exam):
    return [
        enrolment.student
        for enrolment in Enrolment.all_objects.filter(
            institution_id=exam.institution_id,
            course_id=exam.course_id,
            session_id=exam.session_id,
            semester_id=exam.semester_id,
        ).select_related("student")
    ]


def _exam_context(exam):
    return {
        "exam_title": exam.title,
        "course_code": exam.course.code,
        "opens_at": timezone.localtime(exam.opens_at).strftime("%d %b %Y, %H:%M"),
        "closes_at": timezone.localtime(exam.closes_at).strftime("%d %b %Y, %H:%M"),
        "duration_minutes": exam.duration_minutes,
    }


@shared_task(name="notifications.tasks.notify_exam_scheduled")
def notify_exam_scheduled(exam_id):
    """A CBT was scheduled: tell the students enrolled in that course term."""
    from cbt.models import Exam

    exam = Exam.all_objects.select_related("institution", "course").filter(pk=exam_id).first()
    if exam is None:
        return 0
    _activate(exam.institution)
    queued = notify_users(
        institution=exam.institution,
        event=NotificationEvent.EXAM_SCHEDULED,
        users=_exam_students(exam),
        context=_exam_context(exam),
        dedupe_prefix=f"exam_scheduled:{exam.id}",
    )
    return len(queued)


@shared_task(name="notifications.tasks.notify_opened_exams")
def notify_opened_exams(lookback_minutes=60):
    """Beat sweep: exams that have just opened. Idempotent — each student's
    notification carries a dedupe key, so an overlapping or repeated run queues
    nothing twice."""
    from cbt.models import Exam

    now = timezone.now()
    window_start = now - timedelta(minutes=lookback_minutes)
    queued = 0
    exams = Exam.all_objects.select_related("institution", "course").filter(
        opens_at__gte=window_start, opens_at__lte=now, closes_at__gt=now
    )
    for exam in exams:
        _activate(exam.institution)
        queued += len(
            notify_users(
                institution=exam.institution,
                event=NotificationEvent.EXAM_OPENED,
                users=_exam_students(exam),
                context=_exam_context(exam),
                dedupe_prefix=f"exam_opened:{exam.id}",
            )
        )
    return queued


def _flag(flag_id):
    from cbt.models import CheatingFlag

    return (
        CheatingFlag.all_objects.select_related(
            "institution", "attempt__exam__course", "attempt__student", "escalated_to"
        )
        .filter(pk=flag_id)
        .first()
    )


def _flag_reviewers(flag):
    """The lecturers assigned to the exam's course term, the exam's creator, and
    every exam officer in the tenant."""
    exam = flag.attempt.exam
    users = {}
    for assignment in CourseAssignment.all_objects.filter(
        course_id=exam.course_id, session_id=exam.session_id, semester_id=exam.semester_id
    ).select_related("lecturer"):
        users[assignment.lecturer_id] = assignment.lecturer
    if exam.created_by_id:
        users.setdefault(exam.created_by_id, exam.created_by)
    for officer in User.objects.filter(institution_id=exam.institution_id, role=Role.EXAM_OFFICER):
        users.setdefault(officer.id, officer)
    return sorted(users.values(), key=lambda user: user.email)


@shared_task(name="notifications.tasks.notify_cheating_flag")
def notify_cheating_flag(flag_id):
    """An integrity flag was raised. Review-only: the message says so, and no
    score or attempt is touched anywhere on this path."""
    flag = _flag(flag_id)
    if flag is None:
        return 0
    _activate(flag.institution)
    exam = flag.attempt.exam
    reasons = ", ".join(
        reason.get("detail", reason.get("code", "")) for reason in flag.reasons or []
    )
    queued = notify_users(
        institution=flag.institution,
        event=NotificationEvent.CHEATING_FLAG_RAISED,
        users=_flag_reviewers(flag),
        context={
            "exam_title": exam.title,
            "student_name": flag.attempt.student.full_name,
            "reasons": reasons,
        },
        dedupe_prefix=f"cheating_flag_raised:{flag.id}",
    )
    return len(queued)


@shared_task(name="notifications.tasks.notify_flag_escalation")
def notify_flag_escalation(flag_id):
    """A reviewer escalated an integrity flag to the HOD."""
    flag = _flag(flag_id)
    if flag is None or flag.escalated_to is None:
        return 0
    _activate(flag.institution)
    exam = flag.attempt.exam
    queued = notify_users(
        institution=flag.institution,
        event=NotificationEvent.CHEATING_FLAG_ESCALATED,
        users=[flag.escalated_to],
        context={
            "exam_title": exam.title,
            "student_name": flag.attempt.student.full_name,
            "notes": flag.review_notes,
        },
    )
    return len(queued)


@shared_task(name="notifications.tasks.purge_expired_otps")
def purge_expired_otps():
    """Housekeeping: clear one-time codes that were never used."""
    return ResultCheckRegistration.all_objects.filter(
        is_verified=False, otp_expires_at__lt=timezone.now()
    ).update(otp_hash="", otp_expires_at=None)
