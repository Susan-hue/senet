import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class TimeStampedUUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Default academic ladder for universities. Colleges of education and
# polytechnics replace this with the CONPCASS ladder on their own record.
UNIVERSITY_LECTURER_RANKS = [
    "Graduate Assistant",
    "Assistant Lecturer",
    "Lecturer II",
    "Lecturer I",
    "Senior Lecturer",
    "Associate Professor",
    "Professor",
]


def default_lecturer_ranks():
    return list(UNIVERSITY_LECTURER_RANKS)


# Standard Nigerian university 5-point scale. Institutions on other scales
# (4-point, 7-point, different boundaries) replace this on their own record.
def default_grade_scale():
    return [
        {"grade": "A", "min_score": 70, "points": 5},
        {"grade": "B", "min_score": 60, "points": 4},
        {"grade": "C", "min_score": 50, "points": 3},
        {"grade": "D", "min_score": 45, "points": 2},
        {"grade": "E", "min_score": 40, "points": 1},
        {"grade": "F", "min_score": 0, "points": 0},
    ]


# Standard Nigerian degree classification bands; CGPA below the lowest band
# is a fail. min_cgpa values are strings to keep Decimal precision in JSON.
def default_classification_bands():
    return [
        {"name": "First Class", "min_cgpa": "4.50"},
        {"name": "Second Class Upper", "min_cgpa": "3.50"},
        {"name": "Second Class Lower", "min_cgpa": "2.40"},
        {"name": "Third Class", "min_cgpa": "1.50"},
    ]


class Institution(TimeStampedUUIDModel):
    GRADING_SCALE_CHOICES = [
        ("5_POINT", "5-Point Scale"),
        ("7_POINT", "7-Point Scale"),
        ("4_POINT", "4-Point Scale"),
    ]

    CARRYOVER_CGPA_METHOD_CHOICES = [
        ("ALL_ATTEMPTS", "All attempts count in CGPA"),
        ("HIGHEST_ONLY", "Only the best attempt counts in CGPA"),
    ]

    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=30, unique=True)
    is_active = models.BooleanField(default=True)

    grading_scale_type = models.CharField(
        max_length=20, choices=GRADING_SCALE_CHOICES, default="5_POINT"
    )
    default_ca_weight = models.PositiveSmallIntegerField(default=40)
    default_exam_weight = models.PositiveSmallIntegerField(default=60)
    pass_mark = models.DecimalField(max_digits=5, decimal_places=2, default=40)
    probation_cgpa_threshold = models.DecimalField(max_digits=4, decimal_places=2, default=1.50)

    # Min/max credit units a student may register per semester (NUC-mandated
    # defaults; configurable per university).
    min_credit_units_per_semester = models.PositiveSmallIntegerField(default=15)
    max_credit_units_per_semester = models.PositiveSmallIntegerField(default=24)

    # How retaken (carryover) courses count toward CGPA: ALL_ATTEMPTS keeps every
    # attempt in the CGPA denominator; HIGHEST_ONLY counts only the best attempt
    # (the failed attempt stays on the transcript but is excluded from the denominator).
    carryover_cgpa_method = models.CharField(
        max_length=20, choices=CARRYOVER_CGPA_METHOD_CHOICES, default="ALL_ATTEMPTS"
    )
    # Score below which a course is treated as a carryover/fail (varies 40-45%).
    carryover_pass_mark = models.DecimalField(max_digits=5, decimal_places=2, default=40)

    # Letter-grade boundaries and grade points used by the GPA engine.
    grade_scale = models.JSONField(default=default_grade_scale, blank=True)
    # Degree classification bands (highest first) used for final classification.
    classification_bands = models.JSONField(default=default_classification_bands, blank=True)
    # CGPA below this is flagged for withdrawal (probation uses
    # probation_cgpa_threshold above).
    withdrawal_cgpa_threshold = models.DecimalField(max_digits=4, decimal_places=2, default=1.00)
    # A CGPA within this margin below a classification boundary is flagged for
    # Senate review — a flag only, never an automatic upgrade.
    senate_review_margin = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.05")
    )
    # Which result-pipeline state feeds the GPA engine; official grades come
    # from senate-ratified results unless an institution configures otherwise.
    gpa_source_status = models.CharField(max_length=20, default="ratified_by_senate")

    # Ordered set of rank titles a lecturer at this institution may hold.
    lecturer_ranks = models.JSONField(default=default_lecturer_ranks, blank=True)

    enforce_fees_for_results = models.BooleanField(default=False)
    has_external_affiliation = models.BooleanField(default=False)
    has_teaching_practice = models.BooleanField(default=False)
    has_sponsor_portal = models.BooleanField(default=False)

    primary_color = models.CharField(max_length=7, blank=True, default="")
    logo_url = models.URLField(blank=True, default="")

    class Meta:
        db_table = "tenancy_institution"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.default_ca_weight + self.default_exam_weight != 100:
            raise ValidationError("CA weight and Exam weight must sum to 100.")
        if self.min_credit_units_per_semester > self.max_credit_units_per_semester:
            raise ValidationError("Minimum credit units cannot exceed the maximum.")
        ranks = self.lecturer_ranks
        if not isinstance(ranks, list) or not all(isinstance(r, str) and r.strip() for r in ranks):
            raise ValidationError("Lecturer ranks must be a list of non-empty names.")
        if len(set(ranks)) != len(ranks):
            raise ValidationError("Lecturer ranks must not contain duplicates.")

        scale = self.grade_scale
        if (
            not isinstance(scale, list)
            or not scale
            or not all(
                isinstance(row, dict) and {"grade", "min_score", "points"} <= set(row)
                for row in scale
            )
        ):
            raise ValidationError(
                "Grade scale must be a non-empty list of {grade, min_score, points} rows."
            )
        grades = [row["grade"] for row in scale]
        if len(set(grades)) != len(grades):
            raise ValidationError("Grade scale letters must be unique.")

        bands = self.classification_bands
        if not isinstance(bands, list) or not all(
            isinstance(row, dict) and {"name", "min_cgpa"} <= set(row) for row in bands
        ):
            raise ValidationError("Classification bands must be a list of {name, min_cgpa} rows.")
