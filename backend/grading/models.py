from django.db import models

from accounts.models import AcademicBase, Role, User


class Standing(models.TextChoices):
    GOOD = "good", "Good standing"
    PROBATION = "probation", "Probation"
    WITHDRAWAL = "withdrawal", "Withdrawal"


class AcademicStanding(AcademicBase):
    """Persisted output of a department/term standing computation run."""

    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="academic_standings",
        limit_choices_to={"role": Role.STUDENT},
    )
    session = models.ForeignKey(
        "accounts.Session", on_delete=models.PROTECT, related_name="academic_standings"
    )
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="academic_standings"
    )

    term_quality_points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    term_credit_units = models.PositiveSmallIntegerField(default=0)
    gpa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    cumulative_quality_points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    cumulative_credit_units = models.PositiveSmallIntegerField(default=0)
    cgpa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    standing = models.CharField(max_length=12, choices=Standing.choices, blank=True, default="")
    classification = models.CharField(max_length=50, blank=True, default="")
    is_borderline = models.BooleanField(default=False)
    borderline_band = models.CharField(max_length=50, blank=True, default="")
    # [{"code": ..., "title": ...}] — courses still failed at the best attempt.
    outstanding_carryovers = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "grading_academic_standing"
        ordering = ["student__full_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "session", "semester"],
                name="uniq_standing_per_student_term",
            ),
        ]

    def __str__(self):
        return f"{self.student.full_name} — {self.session} {self.semester} (CGPA {self.cgpa})"
