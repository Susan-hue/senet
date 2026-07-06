from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import Enrolment, Role
from accounts.services import lecturer_can_access_course
from results.models import (
    LECTURER_EDITABLE_STATUSES,
    AuditAction,
    CourseResult,
    ResultAuditLog,
    ResultStatus,
    StudentScore,
)

GRADE_BANDS = [
    (Decimal("70"), "A"),
    (Decimal("60"), "B"),
    (Decimal("50"), "C"),
    (Decimal("45"), "D"),
    (Decimal("40"), "E"),
]


def letter_grade(total):
    for cutoff, letter in GRADE_BANDS:
        if total >= cutoff:
            return letter
    return "F"


def _owns_result(actor, result):
    return result.lecturer_id == actor.id


def _hod_scope(actor, result):
    return actor.department_id is not None and actor.department_id == result.course.department_id


def _dean_scope(actor, result):
    return actor.faculty_id is not None and actor.faculty_id == result.course.department.faculty_id


def _senate_scope(actor, result):
    return True


# (from_status, to_status) -> (required role, scope check, reason required).
# Every legal move in the pipeline is enumerated here; anything absent is
# rejected, so states cannot be skipped and ratified results have no exit.
TRANSITIONS = {
    (ResultStatus.DRAFT, ResultStatus.SUBMITTED_TO_HOD): (Role.LECTURER, _owns_result, False),
    (ResultStatus.RETURNED, ResultStatus.SUBMITTED_TO_HOD): (Role.LECTURER, _owns_result, False),
    (ResultStatus.SUBMITTED_TO_HOD, ResultStatus.APPROVED_BY_HOD): (Role.HOD, _hod_scope, False),
    (ResultStatus.SUBMITTED_TO_HOD, ResultStatus.RETURNED): (Role.HOD, _hod_scope, True),
    (ResultStatus.APPROVED_BY_HOD, ResultStatus.APPROVED_BY_DEAN): (
        Role.DEAN,
        _dean_scope,
        False,
    ),
    (ResultStatus.APPROVED_BY_HOD, ResultStatus.RETURNED): (Role.DEAN, _dean_scope, True),
    (ResultStatus.APPROVED_BY_DEAN, ResultStatus.RATIFIED_BY_SENATE): (
        Role.SENATE_ADMIN,
        _senate_scope,
        False,
    ),
    (ResultStatus.APPROVED_BY_DEAN, ResultStatus.RETURNED): (
        Role.SENATE_ADMIN,
        _senate_scope,
        True,
    ),
}


def _log(*, result, actor, action, score=None, before=None, after=None, reason=""):
    """Audit write. Callers must already be inside the same transaction as the
    change being logged, so both commit or neither does."""
    ResultAuditLog.all_objects.create(
        institution=result.institution,
        result=result,
        score=score,
        actor=actor,
        action=action,
        before=before,
        after=after,
        reason=reason,
    )


