"""CBT-as-CA-item integration: a graded CBT can produce a Continuous Assessment
item's score, feeding the existing weighted CA aggregation in the assessments app.

Scores flow only when an attempt is graded, and only the assigned lecturer (or an
admin in scope) may link. Everything is tenant-scoped.
"""

from decimal import Decimal

from rest_framework.exceptions import PermissionDenied, ValidationError

from cbt.models import AttemptStatus, ExamAttempt
from cbt.services import can_manage_exam

TWO_DP = Decimal("0.01")


def link_exam_to_ca_item(*, actor, exam, item):
    if not can_manage_exam(actor, exam.course, exam.session, exam.semester):
        raise PermissionDenied(
            "Only the assigned lecturer (or an admin in scope) can link this exam."
        )
    if item.institution_id != exam.institution_id:
        raise ValidationError({"item": "The item and exam must belong to the same institution."})
    if (item.course_id, item.session_id, item.semester_id) != (
        exam.course_id,
        exam.session_id,
        exam.semester_id,
    ):
        raise ValidationError(
            {"item": "The CA item must be for the same course, session and semester as the exam."}
        )

    exam.assessment_item = item
    exam.save(update_fields=["assessment_item", "updated_at"])
    for attempt in ExamAttempt.all_objects.filter(
        exam=exam, status=AttemptStatus.GRADED
    ).select_related("student"):
        sync_ca_grade_for_attempt(attempt)
    return exam


def sync_ca_grade_for_attempt(attempt):
    """Upsert the student's AssessmentGrade from a graded, linked CBT attempt. The
    exam score is scaled onto the item's mark scale so the existing
    (score / max_score) * weight aggregation stays correct. No-op if unlinked,
    ungraded, or the attempt has no marks; never raises for a missing link."""
    exam = attempt.exam
    if (
        not exam.assessment_item_id
        or attempt.status != AttemptStatus.GRADED
        or not attempt.max_score
    ):
        return None

    from assessments.models import AssessmentGrade, AssessmentItem

    item = AssessmentItem.all_objects.filter(pk=exam.assessment_item_id).first()
    if item is None:
        return None

    ratio = Decimal(attempt.score) / Decimal(attempt.max_score)
    scaled = (ratio * item.max_score).quantize(TWO_DP)
    grade, _ = AssessmentGrade.all_objects.update_or_create(
        item=item,
        student=attempt.student,
        defaults={
            "institution_id": attempt.institution_id,
            "score": scaled,
            "graded_by": exam.created_by,
            "is_released": True,
        },
    )
    return grade
