from decimal import Decimal

from rest_framework import serializers

from accounts.models import Course, Role, Semester, Session, User
from results.models import CourseResult, StudentScore
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

    class Meta(CourseResultSerializer.Meta):
        fields = [*CourseResultSerializer.Meta.fields, "scores"]
        read_only_fields = fields

    def get_scores(self, result):
        # The result is already tenant-checked by the view, so query its rows
        # directly rather than through the thread-local-scoped manager.
        rows = StudentScore.all_objects.filter(result=result, is_current=True).select_related(
            "student"
        )
        return StudentScoreSerializer(rows, many=True).data


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
    ca_score = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"))
    exam_score = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["student"].queryset = User.objects.filter(
                institution=institution, role=Role.STUDENT
            )
