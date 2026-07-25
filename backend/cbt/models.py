"""Computer-Based Testing (CBT) core.

Design notes that matter for exam integrity:

* Correct answers live only on ``Question`` and are never exposed through the
  student-facing serializers (see ``cbt.serializers``). The student sees prompts
  and options; grading happens server-side against fields the client never gets.
* A sitting's assembled paper is frozen onto ``AttemptQuestion`` rows the moment
  the student starts: which questions were drawn, in what order, and the display
  order of each question's options. Reloads replay the same rows, so the paper is
  stable and per-student.
* Timing is server-authoritative: ``ExamAttempt.started_at`` and ``deadline`` are
  set by the server at start and are the only clock that counts.
"""

import uuid

from django.db import models

from accounts.models import AcademicBase, Role, User


class QuestionType(models.TextChoices):
    MCQ = "mcq", "Multiple choice (single answer)"
    MULTI = "multi", "Multiple select"
    TRUE_FALSE = "true_false", "True / false"
    FILL_BLANK = "fill_blank", "Fill in the blank"
    SHORT_ANSWER = "short_answer", "Short answer"


# Types the server can score without a human. Everything else is queued for the
# lecturer. SHORT_ANSWER is the only manual type in the core engine.
OBJECTIVE_TYPES = frozenset(
    {
        QuestionType.MCQ,
        QuestionType.MULTI,
        QuestionType.TRUE_FALSE,
        QuestionType.FILL_BLANK,
    }
)
# Types that carry an ordered list of options whose display order we randomize.
CHOICE_TYPES = frozenset({QuestionType.MCQ, QuestionType.MULTI})


class QuestionBank(AcademicBase):
    """A reusable pool of questions attached to a course. One course can own many
    banks (e.g. per topic); one exam can draw from several banks."""

    course = models.ForeignKey(
        "accounts.Course", on_delete=models.PROTECT, related_name="question_banks"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "cbt_question_bank"
        ordering = ["title", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["course", "title"], name="uniq_bank_title_per_course"),
        ]

    def __str__(self):
        return f"{self.title} — {self.course_id}"


class Question(AcademicBase):
    """A single question in a bank.

    ``options`` holds the choice list for MCQ/MULTI (a JSON list of strings);
    ``correct_answer`` holds the key whose shape depends on ``type``:

    * MCQ         -> int (index into ``options``)
    * MULTI       -> list[int] (indices into ``options``)
    * TRUE_FALSE  -> bool
    * FILL_BLANK  -> list[str] (accepted answers, matched case/space-insensitively)
    * SHORT_ANSWER-> null (graded by a human)

    ``correct_answer`` is NEVER serialized to a student.
    """

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"

    bank = models.ForeignKey(QuestionBank, on_delete=models.PROTECT, related_name="questions")
    type = models.CharField(max_length=16, choices=QuestionType.choices)
    prompt = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_answer = models.JSONField(null=True, blank=True)
    marks = models.DecimalField(max_digits=6, decimal_places=2, default=1)

    requires_manual_grading = models.BooleanField(default=False)
    difficulty = models.CharField(max_length=8, choices=Difficulty.choices, blank=True, default="")
    topic = models.CharField(max_length=120, blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "cbt_question"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_type_display()} ({self.bank_id})"

    @property
    def is_objective(self):
        return self.type in OBJECTIVE_TYPES

    @property
    def is_choice(self):
        return self.type in CHOICE_TYPES


