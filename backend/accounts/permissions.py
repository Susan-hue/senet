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


class CanViewCourseAssignments(BasePermission):
    """Read access for admins, HODs and lecturers (scoped to their own rows in-view)."""

    message = "You cannot view course assignments."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.institution_id
            and user.role in (Role.SCHOOL_ADMIN, Role.HOD, Role.LECTURER)
        )


class CanViewEnrolments(BasePermission):
    """Read access for admins and lecturers (lecturers scoped to assigned courses in-view)."""

    message = "You cannot view enrolments."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.institution_id
            and user.role in (Role.SCHOOL_ADMIN, Role.LECTURER)
        )


class CanManageCourseAssignments(BasePermission):
    """A school admin, or an HOD (further scoped to their department in-view)."""

    message = (
        "Only a school administrator or an HOD (within their department) "
        "can manage course assignments."
    )

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.institution_id
            and user.role in (Role.SCHOOL_ADMIN, Role.HOD)
        )
