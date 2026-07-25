from rest_framework.permissions import BasePermission

from accounts.models import Role

_MANAGER_ROLES = (
    Role.LECTURER,
    Role.HOD,
    Role.DEAN,
    Role.SENATE_ADMIN,
    Role.SCHOOL_ADMIN,
)
_STUDENT_ROLES = (Role.STUDENT, Role.COURSE_REP)

_PROCTOR_VIEWER_ROLES = (
    Role.LECTURER,
    Role.HOD,
    Role.DEAN,
    Role.EXAM_OFFICER,
    Role.SENATE_ADMIN,
    Role.SCHOOL_ADMIN,
)


def _is_member(user):
    return bool(user and user.is_authenticated and user.institution_id)


class IsExamManager(BasePermission):
    """Roles allowed to author banks/questions/exams. Object-level scope (the
    specific course/term) is enforced in the service layer."""

    message = "You are not permitted to manage exams for this course."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in _MANAGER_ROLES


class IsStudent(BasePermission):
    message = "Only a student can sit an exam."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in _STUDENT_ROLES


class IsCbtParticipant(BasePermission):
    message = "You do not have access to the exam engine."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in (
            *_MANAGER_ROLES,
            *_STUDENT_ROLES,
        )


class IsProctoringReviewer(BasePermission):
    """Staff who may read proctoring data / act on flags. Per-attempt scope is
    enforced in the service layer; the exam officer has independent visibility."""

    message = "You are not permitted to view proctoring data."

    def has_permission(self, request, view):
        return _is_member(request.user) and request.user.role in _PROCTOR_VIEWER_ROLES
