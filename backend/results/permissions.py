from rest_framework.permissions import BasePermission

from accounts.models import Role

RESULT_PIPELINE_ROLES = (
    Role.LECTURER,
    Role.HOD,
    Role.DEAN,
    Role.SENATE_ADMIN,
    Role.SCHOOL_ADMIN,
)


def _is_member(user):
    return bool(user and user.is_authenticated and user.institution_id)


class CanViewResults(BasePermission):
    message = "You do not have access to the results pipeline."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in RESULT_PIPELINE_ROLES


class IsLecturer(BasePermission):
    message = "Only a lecturer can perform this action."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role == Role.LECTURER


class IsHOD(BasePermission):
    message = "Only a Head of Department can perform this action."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role == Role.HOD


class IsDean(BasePermission):
    message = "Only a Dean can perform this action."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role == Role.DEAN


class IsSenateAdmin(BasePermission):
    message = "Only a Senate Administrator can perform this action."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role == Role.SENATE_ADMIN