def _two_dp(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _score_snapshot(score):
    return {
        "student": str(score.student_id),
        "ca_score": _two_dp(score.ca_score),
        "exam_score": _two_dp(score.exam_score),
        "total": _two_dp(score.total),
        "grade": score.grade,
    }


def _locked_result(result_id, actor):
    """Fetch a result row-locked for the current transaction, scoped to the
    actor's institution. All state checks after this read are race-free."""
    try:
        return (
            CourseResult.all_objects.select_for_update()
            .select_related("course__department")
            .get(pk=result_id, institution_id=actor.institution_id)
        )
    except CourseResult.DoesNotExist:
        raise NotFound("Result not found.") from None


def create_draft_result(*, lecturer, course, session, semester):
    if semester.session_id != session.id:
        raise ValidationError({"semester": "Semester does not belong to the selected session."})
    if not lecturer_can_access_course(lecturer, course, session, semester):
        raise PermissionDenied("You are not assigned to this course for the selected term.")

    try:
        with transaction.atomic():
            result = CourseResult.all_objects.create(
                institution=lecturer.institution,
                course=course,
                session=session,
                semester=semester,
                lecturer=lecturer,
            )
            _log(
                result=result,
                actor=lecturer,
                action=AuditAction.RESULT_CREATED,
                after={"status": ResultStatus.DRAFT.value},
            )
    except IntegrityError:
        raise ValidationError(
            {"course": "A result sheet already exists for this course and term."}
        ) from None
    return result


def record_score(*, actor, result_id, student, ca_score, exam_score):
    """Create or update the current score row for a student, atomically with
    its audit entry. Locks the result so a concurrent submit cannot interleave."""
    with transaction.atomic():
        result = _locked_result(result_id, actor)
        if not _owns_result(actor, result):
            raise PermissionDenied("Only the lecturer who owns this result sheet can enter scores.")
        if result.status not in LECTURER_EDITABLE_STATUSES:
            raise PermissionDenied("This result has been submitted and is locked for editing.")
        if not lecturer_can_access_course(actor, result.course, result.session, result.semester):
            raise PermissionDenied("You are not assigned to this course for this term.")
        if not Enrolment.all_objects.filter(
            institution_id=result.institution_id,
            student=student,
            course=result.course,
            session=result.session,
            semester=result.semester,
        ).exists():
            raise ValidationError(
                {"student": "This student is not enrolled in the course for this term."}
            )

        ca_max = Decimal(result.course.effective_ca_weight)
        exam_max = Decimal(result.course.effective_exam_weight)
        errors = {}
        if not Decimal("0") <= ca_score <= ca_max:
            errors["ca_score"] = f"CA score must be between 0 and {ca_max}."
        if not Decimal("0") <= exam_score <= exam_max:
            errors["exam_score"] = f"Exam score must be between 0 and {exam_max}."
        if errors:
            raise ValidationError(errors)

        total = ca_score + exam_score
        grade = letter_grade(total)

        row = (
            StudentScore.all_objects.select_for_update()
            .filter(result=result, student=student, is_current=True)
            .first()
        )
        if row is None:
            row = StudentScore.all_objects.create(
                institution=result.institution,
                result=result,
                student=student,
                ca_score=ca_score,
                exam_score=exam_score,
                total=total,
                grade=grade,
            )
            _log(
                result=result,
                actor=actor,
                action=AuditAction.SCORE_ADDED,
                score=row,
                after=_score_snapshot(row),
            )
        else:
            before = _score_snapshot(row)
            row.ca_score = ca_score
            row.exam_score = exam_score
            row.total = total
            row.grade = grade
            row.save(update_fields=["ca_score", "exam_score", "total", "grade", "updated_at"])
            _log(
                result=result,
                actor=actor,
                action=AuditAction.SCORE_CHANGED,
                score=row,
                before=before,
                after=_score_snapshot(row),
            )
    return row


def transition_result(*, actor, result_id, to_status, reason=""):
    """Move a result through the pipeline. The rule table is consulted against
    the row-locked current state, so a stale client can never double-apply or
    skip a step."""
    reason = (reason or "").strip()
    with transaction.atomic():
        result = _locked_result(result_id, actor)

        rule = TRANSITIONS.get((result.status, to_status))
        if rule is None:
            raise ValidationError(
                {"status": (f"A result in state '{result.status}' cannot move to '{to_status}'.")}
            )
        required_role, scope_check, reason_required = rule
        if actor.role != required_role or not scope_check(actor, result):
            raise PermissionDenied("You cannot perform this transition on this result.")
        if reason_required and not reason:
            raise ValidationError({"reason": "A reason is required when returning a result."})
        if (
            to_status == ResultStatus.SUBMITTED_TO_HOD
            and not StudentScore.all_objects.filter(result=result, is_current=True).exists()
        ):
            raise ValidationError({"status": "Cannot submit a result sheet with no scores."})

        before = result.status
        result.status = to_status
        result.returned_reason = reason if to_status == ResultStatus.RETURNED else ""
        result.save(update_fields=["status", "returned_reason", "updated_at"])
        _log(
            result=result,
            actor=actor,
            action=AuditAction.STATUS_CHANGED,
            before={"status": before},
            after={"status": to_status.value},
            reason=reason,
        )
    return result


def submit_result(*, actor, result_id):
    return transition_result(
        actor=actor, result_id=result_id, to_status=ResultStatus.SUBMITTED_TO_HOD
    )


def visible_results(user):
    """Role-scoped queryset: lecturers see their own sheets, HODs their
    department, deans their faculty, senate/school admins the institution."""
    qs = CourseResult.objects.all()
    role = getattr(user, "role", None)
    if role == Role.LECTURER:
        return qs.filter(lecturer=user)
    if role == Role.HOD:
        return qs.filter(course__department_id=user.department_id)
    if role == Role.DEAN:
        return qs.filter(course__department__faculty_id=user.faculty_id)
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs
    return qs.none()
