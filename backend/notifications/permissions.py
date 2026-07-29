from rest_framework.permissions import BasePermission

from accounts.models import Role

_STUDENT_ROLES = (Role.STUDENT, Role.COURSE_REP)


class IsStudentMember(BasePermission):
    """Only a student registers a phone for the SMS/USSD result check — it is
    their own result the binding unlocks."""

    message = "Only a student can register for the SMS result check."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.institution_id and user.role in _STUDENT_ROLES
        )


class CanViewNotifications(BasePermission):
    message = "You cannot view notifications."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.institution_id and user.role)
