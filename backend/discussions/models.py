"""Course discussion boards.

The board *is* the course-term — a thread hangs directly off course + session +
semester, so there is no empty container model to manage. Replies are flat
rather than nested: a class forum is read top to bottom, and a flat list keeps
ordering, pagination and moderation honest at any depth of conversation.

Moderation removes rather than deletes. A removed thread or reply stops being
readable but the row survives with who removed it and when, so a dispute about
what was said and who took it down has an answer.
"""

from django.db import models

from accounts.models import AcademicBase, User


class RemovableMixin(models.Model):
    is_removed = models.BooleanField(default=False)
    removed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class Thread(AcademicBase, RemovableMixin):
    course = models.ForeignKey(
        "accounts.Course", on_delete=models.PROTECT, related_name="discussion_threads"
    )
    session = models.ForeignKey(
        "accounts.Session", on_delete=models.PROTECT, related_name="discussion_threads"
    )
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="discussion_threads"
    )
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="discussion_threads")

    title = models.CharField(max_length=200)
    body = models.TextField()
    is_pinned = models.BooleanField(default=False)
    # A locked thread stays readable; only teaching staff may still post to it.
    is_locked = models.BooleanField(default=False)
    last_activity_at = models.DateTimeField()

    class Meta:
        db_table = "discussions_thread"
        # Pinned first, then whatever was last talked about.
        ordering = ["-is_pinned", "-last_activity_at"]
        indexes = [
            models.Index(
                fields=["course", "session", "semester", "-is_pinned", "-last_activity_at"]
            ),
        ]

    def __str__(self):
        return f"{self.title} — {self.course.code}"


class Reply(AcademicBase, RemovableMixin):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="discussion_replies")
    body = models.TextField()

    class Meta:
        db_table = "discussions_reply"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["thread", "created_at"]),
        ]

    def __str__(self):
        return f"Reply by {self.author_id} on {self.thread_id}"