class Exam(AcademicBase):
    """An exam over a course term, created by the assigned lecturer. Draws
    ``num_questions`` from its banks per student at start time."""

    class ExamType(models.TextChoices):
        CA = "ca", "Continuous assessment"
        MAIN = "exam", "Main exam"

    course = models.ForeignKey("accounts.Course", on_delete=models.PROTECT, related_name="exams")
    session = models.ForeignKey("accounts.Session", on_delete=models.PROTECT, related_name="exams")
    semester = models.ForeignKey(
        "accounts.Semester", on_delete=models.PROTECT, related_name="exams"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", limit_choices_to={"role": Role.LECTURER}
    )
    banks = models.ManyToManyField(QuestionBank, related_name="exams")

    title = models.CharField(max_length=200)
    exam_type = models.CharField(max_length=8, choices=ExamType.choices, default=ExamType.MAIN)
    duration_minutes = models.PositiveIntegerField()
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    num_questions = models.PositiveIntegerField()
    shuffle_questions = models.BooleanField(default=True)
    shuffle_options = models.BooleanField(default=True)
    pass_mark = models.DecimalField(
        max_digits=5, decimal_places=2, default=50, help_text="Percentage, 0–100."
    )

    class Meta:
        db_table = "cbt_exam"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.course_id}"


class AttemptStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    SUBMITTED = "submitted", "Submitted (awaiting marking)"
    AUTO_SUBMITTED = "auto_submitted", "Auto-submitted (awaiting marking)"
    GRADED = "graded", "Graded"


class ExamAttempt(AcademicBase):
    """One student's sitting of an exam. There is at most one attempt per
    (exam, student); the assembled paper hangs off it via ``AttemptQuestion``."""

    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="attempts")
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="exam_attempts",
        limit_choices_to={"role": Role.STUDENT},
    )
    # Both set by the server at start; the client clock is never consulted.
    started_at = models.DateTimeField()
    deadline = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=AttemptStatus.choices, default=AttemptStatus.IN_PROGRESS
    )
    # Populated at grading. ``score`` is the objective total (provisional while a
    # short answer awaits marking); ``max_score`` is the drawn paper's full marks.
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    requires_manual_grading = models.BooleanField(default=False)

    class Meta:
        db_table = "cbt_exam_attempt"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["exam", "student"], name="uniq_attempt_per_exam_student"
            ),
        ]

    def __str__(self):
        return f"{self.student_id} · {self.exam_id} ({self.status})"


class AttemptQuestion(AcademicBase):
    """The frozen assembly of one attempt: which question sits at which position,
    and the display order of its options. Persisted so a reload replays exactly
    the same paper. ``option_order[display_index] = original_option_index``."""

    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.PROTECT, related_name="attempt_questions"
    )
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveIntegerField()
    option_order = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "cbt_attempt_question"
        ordering = ["attempt", "position"]
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question"], name="uniq_attempt_question"),
            models.UniqueConstraint(fields=["attempt", "position"], name="uniq_attempt_position"),
        ]

    def __str__(self):
        return f"{self.attempt_id} #{self.position} -> {self.question_id}"


class Answer(AcademicBase):
    """A student's answer to one drawn question. Unique per (attempt, question)
    so auto-save is an idempotent upsert.

    ``response`` is stored in a display-order-independent form:

    * MCQ         -> int (original option index)
    * MULTI       -> list[int] (sorted original option indices)
    * TRUE_FALSE  -> bool
    * FILL_BLANK / SHORT_ANSWER -> str
    """

    attempt = models.ForeignKey(ExamAttempt, on_delete=models.PROTECT, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="+")
    response = models.JSONField(null=True, blank=True)
    # Set at grading; null while unanswered/objective-ungraded or awaiting a human.
    is_correct = models.BooleanField(null=True, blank=True)
    awarded_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    graded_manually = models.BooleanField(default=False)

    class Meta:
        db_table = "cbt_answer"
        ordering = ["attempt", "question"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"], name="uniq_answer_per_question"
            ),
        ]

    def __str__(self):
        return f"{self.attempt_id} · {self.question_id}"


# Proctoring. Honest scope: browser lockdown signals + webcam are a deterrent and
# an evidence trail for human review, not a tamper-proof control. Every signal is
# advisory — a flag never changes a score or an attempt on its own.


class AppendOnlyError(Exception):
    pass


