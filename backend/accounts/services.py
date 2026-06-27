from django.db.models import Sum
from rest_framework import serializers

from accounts.models import Enrolment, Role
from tenancy.scoping import get_current_institution


def validate_enrolment(*, student, course, session, semester, institution):
    """Cross-field rules for an enrolment. Raises DRF ValidationError on failure."""
    errors = {}

    if student.role != Role.STUDENT:
        errors["student"] = "Enrolments can only be created for users with the student role."
    elif institution is not None and student.institution_id != institution.id:
        errors["student"] = "Student must belong to the same institution."

    if semester.session_id != session.id:
        errors["semester"] = "Semester does not belong to the selected session."

    if Enrolment.objects.filter(
        student=student, course=course, session=session, semester=semester
    ).exists():
        errors["non_field_errors"] = [
            "This student is already enrolled in this course for the selected session and semester."
        ]

    if errors:
        raise serializers.ValidationError(errors)


def term_credit_units(*, student, session, semester, exclude_pk=None):
    """Total credit units a student already carries for a session + semester."""
    qs = Enrolment.objects.filter(student=student, session=session, semester=semester)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.aggregate(total=Sum("course__credit_units"))["total"] or 0


def validate_credit_load(institution, total_units):
    """Reject a per-semester credit load outside the institution's min/max.

    Reusable when a student finalises registration; raises DRF ValidationError.
    """
    if total_units < institution.min_credit_units_per_semester:
        raise serializers.ValidationError(
            f"Total credit units ({total_units}) is below the institution minimum of "
            f"{institution.min_credit_units_per_semester}."
        )
    if total_units > institution.max_credit_units_per_semester:
        raise serializers.ValidationError(
            f"Total credit units ({total_units}) exceeds the institution maximum of "
            f"{institution.max_credit_units_per_semester}."
        )


def enrol_student(*, student, course, session, semester):
    """Validate and create an enrolment, stamped with the current institution."""
    institution = get_current_institution()
    validate_enrolment(
        student=student,
        course=course,
        session=session,
        semester=semester,
        institution=institution,
    )

    # Enforce only the upper bound incrementally; the minimum is a floor checked
    # via validate_credit_load() when a student finalises registration.
    if institution is not None:
        prospective = (
            term_credit_units(student=student, session=session, semester=semester)
            + course.credit_units
        )
        if prospective > institution.max_credit_units_per_semester:
            raise serializers.ValidationError(
                {
                    "course": (
                        f"Adding this course brings the semester load to {prospective} units, "
                        f"above the maximum of {institution.max_credit_units_per_semester}."
                    )
                }
            )

    return Enrolment.objects.create(
        student=student, course=course, session=session, semester=semester
    )
