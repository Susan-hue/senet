from rest_framework.permissions import BasePermission

from accounts.models import Role


def _is_member(user):
    return bool(user and user.is_authenticated and user.institution_id)


class IsLecturer(BasePermission):
    message = "Only a lecturer can perform this action."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role == Role.LECTURER


class IsStudent(BasePermission):
    message = "Only a student can perform this action."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in (
            Role.STUDENT,
            Role.COURSE_REP,
        )


class IsLecturerOrStudent(BasePermission):
    message = "You do not have access to assessments."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in (
            Role.LECTURER,
            Role.STUDENT,
            Role.COURSE_REP,
        )