class ProctorEventType(models.TextChoices):
    TAB_SWITCH = "tab_switch", "Tab switch"
    FOCUS_LOSS = "focus_loss", "Window blur / focus loss"
    FOCUS_REGAIN = "focus_regain", "Focus regained"
    FULLSCREEN_EXIT = "fullscreen_exit", "Fullscreen exit"
    COPY_ATTEMPT = "copy_attempt", "Copy attempt"
    PASTE_ATTEMPT = "paste_attempt", "Paste attempt"
    HEARTBEAT = "heartbeat", "Still-present heartbeat"


class ProctorEvent(AcademicBase):
    """Append-only lockdown signal reported during an attempt. Immutable evidence:
    ``client_timestamp`` is when the browser saw it, ``created_at`` when we did."""

    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.PROTECT, related_name="proctor_events"
    )
    type = models.CharField(max_length=20, choices=ProctorEventType.choices)
    client_timestamp = models.DateTimeField()
    detail = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "cbt_proctor_event"
        ordering = ["attempt", "client_timestamp", "created_at"]
        indexes = [models.Index(fields=["attempt", "type"])]

    def __str__(self):
        return f"{self.attempt_id} · {self.type} @ {self.client_timestamp:%Y-%m-%d %H:%M:%S}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Proctoring events are append-only and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Proctoring events are append-only and cannot be deleted.")


def webcam_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"cbt/webcam/{instance.institution_id}/{instance.attempt_id}/{uuid.uuid4().hex}.{ext}"


class WebcamCapture(AcademicBase):
    """A webcam snapshot/clip for an attempt, stored in the configured media
    backend (Supabase S3, private ACL, in prod).

    Data governance: ``expires_at`` is stamped from the institution's
    ``webcam_retention_days``; a later cleanup task purges the media + row once it
    passes (retention is enforced there, not in the request path). Access is scoped
    by ``cbt.proctoring.can_view_webcam`` — staff in scope + a valid auditor token
    only, never other students, never cross-tenant.
    """

    class Kind(models.TextChoices):
        SNAPSHOT = "snapshot", "Snapshot"
        CLIP = "clip", "Short clip"

    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.PROTECT, related_name="webcam_captures"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SNAPSHOT)
    media = models.FileField(upload_to=webcam_upload_path, max_length=255)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    captured_at = models.DateTimeField()
    expires_at = models.DateTimeField(
        help_text="When retention lapses; media is purged by the cleanup task after this."
    )
    # Advisory anomaly signal (client or future analysis); feeds the flag evaluator.
    is_anomalous = models.BooleanField(default=False)
    anomaly_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "cbt_webcam_capture"
        ordering = ["attempt", "captured_at"]

    def __str__(self):
        return f"{self.attempt_id} · {self.kind} @ {self.captured_at:%Y-%m-%d %H:%M:%S}"


class CheatingFlagStatus(models.TextChoices):
    RAISED = "raised", "Raised (awaiting review)"
    DISMISSED = "dismissed", "Dismissed (false positive)"
    ESCALATED = "escalated", "Escalated to HOD"


class CheatingFlag(AcademicBase):
    """An auto-raised integrity concern for one attempt, strictly for human review.
    Raising/dismissing/escalating NEVER changes the attempt's score or status (a
    tested invariant). One flag per attempt."""

    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.PROTECT, related_name="cheating_flags"
    )
    status = models.CharField(
        max_length=12, choices=CheatingFlagStatus.choices, default=CheatingFlagStatus.RAISED
    )
    auto_raised = models.BooleanField(default=True)
    # Which thresholds tripped: a list of {code, detail, count, threshold}.
    reasons = models.JSONField(default=list, blank=True)

    reviewed_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default="")

    escalated_to = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "cbt_cheating_flag"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["attempt"], name="uniq_flag_per_attempt"),
        ]

    def __str__(self):
        return f"flag({self.status}) · {self.attempt_id}"
