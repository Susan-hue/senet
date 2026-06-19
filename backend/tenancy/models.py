import uuid

from django.core.exceptions import ValidationError
from django.db import models


class TimeStampedUUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Institution(TimeStampedUUIDModel):
    GRADING_SCALE_CHOICES = [
        ("5_POINT", "5-Point Scale"),
        ("7_POINT", "7-Point Scale"),
        ("4_POINT", "4-Point Scale"),
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
