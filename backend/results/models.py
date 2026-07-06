from django.db import models

from accounts.models import AcademicBase, Role, User


class ImmutableRecordError(Exception):
    """Raised when code attempts to rewrite append-only results history."""


class ResultStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED_TO_HOD = "submitted_to_hod", "Submitted to HOD"
    APPROVED_BY_HOD = "approved_by_hod", "Approved by HOD"
    APPROVED_BY_DEAN = "approved_by_dean", "Approved by Dean"
    RATIFIED_BY_SENATE = "ratified_by_senate", "Ratified by Senate"
    RETURNED = "returned", "Returned"


# States in which the owning lecturer may still change score rows in place.
LECTURER_EDITABLE_STATUSES = (ResultStatus.DRAFT, ResultStatus.RETURNED)


class CourseResult(AcademicBase):
    """A lecturer's result sheet for one course in one session + semester."""

    course = models.ForeignKey("accounts.Course", on_delete=models.PROTECT, related_name="results")
    session = models.ForeignKey(
        "accounts.Session", on_delete=models.PROTECT, related_name="results"
    )
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="results"
    )
    lecturer = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="course_results",
        limit_choices_to={"role": Role.LECTURER},
    )
    status = models.CharField(
        max_length=20, choices=ResultStatus.choices, default=ResultStatus.DRAFT
    )
    returned_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "results_course_result"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "session", "semester"], name="uniq_result_per_course_term"
            ),
        ]

    def __str__(self):
        return f"{self.course.code} — {self.session.name} {self.semester.name} ({self.status})"

    def save(self, *args, **kwargs):
        # Append-only backstop: once ratified, the row itself never changes.
        # Post-ratification corrections arrive as new superseding score rows.
        if not self._state.adding:
            stored = CourseResult.all_objects.values_list("status", flat=True).get(pk=self.pk)
            if stored == ResultStatus.RATIFIED_BY_SENATE:
                raise ImmutableRecordError(
                    "A ratified result is immutable; changes require an amendment."
                )
        super().save(*args, **kwargs)


class StudentScore(AcademicBase):
    result = models.ForeignKey(CourseResult, on_delete=models.PROTECT, related_name="scores")
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="result_scores",
        limit_choices_to={"role": Role.STUDENT},
    )
    ca_score = models.DecimalField(max_digits=5, decimal_places=2)
    exam_score = models.DecimalField(max_digits=5, decimal_places=2)
    total = models.DecimalField(max_digits=5, decimal_places=2)
    grade = models.CharField(max_length=2)
    # Amendment support (Sprint 4): a correcting row points at the row it
    # replaces; the replaced row keeps its values forever and only loses
    # currency via the is_current flag.
    supersedes = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="superseded_by",
        null=True,
        blank=True,
    )
    is_current = models.BooleanField(default=True)

    class Meta:
        db_table = "results_student_score"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["result", "student"],
                condition=models.Q(is_current=True),
                name="uniq_current_score_per_student",
            ),
        ]

    def __str__(self):
        return f"{self.student.full_name} — {self.total} ({self.grade})"

    def _stored_result_status(self):
        return CourseResult.all_objects.values_list("status", flat=True).get(pk=self.result_id)

    def save(self, *args, **kwargs):
        # In-place edits are only legal while the lecturer still owns the
        # sheet. The single exception is flipping is_current, which is how a
        # superseding amendment retires a row without losing its values.
        if not self._state.adding:
            update_fields = kwargs.get("update_fields")
            currency_flip = update_fields is not None and set(update_fields) <= {
                "is_current",
                "updated_at",
            }
            if not currency_flip and self._stored_result_status() not in (
                LECTURER_EDITABLE_STATUSES
            ):
                raise ImmutableRecordError(
                    "Score rows cannot be edited in place after submission; use a superseding row."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._stored_result_status() not in LECTURER_EDITABLE_STATUSES:
            raise ImmutableRecordError("Score rows cannot be deleted after submission.")
        return super().delete(*args, **kwargs)


class AuditAction(models.TextChoices):
    RESULT_CREATED = "result_created", "Result created"
    SCORE_ADDED = "score_added", "Score added"
    SCORE_CHANGED = "score_changed", "Score changed"
    SCORE_SUPERSEDED = "score_superseded", "Score superseded"
    STATUS_CHANGED = "status_changed", "Status changed"


class ResultAuditLog(AcademicBase):
    """Append-only record of every score change and state transition."""

    result = models.ForeignKey(CourseResult, on_delete=models.PROTECT, related_name="audit_entries")
    score = models.ForeignKey(
        StudentScore,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=20, choices=AuditAction.choices)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "results_audit_log"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.action} by {self.actor_id} on {self.result_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Audit log entries are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Audit log entries cannot be deleted.")
