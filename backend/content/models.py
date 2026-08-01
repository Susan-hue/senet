"""Course content: modules and the learning material inside them.

A course-term is organised into ordered ``Module`` rows (weeks, topics, units),
each holding ordered ``ContentItem`` rows — an uploaded file, a written lesson
page, a link, or a video. Both levels carry a draft/published flag and items may
additionally hold a release date, so a lecturer can build a course ahead of the
term and let it open on schedule.

``ContentView`` is the read receipt: one row per student per item, so a lecturer
can see who has opened what.
"""

import uuid

from django.db import models

from accounts.models import AcademicBase, Role, User


class Module(AcademicBase):
    course = models.ForeignKey(
        "accounts.Course", on_delete=models.PROTECT, related_name="content_modules"
    )
    session = models.ForeignKey(
        "accounts.Session", on_delete=models.PROTECT, related_name="content_modules"
    )
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="content_modules"
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="content_modules")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    # Lecturer-controlled order within the course-term. Gaps are harmless; only
    # the relative order is meaningful.
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    class Meta:
        db_table = "content_module"
        ordering = ["position", "created_at"]
        indexes = [
            models.Index(fields=["course", "session", "semester", "position"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "session", "semester", "title"],
                name="uniq_module_title_per_course_term",
            ),
        ]

    def __str__(self):
        return f"{self.title} — {self.course.code}"


def content_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"content/{instance.institution_id}/{instance.module_id}/{uuid.uuid4().hex}.{ext}"


class ContentItem(AcademicBase):
    class Kind(models.TextChoices):
        FILE = "file", "File"
        PAGE = "page", "Page"
        LINK = "link", "Link"
        VIDEO = "video", "Video"

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="items")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="content_items")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)
    # When set, a published item still stays hidden from students until this
    # moment. Staff always see it.
    available_from = models.DateTimeField(null=True, blank=True)

    # Exactly which of these carries the payload depends on `kind`; the rules
    # are enforced in services.py, not here, so a data migration or the admin
    # can still write a partial row.
    file = models.FileField(upload_to=content_upload_path, max_length=255, blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(max_length=500, blank=True, default="")
    body = models.TextField(blank=True, default="")

    class Meta:
        db_table = "content_item"
        ordering = ["position", "created_at"]
        indexes = [
            models.Index(fields=["module", "position"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.kind})"

    @property
    def course_id(self):
        return self.module.course_id


class ContentView(AcademicBase):
    """One student's read receipt for one item."""

    item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name="views")
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="content_views",
        limit_choices_to={"role": Role.STUDENT},
    )
    first_viewed_at = models.DateTimeField()
    last_viewed_at = models.DateTimeField()
    view_count = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "content_view"
        ordering = ["-last_viewed_at"]
        constraints = [
            models.UniqueConstraint(fields=["item", "student"], name="uniq_view_per_student_item"),
        ]

    def __str__(self):
        return f"{self.student_id} viewed {self.item_id}"
