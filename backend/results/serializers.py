from decimal import Decimal

from rest_framework import serializers

from accounts.models import Course, Programme, Role, Semester, Session, User
from results.models import CourseResult, ExternalExaminerReport, ResultAmendment, StudentScore
from tenancy.scoping import get_current_institution


class StudentScoreSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_identifier = serializers.CharField(source="student.identifier", read_only=True)

    class Meta:
        model = StudentScore
        fields = [
            "id",
            "student",
            "student_name",
            "student_identifier",
            "ca_score",
            "exam_score",
            "total",
            "grade",
            "is_current",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CourseResultSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    lecturer_name = serializers.CharField(source="lecturer.full_name", read_only=True)

    class Meta:
        model = CourseResult
        fields = [
            "id",
            "institution",
            "course",
            "course_code",
            "course_title",
            "session",
            "semester",
            "lecturer",
            "lecturer_name",
            "status",
            "returned_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CourseResultDetailSerializer(CourseResultSerializer):
    scores = serializers.SerializerMethodField()
    statistics = serializers.SerializerMethodField()

    class Meta(CourseResultSerializer.Meta):
        fields = [*CourseResultSerializer.Meta.fields, "scores", "statistics"]
        read_only_fields = fields

    def get_scores(self, result):
        # The result is already tenant-checked by the view, so query its rows
        # directly rather than through the thread-local-scoped manager.
        rows = StudentScore.all_objects.filter(result=result, is_current=True).select_related(
            "student"
        )
        return StudentScoreSerializer(rows, many=True).data

    def get_statistics(self, result):
        from results.services import compute_anomaly_stats

        return compute_anomaly_stats(result)


class CreateResultSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.none())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["course"].queryset = Course.all_objects.filter(institution=institution)
            self.fields["session"].queryset = Session.all_objects.filter(institution=institution)
            self.fields["semester"].queryset = Semester.all_objects.filter(institution=institution)


class ScoreInputSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    # Omit ca_score to have it aggregated from the student's graded assessment
    # items for this course term.
    ca_score = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
        default=None,
    )
    exam_score = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["student"].queryset = User.objects.filter(
                institution=institution, role=Role.STUDENT
            )


class ReturnReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class BatchRatifySerializer(serializers.Serializer):
    result_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, min_length=1
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ExternalExaminerReportSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source="faculty.name", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)

    class Meta:
        model = ExternalExaminerReport
        fields = [
            "id",
            "institution",
            "faculty",
            "faculty_name",
            "programme",
            "programme_name",
            "session",
            "semester",
            "examiner_name",
            "examiner_institution",
            "audit_date",
            "remarks",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateExternalExaminerReportSerializer(serializers.Serializer):
    programme = serializers.PrimaryKeyRelatedField(queryset=Programme.objects.none())
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.none())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.none())
    examiner_name = serializers.CharField(max_length=200)
    examiner_institution = serializers.CharField(max_length=200)
    audit_date = serializers.DateField()
    remarks = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["programme"].queryset = Programme.all_objects.filter(
                institution=institution
            )
            self.fields["session"].queryset = Session.all_objects.filter(institution=institution)
            self.fields["semester"].queryset = Semester.all_objects.filter(institution=institution)


class ResultAmendmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_identifier = serializers.CharField(source="student.identifier", read_only=True)
    course_code = serializers.CharField(source="result.course.code", read_only=True)

    class Meta:
        model = ResultAmendment
        fields = [
            "id",
            "institution",
            "result",
            "course_code",
            "student",
            "student_name",
            "student_identifier",
            "original_score",
            "proposed_ca_score",
            "proposed_exam_score",
            "proposed_total",
            "proposed_grade",
            "justification",
            "status",
            "returned_reason",
            "raised_by",
            "applied_score",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class RaiseAmendmentSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    proposed_ca_score = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0")
    )
    proposed_exam_score = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0")
    )
    justification = serializers.CharField(allow_blank=False, trim_whitespace=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["student"].queryset = User.objects.filter(
                institution=institution, role=Role.STUDENT
            )
