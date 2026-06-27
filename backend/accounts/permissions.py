from rest_framework.permissions import BasePermission

from accounts.models import Role


class IsTenantMember(BasePermission):
    """Authenticated user that belongs to an institution (tenant scope)."""

    message = "You must belong to an institution to access this resource."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.institution_id and user.role)


class IsSchoolAdmin(BasePermission):
    """Tenant member whose role is school_admin (structural changes)."""

    message = "Only a school administrator can perform this action."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.institution_id
            and user.role == Role.SCHOOL_ADMIN
        )
