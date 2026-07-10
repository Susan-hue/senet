from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Enrolment, Role
from accounts.services import lecturer_can_access_course
from assessments.models import AssessmentGrade, AssessmentItem, Submission

TWO_DP = Decimal("0.01")


def ca_weight_used(course, session, semester, exclude_pk=None):
    """Total CA weight already claimed by this course-term's items."""
    qs = AssessmentItem.all_objects.filter(course=course, session=session, semester=semester)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.aggregate(total=Sum("weight"))["total"] or Decimal("0")


def _require_assigned_lecturer(lecturer, course, session, semester):
    if not lecturer_can_access_course(lecturer, course, session, semester):
        raise PermissionDenied("You are not assigned to this course for the selected term.")


def can_read_item_grades(user, item):
    """Whether ``user`` may read the recorded grades for ``item``.

    The lecturer assigned to the item's course-term, the HOD of its department,
    the dean of its faculty, and school/senate admins across the tenant. Callers
    must already have scoped ``item`` to the user's institution.
    """
    role = getattr(user, "role", None)
    if role == Role.LECTURER:
        return lecturer_can_access_course(user, item.course, item.session, item.semester)
    if role == Role.HOD:
        return user.department_id is not None and user.department_id == item.course.department_id
    if role == Role.DEAN:
        return user.faculty_id is not None and user.faculty_id == item.course.department.faculty_id
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return True
    return False


def create_item(*, lecturer, course, session, semester, title, kind, max_score, weight, due_date):
    if semester.session_id != session.id:
        raise ValidationError({"semester": "Semester does not belong to the selected session."})
    _require_assigned_lecturer(lecturer, course, session, semester)

    errors = {}
    if max_score <= 0:
        errors["max_score"] = "Max score must be greater than zero."
    if weight <= 0:
        errors["weight"] = "Weight must be greater than zero."
    else:
        ca_portion = Decimal(course.effective_ca_weight)
        used = ca_weight_used(course, session, semester)
        if used + weight > ca_portion:
            errors["weight"] = (
                f"CA items for this course already use {used} of {ca_portion} points; "
                f"adding {weight} would exceed the CA portion."
            )
    if AssessmentItem.all_objects.filter(
        course=course, session=session, semester=semester, title=title
    ).exists():
        errors["title"] = "An assessment item with this title already exists for this term."
    if errors:
        raise ValidationError(errors)

    return AssessmentItem.all_objects.create(
        institution=lecturer.institution,
        course=course,
        session=session,
        semester=semester,
        created_by=lecturer,
        title=title,
        kind=kind,
        max_score=max_score,
        weight=weight,
        due_date=due_date,
    )


def submit_file(*, student, item, upload):
    """Store a student's file for an item. Late uploads are flagged, never
    blocked — the lecturer applies their own policy at grading time."""
    if (
        student.institution_id != item.institution_id
        or not Enrolment.all_objects.filter(
            institution_id=item.institution_id,
            student=student,
            course=item.course,
            session=item.session,
            semester=item.semester,
        ).exists()
    ):
        raise PermissionDenied("You are not enrolled in this course for this term.")

    existing = Submission.all_objects.filter(item=item, student=student).first()
    if (
        existing is not None
        and AssessmentGrade.all_objects.filter(item=item, student=student).exists()
    ):
        raise ValidationError(
            {"file": "This submission has already been graded and can no longer be replaced."}
        )

    now = timezone.now()
    if existing is None:
        return Submission.all_objects.create(
            institution=item.institution,
            item=item,
            student=student,
            file=upload,
            original_filename=upload.name or "",
            submitted_at=now,
            is_late=now > item.due_date,
        )

    existing.file = upload
    existing.original_filename = upload.name or ""
    existing.submitted_at = now
    existing.is_late = now > item.due_date
    existing.save(
        update_fields=["file", "original_filename", "submitted_at", "is_late", "updated_at"]
    )
    return existing


def grade_student(*, lecturer, item, student, score, feedback="", is_released=False):
    _require_assigned_lecturer(lecturer, item.course, item.session, item.semester)

    if not Enrolment.all_objects.filter(
        institution_id=item.institution_id,
        student=student,
        course=item.course,
        session=item.session,
        semester=item.semester,
    ).exists():
        raise ValidationError(
            {"student": "This student is not enrolled in the course for this term."}
        )
    if not Decimal("0") <= score <= item.max_score:
        raise ValidationError(
            {"score": f"Score must be between 0 and {item.max_score} for this item."}
        )

    submission = Submission.all_objects.filter(item=item, student=student).first()
    grade = AssessmentGrade.all_objects.filter(item=item, student=student).first()
    if grade is None:
        return AssessmentGrade.all_objects.create(
            institution=item.institution,
            item=item,
            student=student,
            submission=submission,
            score=score,
            feedback=feedback,
            graded_by=lecturer,
            is_released=is_released,
        )

    grade.score = score
    grade.feedback = feedback
    grade.graded_by = lecturer
    grade.is_released = is_released
    grade.submission = submission
    grade.save(
        update_fields=[
            "score",
            "feedback",
            "graded_by",
            "is_released",
            "submission",
            "updated_at",
        ]
    )
    return grade


def aggregate_ca_for_student(course, session, semester, student):
    """Weighted CA total from the student's graded items.

    Each grade contributes (score / max_score) * weight, so the result is in
    percentage points of the course total and can be written straight into the
    results pipeline's CA entry. Ungraded items contribute nothing.
    """
    grades = AssessmentGrade.all_objects.filter(
        item__course=course,
        item__session=session,
        item__semester=semester,
        student=student,
    ).select_related("item")

    total = Decimal("0")
    for grade in grades:
        item = grade.item
        total += (grade.score / item.max_score) * item.weight
    return total.quantize(TWO_DP)
