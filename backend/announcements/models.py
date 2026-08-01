"""Course announcements: what a lecturer tells a whole class at once.

One flat list per course-term, newest first, with pinned rows held at the top.
Announcements are not versioned — an edit rewrites the row — but the author and
both timestamps are kept so a class can see when something changed.
"""

from django.db import models

from accounts.models import AcademicBase, User


class Announcement(AcademicBase):
    course = models.ForeignKey(
        "accounts.Course", on_delete=models.PROTECT, related_name="announcements"
    )
    session = models.ForeignKey(
        "accounts.Session", on_delete=models.PROTECT, related_name="announcements"
    )
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="announcements"
    )
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="announcements")

    title = models.CharField(max_length=200)
    body = models.TextField()
    is_pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "announcements_announcement"
        # Pinned first, then newest. Matches what the class should read.
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=["course", "session", "semester", "-is_pinned", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.title} — {self.course.code}"
