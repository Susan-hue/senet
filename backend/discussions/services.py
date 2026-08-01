"""Discussion services: posting, participation limits and moderation.

Who may do what:

* post a thread or reply — anyone with a place on the course-term (enrolled
  student or teaching staff), unless the thread is locked, which leaves only
  staff;
* pin or lock a thread — teaching staff only;
* remove a thread or reply — its own author, or teaching staff.
"""

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.services import (
    can_access_course,
    can_manage_course,
    scope_to_accessible_courses,
)
from discussions.models import Reply, Thread


def _thread_term(thread):
    return thread.course, thread.session, thread.semester


def _require_participant(user, course, session, semester):
    if not can_access_course(user, course, session, semester):
        raise PermissionDenied("You do not take part in this course for this term.")


def _require_manager(user, course, session, semester):
    if not can_manage_course(user, course, session, semester):
        raise PermissionDenied("Only this course's teaching staff can do that.")


def can_moderate(user, thread):
    return can_manage_course(user, *_thread_term(thread))


# --------------------------------------------------------------------------- #
# Reading                                                                      #
# --------------------------------------------------------------------------- #


def visible_threads(user, *, course=None, session=None, semester=None):
    """Live threads on the course-terms the user takes part in.

    Removed threads are gone for everyone, moderators included: the row is kept
    for the record, not to be browsed. Each is annotated with its live reply
    count so a board listing does not need one query per row.
    """
    qs = scope_to_accessible_courses(Thread.objects.filter(is_removed=False), user)
    if course is not None:
        qs = qs.filter(course=course, session=session, semester=semester)
    return qs.annotate(reply_count=Count("replies", filter=Q(replies__is_removed=False)))


def visible_replies(user, *, thread):
    _require_participant(user, *_thread_term(thread))
    return Reply.all_objects.filter(
        thread=thread, is_removed=False, institution_id=thread.institution_id
    ).select_related("author")


# --------------------------------------------------------------------------- #
# Threads                                                                      #
# --------------------------------------------------------------------------- #


def create_thread(*, actor, course, session, semester, title, body, is_pinned=False):
    _require_participant(actor, course, session, semester)
    if not body.strip():
        raise ValidationError({"body": "A thread needs a body."})
    # Pinning is a moderator act, so a student asking for it is simply ignored
    # rather than refused — the thread is still what they wanted to post.
    pinned = bool(is_pinned) and can_manage_course(actor, course, session, semester)

    now = timezone.now()
    return Thread.all_objects.create(
        institution=course.institution,
        course=course,
        session=session,
        semester=semester,
        author=actor,
        title=title,
        body=body,
        is_pinned=pinned,
        last_activity_at=now,
    )


def update_thread(*, actor, thread, **changes):
    """Edit a thread. The author may rewrite their own words; pinning and
    locking are moderator switches whoever asks for them."""
    if thread.is_removed:
        raise ValidationError({"thread": "This thread has been removed."})

    is_author = thread.author_id == actor.id
    moderator = can_moderate(actor, thread)
    if not (is_author or moderator):
        raise PermissionDenied("You can only edit your own thread.")

    fields = []
    for field in ("title", "body"):
        if changes.get(field) is not None:
            if field == "body" and not changes[field].strip():
                raise ValidationError({"body": "A thread needs a body."})
            setattr(thread, field, changes[field])
            fields.append(field)

    for field in ("is_pinned", "is_locked"):
        if changes.get(field) is not None:
            if not moderator:
                raise PermissionDenied("Only this course's teaching staff can do that.")
            setattr(thread, field, changes[field])
            fields.append(field)

    if fields:
        thread.save(update_fields=fields + ["updated_at"])
    return thread


def remove_thread(*, actor, thread):
    if thread.author_id != actor.id and not can_moderate(actor, thread):
        raise PermissionDenied("You can only remove your own thread.")
    if thread.is_removed:
        return thread
    thread.is_removed = True
    thread.removed_by = actor
    thread.removed_at = timezone.now()
    thread.save(update_fields=["is_removed", "removed_by", "removed_at", "updated_at"])
    return thread


# --------------------------------------------------------------------------- #
# Replies                                                                      #
# --------------------------------------------------------------------------- #


def create_reply(*, actor, thread, body):
    if thread.is_removed:
        raise ValidationError({"thread": "This thread has been removed."})
    course, session, semester = _thread_term(thread)
    _require_participant(actor, course, session, semester)
    if thread.is_locked and not can_manage_course(actor, course, session, semester):
        raise PermissionDenied("This thread is locked.")
    if not body.strip():
        raise ValidationError({"body": "A reply needs a body."})

    reply = Reply.all_objects.create(
        institution=thread.institution, thread=thread, author=actor, body=body
    )
    thread.last_activity_at = reply.created_at
    thread.save(update_fields=["last_activity_at", "updated_at"])
    return reply


def update_reply(*, actor, reply, body):
    if reply.is_removed:
        raise ValidationError({"reply": "This reply has been removed."})
    if reply.author_id != actor.id:
        raise PermissionDenied("You can only edit your own reply.")
    if not body.strip():
        raise ValidationError({"body": "A reply needs a body."})
    reply.body = body
    reply.save(update_fields=["body", "updated_at"])
    return reply


def remove_reply(*, actor, reply):
    if reply.author_id != actor.id and not can_moderate(actor, reply.thread):
        raise PermissionDenied("You can only remove your own reply.")
    if reply.is_removed:
        return reply
    reply.is_removed = True
    reply.removed_by = actor
    reply.removed_at = timezone.now()
    reply.save(update_fields=["is_removed", "removed_by", "removed_at", "updated_at"])
    return reply
