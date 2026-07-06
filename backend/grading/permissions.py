from rest_framework.permissions import BasePermission

from accounts.models import Role

STANDING_VIEWER_ROLES = (
    Role.STUDENT,
    Role.COURSE_REP,
    Role.COURSE_ADVISER,
    Role.HOD,
    Role.DEAN,
    Role.SENATE_ADMIN,
    Role.SCHOOL_ADMIN,
)

COMPUTE_TRIGGER_ROLES = (Role.HOD, Role.DEAN, Role.SENATE_ADMIN, Role.SCHOOL_ADMIN)


def _is_member(user):
    return bool(user and user.is_authenticated and user.institution_id)


class CanViewStanding(BasePermission):
    message = "You do not have access to academic standing."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in STANDING_VIEWER_ROLES


class CanTriggerComputation(BasePermission):
    message = "Only an HOD, dean or administrator can trigger a computation run."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in COMPUTE_TRIGGER_ROLES


def can_view_student(actor, student):
    """Scope: students see themselves; advisers and HODs their department;
    deans their faculty; senate/school admins the whole institution."""
    if actor.institution_id != student.institution_id:
        return False
    role = actor.role
    if role in (Role.STUDENT, Role.COURSE_REP):
        return actor.id == student.id
    if role in (Role.COURSE_ADVISER, Role.HOD):
        return actor.department_id is not None and actor.department_id == student.department_id
    if role == Role.DEAN:
        if actor.faculty_id is None:
            return False
        if student.faculty_id == actor.faculty_id:
            return True
        return (
            student.department_id is not None and student.department.faculty_id == actor.faculty_id
        )
    return role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN)
