"""Content services: authoring, ordering, publication and read receipts.

Every write goes through here so the two rules that matter are stated once —
who may author on a course-term, and what a given item kind must carry.
"""

from django.db import transaction
from django.db.models import Exists, F, Max, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.services import (
    STUDENT_ROLES,
    can_access_course,
    can_manage_course,
    scope_to_accessible_courses,
)
from content.models import ContentItem, ContentView, Module

# What each kind of item must carry, and what it must not.
_REQUIRED_PAYLOAD = {
    ContentItem.Kind.FILE: ("file",),
    ContentItem.Kind.PAGE: ("body",),
    ContentItem.Kind.LINK: ("url",),
    # A video is either an upload or an embed, so it is checked separately.
    ContentItem.Kind.VIDEO: (),
}


def _require_manager(user, course, session, semester):
    if not can_manage_course(user, course, session, semester):
        raise PermissionDenied("You do not manage this course for this term.")


def _module_term(module):
    return module.course, module.session, module.semester


def require_module_manager(user, module):
    _require_manager(user, *_module_term(module))


def _next_position(queryset):
    return (queryset.aggregate(top=Max("position"))["top"] or 0) + 10


# --------------------------------------------------------------------------- #
# Visibility                                                                   #
# --------------------------------------------------------------------------- #


def _is_student(user):
    return getattr(user, "role", None) in STUDENT_ROLES


def visible_modules(user, *, course=None, session=None, semester=None):
    """Modules the user may see. Students are held to published rows only."""
    qs = scope_to_accessible_courses(Module.objects.all(), user)
    if course is not None:
        qs = qs.filter(course=course, session=session, semester=semester)
    if _is_student(user):
        qs = qs.filter(is_published=True)
    return qs


def _released_filter():
    return Q(available_from__isnull=True) | Q(available_from__lte=timezone.now())


def visible_items(user, *, module=None):
    """Items the user may see.

    For a student that means: the module is published, the item is published,
    and any release date has passed. Staff see drafts and unreleased items so
    they can build a term in advance.
    """
    qs = scope_to_accessible_courses(ContentItem.objects.all(), user, prefix="module__")
    if module is not None:
        qs = qs.filter(module=module)
    if _is_student(user):
        qs = qs.filter(is_published=True, module__is_published=True).filter(_released_filter())
    return qs


def item_is_visible_to(user, item):
    """Whether one already-fetched item may be shown to ``user``."""
    module = item.module
    course, session, semester = _module_term(module)
    if can_manage_course(user, course, session, semester):
        return True
    if not can_access_course(user, course, session, semester):
        return False
    if not (item.is_published and module.is_published):
        return False
    return item.available_from is None or item.available_from <= timezone.now()


# --------------------------------------------------------------------------- #
# Modules                                                                      #
# --------------------------------------------------------------------------- #


def create_module(
    *, actor, course, session, semester, title, description="", is_published=False, position=None
):
    _require_manager(actor, course, session, semester)
    if Module.all_objects.filter(
        course=course, session=session, semester=semester, title=title
    ).exists():
        raise ValidationError({"title": "A module with this title already exists for this term."})

    siblings = Module.all_objects.filter(course=course, session=session, semester=semester)
    return Module.all_objects.create(
        institution=course.institution,
        course=course,
        session=session,
        semester=semester,
        created_by=actor,
        title=title,
        description=description,
        is_published=is_published,
        position=_next_position(siblings) if position is None else position,
    )


def update_module(*, actor, module, **changes):
    require_module_manager(actor, module)
    title = changes.get("title")
    if title and title != module.title:
        clash = Module.all_objects.filter(
            course=module.course,
            session=module.session,
            semester=module.semester,
            title=title,
        ).exclude(pk=module.pk)
        if clash.exists():
            raise ValidationError(
                {"title": "A module with this title already exists for this term."}
            )

    fields = []
    for field in ("title", "description", "is_published", "position"):
        if field in changes and changes[field] is not None:
            setattr(module, field, changes[field])
            fields.append(field)
    if fields:
        module.save(update_fields=fields + ["updated_at"])
    return module


def delete_module(*, actor, module):
    """Remove a module and the items inside it.

    Items cascade; their read receipts cascade with them. Nothing downstream
    (a grade, a result) depends on content, so this is a real delete rather
    than the soft removal the discussion boards use.
    """
    require_module_manager(actor, module)
    module.delete()


@transaction.atomic
def reorder_modules(*, actor, course, session, semester, module_ids):
    """Rewrite the order of a course-term's modules from an explicit id list."""
    _require_manager(actor, course, session, semester)
    modules = {
        str(m.id): m
        for m in Module.all_objects.filter(course=course, session=session, semester=semester)
    }
    ids = [str(i) for i in module_ids]
    if set(ids) != set(modules) or len(ids) != len(modules):
        raise ValidationError({"modules": "Provide every module in this course-term exactly once."})
    for index, module_id in enumerate(ids, start=1):
        module = modules[module_id]
        module.position = index * 10
        module.save(update_fields=["position", "updated_at"])
    return [modules[i] for i in ids]


