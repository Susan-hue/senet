"""CBT proctoring: capture lockdown signals + webcam, evaluate them into a
review-only cheating flag, and build an aggregated integrity report.

Invariants: nothing here writes ``ExamAttempt.score``/``status`` (flags are
advisory, not penalties), and every read is tenant-scoped. Browser proctoring is
a deterrent and evidence trail, not an uncheatable control.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from accounts.models import CourseAssignment, Role, User
from accounts.services import lecturer_can_access_course
from cbt.models import (
    CheatingFlag,
    CheatingFlagStatus,
    ProctorEvent,
    ProctorEventType,
    WebcamCapture,
)

# Thresholds at which signals trip a flag; override via settings.CBT_PROCTOR_THRESHOLDS.
DEFAULT_PROCTOR_THRESHOLDS = {
    "tab_switch": 3,
    "focus_loss": 3,
    "focus_loss_seconds": 60,
    "fullscreen_exit": 2,
    "clipboard": 1,
    "webcam_anomaly": 1,
}


def _thresholds():
    return {**DEFAULT_PROCTOR_THRESHOLDS, **getattr(settings, "CBT_PROCTOR_THRESHOLDS", {})}


# --------------------------------------------------------------------------- #
# Capture                                                                     #
# --------------------------------------------------------------------------- #


def record_event(*, attempt, event_type, client_timestamp, detail=None):
    """Append one proctoring signal (immutable) and re-evaluate the attempt."""
    event = ProctorEvent.all_objects.create(
        institution_id=attempt.institution_id,
        attempt=attempt,
        type=event_type,
        client_timestamp=client_timestamp,
        detail=detail,
    )
    evaluate_attempt_for_cheating(attempt)
    return event


def create_webcam_capture(
    *, attempt, media, kind, captured_at, is_anomalous=False, anomaly_reason=""
):
    """Store a webcam snapshot/clip for an attempt, stamping its retention window
    from the institution's ``webcam_retention_days``."""
    retention_days = attempt.institution.webcam_retention_days
    capture = WebcamCapture.all_objects.create(
        institution_id=attempt.institution_id,
        attempt=attempt,
        kind=kind,
        media=media,
        original_filename=getattr(media, "name", "") or "",
        captured_at=captured_at,
        expires_at=timezone.now() + timedelta(days=retention_days),
        is_anomalous=is_anomalous,
        anomaly_reason=anomaly_reason,
    )
    if is_anomalous:
        evaluate_attempt_for_cheating(attempt)
    return capture


# --------------------------------------------------------------------------- #
# Automatic flagging (review-only)                                            #
# --------------------------------------------------------------------------- #


def evaluate_attempt_for_cheating(attempt):
    """Raise/refresh a review-only flag from an attempt's signals. Never touches
    score/status. One flag per attempt; refreshes reasons on an open flag, respects
    a reviewer's decision, notifies only on first raise. Returns the flag or None."""
    reasons = _tripped_reasons(attempt)
    if not reasons:
        return None

    flag, created = CheatingFlag.all_objects.get_or_create(
        attempt=attempt,
        defaults={
            "institution_id": attempt.institution_id,
            "reasons": reasons,
            "status": CheatingFlagStatus.RAISED,
            "auto_raised": True,
        },
    )
    if created:
        from cbt.tasks import notify_cheating_flag

        notify_cheating_flag.delay(str(flag.id))
    elif flag.status == CheatingFlagStatus.RAISED:
        flag.reasons = reasons
        flag.save(update_fields=["reasons", "updated_at"])
    return flag


def _tripped_reasons(attempt):
    thresholds = _thresholds()
    counts = {}
    focus_loss_seconds = 0.0
    for event in ProctorEvent.all_objects.filter(attempt=attempt):
        counts[event.type] = counts.get(event.type, 0) + 1
        if event.type == ProctorEventType.FOCUS_LOSS and isinstance(event.detail, dict):
            focus_loss_seconds += float(event.detail.get("duration_seconds") or 0)
    clipboard = counts.get(ProctorEventType.COPY_ATTEMPT, 0) + counts.get(
        ProctorEventType.PASTE_ATTEMPT, 0
    )
    webcam_anomalies = WebcamCapture.all_objects.filter(attempt=attempt, is_anomalous=True).count()

    reasons = []

    def trip(code, count, threshold, detail):
        if count >= threshold:
            reasons.append(
                {"code": code, "count": int(count), "threshold": threshold, "detail": detail}
            )

    trip(
        "repeated_tab_switch",
        counts.get(ProctorEventType.TAB_SWITCH, 0),
        thresholds["tab_switch"],
        "Repeated tab switching",
    )
    trip(
        "repeated_focus_loss",
        counts.get(ProctorEventType.FOCUS_LOSS, 0),
        thresholds["focus_loss"],
        "Repeated loss of the exam window focus",
    )
    trip(
        "extended_focus_loss",
        focus_loss_seconds,
        thresholds["focus_loss_seconds"],
        "Extended time with the exam window unfocused",
    )
    trip(
        "fullscreen_exit",
        counts.get(ProctorEventType.FULLSCREEN_EXIT, 0),
        thresholds["fullscreen_exit"],
        "Left fullscreen during the exam",
    )
    trip("clipboard_activity", clipboard, thresholds["clipboard"], "Copy/paste activity")
    trip(
        "webcam_anomaly",
        webcam_anomalies,
        thresholds["webcam_anomaly"],
        "Webcam anomalies detected",
    )
    return reasons


