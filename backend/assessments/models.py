import uuid

from django.db import models

from accounts.models import AcademicBase, Role, User


class AssessmentItem(AcademicBase):
    """A weighted CA component (assignment, test, project) for a course term."""

    class Kind(models.TextChoices):
        ASSIGNMENT = "assignment", "Assignment"
        TEST = "test", "Test"
        PROJECT = "project", "Project"

    course = models.ForeignKey(
        "accounts.Course", on_delete=models.PROTECT, related_name="assessment_items"
    )
    session = models.ForeignKey(
        "accounts.Session", on_delete=models.PROTECT, related_name="assessment_items"
    )
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="assessment_items"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="assessment_items",
        limit_choices_to={"role": Role.LECTURER},
    )
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    # Raw marking scale of the item (e.g. marked out of 20).
    max_score = models.DecimalField(max_digits=6, decimal_places=2)
    # The item's share of the course's CA portion, in percentage points of the
    # final course total (all items together may not exceed the CA weight).
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    due_date = models.DateTimeField()

    class Meta:
        db_table = "assessments_item"
        ordering = ["due_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "session", "semester", "title"],
                name="uniq_item_title_per_course_term",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.kind}) — {self.course.code}"


def submission_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return (
        f"assessments/{instance.institution_id}/{instance.item_id}/"
        f"{instance.student_id}/{uuid.uuid4().hex}.{ext}"
    )


class Submission(AcademicBase):
    item = models.ForeignKey(AssessmentItem, on_delete=models.PROTECT, related_name="submissions")
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="assessment_submissions",
        limit_choices_to={"role": Role.STUDENT},
    )
    file = models.FileField(upload_to=submission_upload_path, max_length=255)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    submitted_at = models.DateTimeField()
    is_late = models.BooleanField(default=False)

    class Meta:
        db_table = "assessments_submission"
        ordering = ["submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "student"], name="uniq_submission_per_student_item"
            ),
        ]

    def __str__(self):
        return f"{self.student.full_name} → {self.item.title}"


class AssessmentGrade(AcademicBase):
    item = models.ForeignKey(AssessmentItem, on_delete=models.PROTECT, related_name="grades")
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="assessment_grades",
        limit_choices_to={"role": Role.STUDENT},
    )
    # Optional: a grade can attach to a file submission, or stand alone for
    # items with no upload (e.g. an in-class test).
    submission = models.OneToOneField(
        Submission, on_delete=models.PROTECT, related_name="grade", null=True, blank=True
    )
    score = models.DecimalField(max_digits=6, decimal_places=2)
    feedback = models.TextField(blank=True, default="")
    graded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"role": Role.LECTURER},
    )
    is_released = models.BooleanField(default=False)

    class Meta:
        db_table = "assessments_grade"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["item", "student"], name="uniq_grade_per_student_item"),
        ]

    def __str__(self):
        return f"{self.student.full_name} — {self.score}/{self.item.max_score}"