# --------------------------------------------------------------------------- #
# Items                                                                        #
# --------------------------------------------------------------------------- #


def _validate_payload(kind, *, file, url, body, partial_of=None):
    """Check an item carries what its kind needs.

    On an update ``partial_of`` is the stored item, so a field left out of the
    request keeps whatever is already there instead of reading as missing.
    """

    def current(name, incoming):
        if incoming not in (None, ""):
            return incoming
        return getattr(partial_of, name, None) if partial_of is not None else None

    file_value = current("file", file)
    url_value = current("url", url)
    body_value = current("body", body)

    errors = {}
    if kind == ContentItem.Kind.VIDEO:
        if not file_value and not url_value:
            errors["url"] = "A video item needs either an uploaded file or an embed URL."
    else:
        for field in _REQUIRED_PAYLOAD[kind]:
            value = {"file": file_value, "url": url_value, "body": body_value}[field]
            if not value:
                errors[field] = f"A {kind} item requires this field."
    if errors:
        raise ValidationError(errors)


def create_item(
    *,
    actor,
    module,
    title,
    kind,
    description="",
    file=None,
    url="",
    body="",
    is_published=False,
    available_from=None,
    position=None,
):
    require_module_manager(actor, module)
    _validate_payload(kind, file=file, url=url, body=body)

    siblings = ContentItem.all_objects.filter(module=module)
    return ContentItem.all_objects.create(
        institution=module.institution,
        module=module,
        created_by=actor,
        title=title,
        description=description,
        kind=kind,
        file=file,
        original_filename=getattr(file, "name", "") or "",
        url=url,
        body=body,
        is_published=is_published,
        available_from=available_from,
        position=_next_position(siblings) if position is None else position,
    )


def update_item(*, actor, item, **changes):
    require_module_manager(actor, item.module)

    kind = changes.get("kind") or item.kind
    _validate_payload(
        kind,
        file=changes.get("file"),
        url=changes.get("url"),
        body=changes.get("body"),
        partial_of=item,
    )

    fields = []
    for field in (
        "title",
        "description",
        "kind",
        "url",
        "body",
        "is_published",
        "position",
    ):
        if field in changes and changes[field] is not None:
            setattr(item, field, changes[field])
            fields.append(field)

    # available_from is nullable on purpose: an explicit null clears the
    # release date, so it cannot use the "None means absent" rule above.
    if "available_from" in changes:
        item.available_from = changes["available_from"]
        fields.append("available_from")

    upload = changes.get("file")
    if upload is not None:
        item.file = upload
        item.original_filename = getattr(upload, "name", "") or ""
        fields += ["file", "original_filename"]

    if fields:
        item.save(update_fields=fields + ["updated_at"])
    return item


def delete_item(*, actor, item):
    require_module_manager(actor, item.module)
    item.delete()


@transaction.atomic
def reorder_items(*, actor, module, item_ids):
    require_module_manager(actor, module)
    items = {str(i.id): i for i in ContentItem.all_objects.filter(module=module)}
    ids = [str(i) for i in item_ids]
    if set(ids) != set(items) or len(ids) != len(items):
        raise ValidationError({"items": "Provide every item in this module exactly once."})
    for index, item_id in enumerate(ids, start=1):
        item = items[item_id]
        item.position = index * 10
        item.save(update_fields=["position", "updated_at"])
    return [items[i] for i in ids]


# --------------------------------------------------------------------------- #
# Read receipts                                                                #
# --------------------------------------------------------------------------- #


def record_view(*, student, item):
    """Record that a student opened an item.

    Only students leave receipts — a lecturer reading their own material is not
    progress. The counter is bumped with an F() expression so two tabs opening
    the same page cannot lose a count to a read-modify-write race.
    """
    if not _is_student(student):
        return None
    if not item_is_visible_to(student, item):
        raise PermissionDenied("This content is not available to you.")

    now = timezone.now()
    view, created = ContentView.all_objects.get_or_create(
        item=item,
        student=student,
        defaults={
            "institution_id": item.institution_id,
            "first_viewed_at": now,
            "last_viewed_at": now,
            "view_count": 1,
        },
    )
    if not created:
        ContentView.all_objects.filter(pk=view.pk).update(
            last_viewed_at=now, view_count=F("view_count") + 1, updated_at=now
        )
        view.refresh_from_db(fields=["last_viewed_at", "view_count"])
    return view


def annotate_viewed(qs, user):
    """Tag each item with whether this student has opened it."""
    if not _is_student(user):
        return qs
    seen = ContentView.all_objects.filter(item=OuterRef("pk"), student=user)
    return qs.annotate(viewed=Exists(seen))
