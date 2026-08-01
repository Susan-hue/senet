"""Shared plumbing for the course-scoped teaching apps.

Content, announcements and discussions all hang off the same thing: a course in
a term. They resolve that triple the same way, gate on the same access rules
(``accounts.services.can_manage_course`` / ``can_access_course``), and paginate
the same way — so it lives here once rather than three times.
"""

from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission

from accounts.models import Course, Role, Semester, Session
from accounts.pagination import paginated_response as paginated
from accounts.services import can_access_course, can_manage_course
from tenancy.serializers import TenantScopedSerializerMixin
from tenancy.views import TenantAPIView

__all__ = [
    "CourseTermSerializer",
    "IsCourseManager",
    "IsCourseParticipant",
    "MANAGER_ROLES",
    "PARTICIPANT_ROLES",
    "TenantAPIView",
    "get_scoped",
    "paginated",
    "require_access",
    "require_manager",
    "resolve_course_term",
]

MANAGER_ROLES = (
    Role.LECTURER,
    Role.HOD,
    Role.DEAN,
    Role.SENATE_ADMIN,
    Role.SCHOOL_ADMIN,
)

PARTICIPANT_ROLES = MANAGER_ROLES + (Role.STUDENT, Role.COURSE_REP)


def _is_member(user):
    return bool(user and user.is_authenticated and user.institution_id)


class IsCourseParticipant(BasePermission):
    """Any role that can hold a place on a course. Which *course* they may touch
    is decided per object, not here."""

    message = "You do not have access to course material."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in PARTICIPANT_ROLES


class IsCourseManager(BasePermission):
    message = "Only teaching staff can manage course material."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in MANAGER_ROLES


class CourseTermSerializer(TenantScopedSerializerMixin, serializers.Serializer):
    """The course-term triple, with querysets bound to the caller's tenant.

    Binding the querysets is the tenant check: an id from another institution
    simply is not a valid choice, so it fails validation rather than reaching a
    permission check that might be written to assume otherwise.
    """

    tenant_scoped_fields = {"course": Course, "session": Session, "semester": Semester}

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.none())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.none())

    def validate(self, attrs):
        session = attrs.get("session")
        semester = attrs.get("semester")
        if session and semester and semester.session_id != session.id:
            raise serializers.ValidationError(
                {"semester": "Semester does not belong to the selected session."}
            )
        return attrs


def resolve_course_term(request, *, required=True):
    """Read course/session/semester from the query string.

    Returns ``(course, session, semester)``, each None when absent. Ids that
    belong to another tenant resolve to None and therefore read as missing —
    a cross-tenant probe learns nothing beyond "you must supply a course".
    """
    institution_id = request.user.institution_id
    values = {}
    for name, model in (("course", Course), ("session", Session), ("semester", Semester)):
        raw = request.query_params.get(name)
        values[name] = (
            model.all_objects.filter(pk=raw, institution_id=institution_id).first() if raw else None
        )

    if required and not all(values.values()):
        raise serializers.ValidationError(
            {
                name: "This query parameter is required."
                for name, value in values.items()
                if value is None
            }
        )
    return values["course"], values["session"], values["semester"]


def require_manager(user, course, session, semester):
    if not can_manage_course(user, course, session, semester):
        raise PermissionDenied("You do not manage this course for this term.")


def require_access(user, course, session, semester):
    """Gate a read. A user with no place on the course gets a 404 rather than a
    403: whether a given course holds material is not theirs to learn."""
    if not can_access_course(user, course, session, semester):
        raise NotFound("Not found.")


def get_scoped(model, pk, user, *, select_related=(), message="Not found."):
    """Fetch one row by id, inside the caller's tenant.

    ``all_objects`` with an explicit institution filter rather than the tenant
    manager, so the lookup is correct even if scoping was never activated. A row
    in another institution is indistinguishable from one that does not exist.
    """
    qs = model.all_objects.filter(pk=pk, institution_id=user.institution_id)
    if select_related:
        qs = qs.select_related(*select_related)
    row = qs.first()
    if row is None:
        raise NotFound(message)
    return row
