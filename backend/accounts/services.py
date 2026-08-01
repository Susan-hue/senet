from django.db.models import Exists, OuterRef, Sum
from rest_framework import serializers

from accounts.models import CourseAssignment, Enrolment, Role
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


def validate_course_assignment(*, actor, lecturer, course, session, semester, institution):
    """Cross-field rules for a lecturer-to-course assignment.

    ``actor`` is the user making the assignment; an HOD may only assign within
    their own department. Raises DRF ValidationError on failure.
    """
    errors = {}

    if lecturer.role != Role.LECTURER:
        errors["lecturer"] = "Only users with the lecturer role can be assigned to a course."
    elif institution is not None and lecturer.institution_id != institution.id:
        errors["lecturer"] = "Lecturer must belong to the same institution."

    if semester.session_id != session.id:
        errors["semester"] = "Semester does not belong to the selected session."

    if actor is not None and actor.role == Role.HOD and course.department_id != actor.department_id:
        errors["course"] = "An HOD can only assign lecturers to courses in their own department."

    if CourseAssignment.objects.filter(
        lecturer=lecturer, course=course, session=session, semester=semester
    ).exists():
        errors["non_field_errors"] = [
            "This lecturer is already assigned to this course for the selected session and semester."
        ]

    if errors:
        raise serializers.ValidationError(errors)


def assign_lecturer(*, actor, lecturer, course, session, semester):
    """Validate and create a course assignment, stamped with the current tenant."""
    institution = get_current_institution()
    validate_course_assignment(
        actor=actor,
        lecturer=lecturer,
        course=course,
        session=session,
        semester=semester,
        institution=institution,
    )
    return CourseAssignment.objects.create(
        lecturer=lecturer, course=course, session=session, semester=semester
    )


def lecturer_can_access_course(user, course, session, semester):
    """Whether ``user`` is a lecturer assigned to ``course`` for the given term.

    Context-independent (uses ``all_objects`` with explicit filters) so the
    results pipeline can call it from any context to enforce that a lecturer may
    only enter results for their assigned courses.
    """
    if user is None or getattr(user, "role", None) != Role.LECTURER:
        return False
    return CourseAssignment.all_objects.filter(
        lecturer=user, course=course, session=session, semester=semester
    ).exists()


STUDENT_ROLES = (Role.STUDENT, Role.COURSE_REP)


def student_is_enrolled(user, course, session, semester):
    """Whether ``user`` holds an enrolment in ``course`` for the given term."""
    if user is None or getattr(user, "role", None) not in STUDENT_ROLES:
        return False
    return Enrolment.all_objects.filter(
        student=user, course=course, session=session, semester=semester
    ).exists()


def can_manage_course(user, course, session, semester):
    """Whether ``user`` may author and moderate teaching material on a course.

    The lecturer assigned to that course-term, the HOD of the owning department,
    the dean of its faculty, and school/senate admins across the tenant. A
    lecturer is scoped to the course they actually teach — assignment to another
    course confers nothing here.
    """
    role = getattr(user, "role", None)
    if user is None or role is None:
        return False
    if user.institution_id != course.institution_id:
        return False
    if role == Role.LECTURER:
        return lecturer_can_access_course(user, course, session, semester)
    if role == Role.HOD:
        return user.department_id is not None and user.department_id == course.department_id
    if role == Role.DEAN:
        return user.faculty_id is not None and user.faculty_id == course.department.faculty_id
    return role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN)


def can_access_course(user, course, session, semester):
    """Whether ``user`` may read a course's teaching material: anyone who can
    manage it, plus the students enrolled in that course-term."""
    return can_manage_course(user, course, session, semester) or student_is_enrolled(
        user, course, session, semester
    )


def scope_to_accessible_courses(qs, user, prefix=""):
    """Narrow a queryset of course-term rows to the ones ``user`` may read.

    Rows must carry ``course``/``session``/``semester`` (optionally behind a
    relation ``prefix``). Managers see whole slices of the tenant, so their
    narrowing is a plain filter; a student's is an ``Exists`` against their own
    enrolments, which keeps the whole thing one query regardless of how many
    courses they take.
    """
    role = getattr(user, "role", None)
    if user is None or role is None:
        return qs.none()

    def field(name):
        return f"{prefix}{name}"

    if role == Role.LECTURER:
        assigned = CourseAssignment.all_objects.filter(
            lecturer=user,
            course=OuterRef(field("course")),
            session=OuterRef(field("session")),
            semester=OuterRef(field("semester")),
        )
        return qs.filter(Exists(assigned))
    if role in STUDENT_ROLES:
        enrolled = Enrolment.all_objects.filter(
            student=user,
            course=OuterRef(field("course")),
            session=OuterRef(field("session")),
            semester=OuterRef(field("semester")),
        )
        return qs.filter(Exists(enrolled))
    if role == Role.HOD:
        if user.department_id is None:
            return qs.none()
        return qs.filter(**{f"{field('course')}__department_id": user.department_id})
    if role == Role.DEAN:
        if user.faculty_id is None:
            return qs.none()
        return qs.filter(**{f"{field('course')}__department__faculty_id": user.faculty_id})
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs
    return qs.none()
