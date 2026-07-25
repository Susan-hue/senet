from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import Role
from auditor.authentication import AuditorPrincipal


class IsSchoolAdmin(BasePermission):
    message = "Only a School Administrator can manage auditor tokens."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "institution_id", None)
            and getattr(user, "role", None) == Role.SCHOOL_ADMIN
        )


class IsValidAuditor(BasePermission):
    """A valid auditor token AND a safe (read-only) HTTP method.

    The method guard is a hard backstop: even if a write handler were ever added
    to an auditor view, this permission refuses anything outside SAFE_METHODS, so
    the auditor path cannot mutate data through any route."""

    message = "A valid auditor token is required for read-only access."

    def has_permission(self, request, view):
        return isinstance(request.user, AuditorPrincipal) and request.method in SAFE_METHODS
