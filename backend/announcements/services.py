"""Announcement services.

Posting an announcement optionally notifies the class. That fan-out is
deliberately best-effort: the announcement is the record, the notification is a
convenience, and a provider or configuration problem must never cost a lecturer
the post they just wrote.
"""

import logging

from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Enrolment
from accounts.services import can_manage_course, scope_to_accessible_courses
from announcements.models import Announcement

logger = logging.getLogger(__name__)


def _require_manager(user, course, session, semester):
    if not can_manage_course(user, course, session, semester):
        raise PermissionDenied("You do not manage this course for this term.")


def visible_announcements(user, *, course=None, session=None, semester=None):
    qs = scope_to_accessible_courses(Announcement.objects.all(), user)
    if course is not None:
        qs = qs.filter(course=course, session=session, semester=semester)
    return qs


def _notify_class(announcement):
    """Tell the enrolled students something was posted.

    Wrapped whole: notifications are a side effect of the post, not part of it.
    """
    try:
        from notifications.models import NotificationEvent
        from notifications.services import notify_users

        students = [
            enrolment.student
            for enrolment in Enrolment.all_objects.filter(
                institution_id=announcement.institution_id,
                course_id=announcement.course_id,
                session_id=announcement.session_id,
                semester_id=announcement.semester_id,
            ).select_related("student")
        ]
        if not students:
            return
        notify_users(
            institution=announcement.institution,
            event=NotificationEvent.ANNOUNCEMENT_POSTED,
            users=students,
            context={
                "course_code": announcement.course.code,
                "title": announcement.title,
                "author_name": announcement.author.full_name,
            },
            dedupe_prefix=f"announcement:{announcement.id}",
        )
    except Exception:  # noqa: BLE001 - the post stands whatever the mailer does
        logger.exception("Could not queue notifications for announcement %s", announcement.id)


def create_announcement(
    *, actor, course, session, semester, title, body, is_pinned=False, notify=True
):
    _require_manager(actor, course, session, semester)
    if not body.strip():
        raise ValidationError({"body": "An announcement needs a body."})

    announcement = Announcement.all_objects.create(
        institution=course.institution,
        course=course,
        session=session,
        semester=semester,
        author=actor,
        title=title,
        body=body,
        is_pinned=is_pinned,
    )
    if notify:
        _notify_class(announcement)
    return announcement


def update_announcement(*, actor, announcement, **changes):
    _require_manager(actor, announcement.course, announcement.session, announcement.semester)
    fields = []
    for field in ("title", "body", "is_pinned"):
        if field in changes and changes[field] is not None:
            setattr(announcement, field, changes[field])
            fields.append(field)
    if "body" in changes and changes["body"] is not None and not changes["body"].strip():
        raise ValidationError({"body": "An announcement needs a body."})
    if fields:
        announcement.save(update_fields=fields + ["updated_at"])
    return announcement


def delete_announcement(*, actor, announcement):
    _require_manager(actor, announcement.course, announcement.session, announcement.semester)
    announcement.delete()
