from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from accounts.models import Course, Role, Semester, Session, User
from assessments.models import AssessmentGrade, AssessmentItem, Submission
from tenancy.scoping import get_current_institution


class AssessmentItemSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = AssessmentItem
        fields = [
            "id",
            "institution",
            "course",
            "course_code",
            "course_title",
            "session",
            "semester",
            "created_by",
            "title",
            "kind",
            "max_score",
            "weight",
            "due_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateItemSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.none())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.none())
    title = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=AssessmentItem.Kind.choices)
    max_score = serializers.DecimalField(max_digits=6, decimal_places=2)
    weight = serializers.DecimalField(max_digits=5, decimal_places=2)
    due_date = serializers.DateTimeField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["course"].queryset = Course.all_objects.filter(institution=institution)
            self.fields["session"].queryset = Session.all_objects.filter(institution=institution)
            self.fields["semester"].queryset = Semester.all_objects.filter(institution=institution)


class SubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_identifier = serializers.CharField(source="student.identifier", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = [
            "id",
            "item",
            "student",
            "student_name",
            "student_identifier",
            "file_url",
            "original_filename",
            "submitted_at",
            "is_late",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_file_url(self, submission):
        try:
            return submission.file.url
        except (ValueError, NotImplementedError):
            return None


class SubmissionUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, upload):
        name = (upload.name or "").lower()
        if not name.endswith(settings.ASSESSMENT_ALLOWED_EXTENSIONS):
            allowed = ", ".join(settings.ASSESSMENT_ALLOWED_EXTENSIONS)
            raise serializers.ValidationError(f"Only {allowed} files are accepted.")
        if upload.size > settings.ASSESSMENT_MAX_FILE_BYTES:
            limit_mb = settings.ASSESSMENT_MAX_FILE_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"File exceeds the maximum size of {limit_mb} MB.")
        return upload


class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    item_title = serializers.CharField(source="item.title", read_only=True)
    item_max_score = serializers.DecimalField(
        source="item.max_score", max_digits=6, decimal_places=2, read_only=True
    )
    item_weight = serializers.DecimalField(
        source="item.weight", max_digits=5, decimal_places=2, read_only=True
    )

    class Meta:
        model = AssessmentGrade
        fields = [
            "id",
            "item",
            "item_title",
            "item_max_score",
            "item_weight",
            "student",
            "student_name",
            "submission",
            "score",
            "feedback",
            "graded_by",
            "is_released",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class GradeInputSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    score = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0"))
    feedback = serializers.CharField(required=False, allow_blank=True, default="")
    is_released = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["student"].queryset = User.objects.filter(
                institution=institution, role=Role.STUDENT
            )