# --------------------------------------------------------------------------- #
# Review flow                                                                 #
# --------------------------------------------------------------------------- #


def _require_reviewer(actor, attempt):
    """Only the course's lecturer (or an HOD/dean/admin in scope) may act on a
    flag. The exam officer has independent *visibility* but does not review."""
    from cbt.services import can_manage_exam

    exam = attempt.exam
    if not can_manage_exam(actor, exam.course, exam.session, exam.semester):
        raise PermissionDenied(
            "Only the course's lecturer (or an admin in scope) can review this flag."
        )


def dismiss_flag(*, actor, flag, notes=""):
    """Mark a flag a false positive. Records who/when/why; changes nothing about
    the attempt's score or status."""
    _require_reviewer(actor, flag.attempt)
    flag.status = CheatingFlagStatus.DISMISSED
    flag.reviewed_by = actor
    flag.reviewed_at = timezone.now()
    flag.review_notes = notes
    flag.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes", "updated_at"])
    return flag


def escalate_flag(*, actor, flag, notes=""):
    """Escalate a flag to the HOD of the course's department with notes. The exam
    officer already has independent visibility. Does not alter the attempt."""
    _require_reviewer(actor, flag.attempt)
    flag.status = CheatingFlagStatus.ESCALATED
    flag.reviewed_by = actor
    flag.reviewed_at = timezone.now()
    flag.review_notes = notes
    flag.escalated_to = _find_hod(flag.attempt.exam.course)
    flag.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "escalated_to",
            "updated_at",
        ]
    )
    from cbt.tasks import notify_flag_escalation

    notify_flag_escalation.delay(str(flag.id))
    return flag


def _find_hod(course):
    return User.objects.filter(
        institution_id=course.institution_id, role=Role.HOD, department_id=course.department_id
    ).first()


# --------------------------------------------------------------------------- #
# Notification recipients                                                      #
# --------------------------------------------------------------------------- #


def flag_notification_recipients(flag):
    """Lecturer(s) assigned to the exam's course-term + the exam's creator + every
    exam officer in the tenant. Deduplicated, sorted email list."""
    exam = flag.attempt.exam
    emails = set()
    for assignment in CourseAssignment.all_objects.filter(
        course_id=exam.course_id, session_id=exam.session_id, semester_id=exam.semester_id
    ).select_related("lecturer"):
        if assignment.lecturer.email:
            emails.add(assignment.lecturer.email)
    if exam.created_by_id and exam.created_by.email:
        emails.add(exam.created_by.email)
    for officer in User.objects.filter(institution_id=exam.institution_id, role=Role.EXAM_OFFICER):
        if officer.email:
            emails.add(officer.email)
    return sorted(emails)


# --------------------------------------------------------------------------- #
# Access scoping                                                              #
# --------------------------------------------------------------------------- #


def can_view_proctoring(user, attempt):
    """Staff who may see an attempt's proctoring data. Students (including the
    subject) never can. The exam officer has independent, tenant-wide visibility."""
    role = getattr(user, "role", None)
    if role is None or getattr(user, "institution_id", None) != attempt.institution_id:
        return False
    exam = attempt.exam
    if role == Role.EXAM_OFFICER:
        return True
    if role == Role.LECTURER:
        return exam.created_by_id == user.id or lecturer_can_access_course(
            user, exam.course, exam.session, exam.semester
        )
    if role == Role.HOD:
        return user.department_id is not None and user.department_id == exam.course.department_id
    if role == Role.DEAN:
        return user.faculty_id is not None and user.faculty_id == exam.course.department.faculty_id
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return True
    return False


def can_view_webcam(principal, attempt):
    """Webcam viewers: staff in scope (``can_view_proctoring``) OR a valid auditor
    token whose scope covers the attempt. Never a student, never cross-tenant."""
    from auditor.authentication import AuditorPrincipal

    if isinstance(principal, AuditorPrincipal):
        return _auditor_can_view(principal.token, attempt)
    return can_view_proctoring(principal, attempt)


