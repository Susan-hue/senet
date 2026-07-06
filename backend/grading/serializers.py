from rest_framework import serializers

from accounts.models import Department, Semester, Session
from grading.models import AcademicStanding
from tenancy.scoping import get_current_institution


class ComputeRequestSerializer(serializers.Serializer):
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.none())
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.none())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["department"].queryset = Department.all_objects.filter(
                institution=institution
            )
            self.fields["session"].queryset = Session.all_objects.filter(institution=institution)
            self.fields["semester"].queryset = Semester.all_objects.filter(institution=institution)

    def validate(self, attrs):
        if attrs["semester"].session_id != attrs["session"].id:
            raise serializers.ValidationError(
                {"semester": "Semester does not belong to the selected session."}
            )
        return attrs


class AcademicStandingSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_identifier = serializers.CharField(source="student.identifier", read_only=True)

    class Meta:
        model = AcademicStanding
        fields = [
            "id",
            "student",
            "student_name",
            "student_identifier",
            "session",
            "semester",
            "term_quality_points",
            "term_credit_units",
            "gpa",
            "cumulative_quality_points",
            "cumulative_credit_units",
            "cgpa",
            "standing",
            "classification",
            "is_borderline",
            "borderline_band",
            "outstanding_carryovers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