def _auditor_can_view(token, attempt):
    if token.institution_id != attempt.institution_id or not token.is_valid:
        return False
    exam = attempt.exam
    department_ids = list(token.programmes.values_list("department_id", flat=True))
    if department_ids and exam.course.department_id not in department_ids:
        return False
    session_ids = list(token.sessions.values_list("id", flat=True))
    if session_ids and exam.session_id not in session_ids:
        return False
    return True


def visible_flags(user):
    """Flags a staff user may list, scoped to their remit within the tenant."""
    from django.db.models import Exists, OuterRef

    role = getattr(user, "role", None)
    qs = CheatingFlag.all_objects.filter(institution_id=user.institution_id).select_related(
        "attempt__exam__course__department", "attempt__student"
    )
    if role in (Role.EXAM_OFFICER, Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs.order_by("-created_at")
    if role == Role.LECTURER:
        assigned = CourseAssignment.all_objects.filter(
            lecturer=user,
            course=OuterRef("attempt__exam__course"),
            session=OuterRef("attempt__exam__session"),
            semester=OuterRef("attempt__exam__semester"),
        )
        return qs.filter(Exists(assigned)).order_by("-created_at")
    if role == Role.HOD:
        return qs.filter(attempt__exam__course__department_id=user.department_id).order_by(
            "-created_at"
        )
    if role == Role.DEAN:
        return qs.filter(attempt__exam__course__department__faculty_id=user.faculty_id).order_by(
            "-created_at"
        )
    return qs.none()


# --------------------------------------------------------------------------- #
# Integrity report                                                            #
# --------------------------------------------------------------------------- #


def build_integrity_report(attempt):
    """Aggregate everything a reviewer needs for one attempt: all proctoring
    events, the flag status, webcam references, and timing anomalies."""
    events = list(
        ProctorEvent.all_objects.filter(attempt=attempt).order_by("client_timestamp", "created_at")
    )
    event_counts = {}
    for event in events:
        event_counts[event.type] = event_counts.get(event.type, 0) + 1

    captures = list(WebcamCapture.all_objects.filter(attempt=attempt).order_by("captured_at"))
    flag = CheatingFlag.all_objects.filter(attempt=attempt).first()

    return {
        "attempt": str(attempt.id),
        "exam": str(attempt.exam_id),
        "student": str(attempt.student_id),
        "attempt_status": attempt.status,
        "score": str(attempt.score) if attempt.score is not None else None,
        "total_events": len(events),
        "event_counts": event_counts,
        "events": [
            {
                "type": event.type,
                "client_timestamp": event.client_timestamp,
                "received_at": event.created_at,
                "detail": event.detail,
            }
            for event in events
        ],
        "webcam": {
            "count": len(captures),
            "anomalies": sum(1 for c in captures if c.is_anomalous),
            "captures": [
                {
                    "id": str(c.id),
                    "kind": c.kind,
                    "captured_at": c.captured_at,
                    "is_anomalous": c.is_anomalous,
                    "anomaly_reason": c.anomaly_reason,
                    "expires_at": c.expires_at,
                }
                for c in captures
            ],
        },
        "timing": _timing_anomalies(attempt, events),
        "flag": _flag_summary(flag),
    }


def _timing_anomalies(attempt, events):
    allowed = (attempt.deadline - attempt.started_at).total_seconds()
    end = attempt.submitted_at or timezone.now()
    used = (end - attempt.started_at).total_seconds()
    heartbeats = [e for e in events if e.type == ProctorEventType.HEARTBEAT]
    max_gap = 0.0
    for earlier, later in zip(heartbeats, heartbeats[1:], strict=False):
        gap = (later.client_timestamp - earlier.client_timestamp).total_seconds()
        max_gap = max(max_gap, gap)
    return {
        "allowed_seconds": int(allowed),
        "used_seconds": int(used),
        "auto_submitted": attempt.status == "auto_submitted",
        "heartbeat_count": len(heartbeats),
        "max_heartbeat_gap_seconds": int(max_gap),
    }


def _flag_summary(flag):
    if flag is None:
        return None
    return {
        "id": str(flag.id),
        "status": flag.status,
        "auto_raised": flag.auto_raised,
        "reasons": flag.reasons,
        "reviewed_by": str(flag.reviewed_by_id) if flag.reviewed_by_id else None,
        "reviewed_at": flag.reviewed_at,
        "review_notes": flag.review_notes,
        "escalated_to": str(flag.escalated_to_id) if flag.escalated_to_id else None,
    }
