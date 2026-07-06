from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Enrolment,
    Faculty,
    ImportJob,
    Level,
    Programme,
    Role,
    Semester,
    Session,
    User,
)
from tenancy.scoping import get_current_institution


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "full_name", "password", "role"]
        extra_kwargs = {"role": {"required": False}}

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        validated_data.setdefault("role", Role.STUDENT)
        return User.objects.create_user(password=password, is_verified=False, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class MeSerializer(serializers.ModelSerializer):
    institution_id = serializers.PrimaryKeyRelatedField(source="institution", read_only=True)
    institution_name = serializers.CharField(
        source="institution.name", read_only=True, default=None
    )
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    faculty_name = serializers.CharField(source="faculty.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "institution_id",
            "institution_name",
            "department",
            "department_name",
            "faculty",
            "faculty_name",
            "current_level",
            "identifier",
            "is_verified",
        ]
        read_only_fields = fields


class UserAdminSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    rank = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "department",
            "department_name",
            "current_level",
            "identifier",
            "rank",
            "is_active",
            "is_verified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_verified", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["department"].queryset = Department.all_objects.filter(
                institution=institution
            )
        else:
            self.fields["department"].queryset = Department.objects.none()

    def validate_rank(self, value):
        return (value or "").strip()

    def validate(self, attrs):
        role = attrs.get("role", getattr(self.instance, "role", None))
        if role != Role.LECTURER:
            # A role change away from lecturer drops any stored rank.
            if attrs.get("rank"):
                raise serializers.ValidationError(
                    {"rank": "Only lecturers can have an academic rank."}
                )
            if "rank" in attrs or "role" in attrs:
                attrs["rank"] = ""
            return attrs

        rank = attrs.get("rank", getattr(self.instance, "rank", ""))
        if rank:
            institution = get_current_institution()
            allowed = institution.lecturer_ranks if institution is not None else []
            if rank not in allowed:
                raise serializers.ValidationError(
                    {"rank": "This rank is not in your institution's configured ladder."}
                )
        return attrs

    def create(self, validated_data):
        user = User(**validated_data)
        user.set_unusable_password()
        user.is_verified = False
        user.save()
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        validate_password(value)
        return value


# --------------------------------------------------------------------------- #
# Academic structure                                                          #
# --------------------------------------------------------------------------- #

READ_ONLY_AUDIT = ["id", "created_at", "updated_at"]


def _unique_code(model, code, instance):
    """Reject a duplicate code within the current (auto-scoped) institution."""
    qs = model.objects.filter(code=code)
    if instance is not None:
        qs = qs.exclude(pk=instance.pk)
    if qs.exists():
        raise serializers.ValidationError("A record with this code already exists.")


class FacultySerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Faculty
        fields = ["id", "institution", "name", "code", "created_at", "updated_at"]
        read_only_fields = READ_ONLY_AUDIT

    def validate_code(self, value):
        _unique_code(Faculty, value, self.instance)
        return value


class DepartmentSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Department
        fields = ["id", "institution", "faculty", "name", "code", "created_at", "updated_at"]
        read_only_fields = READ_ONLY_AUDIT

    def validate_code(self, value):
        _unique_code(Department, value, self.instance)
        return value


class ProgrammeSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Programme
        fields = [
            "id",
            "institution",
            "department",
            "name",
            "code",
            "degree_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = READ_ONLY_AUDIT

    def validate_code(self, value):
        _unique_code(Programme, value, self.instance)
        return value


class SessionSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Session
        fields = [
            "id",
            "institution",
            "name",
            "start_date",
            "end_date",
            "is_current",
            "created_at",
            "updated_at",
        ]
        read_only_fields = READ_ONLY_AUDIT

    def validate_name(self, value):
        qs = Session.objects.filter(name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A session with this name already exists.")
        return value

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_date": "End date must be after start date."})
        return attrs


class SemesterSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Semester
        fields = [
            "id",
            "institution",
            "session",
            "name",
            "start_date",
            "end_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = READ_ONLY_AUDIT

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_date": "End date must be after start date."})

        session = attrs.get("session", getattr(self.instance, "session", None))
        name = attrs.get("name", getattr(self.instance, "name", None))
        qs = Semester.objects.filter(session=session, name=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"name": "This session already has a semester with that name."}
            )
        return attrs


class CourseSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)
    level = serializers.ChoiceField(choices=Level.choices)
    effective_ca_weight = serializers.IntegerField(read_only=True)
    effective_exam_weight = serializers.IntegerField(read_only=True)

    class Meta:
        model = Course
        fields = [
            "id",
            "institution",
            "department",
            "code",
            "title",
            "credit_units",
            "level",
            "ca_weight",
            "exam_weight",
            "effective_ca_weight",
            "effective_exam_weight",
            "created_at",
            "updated_at",
        ]
        read_only_fields = READ_ONLY_AUDIT

    def validate_code(self, value):
        _unique_code(Course, value, self.instance)
        return value

    def validate(self, attrs):
        ca = attrs.get("ca_weight", getattr(self.instance, "ca_weight", None))
        exam = attrs.get("exam_weight", getattr(self.instance, "exam_weight", None))
        if (ca is None) != (exam is None):
            raise serializers.ValidationError("Provide both CA and exam weight, or neither.")
        if ca is not None and ca + exam != 100:
            raise serializers.ValidationError({"ca_weight": "CA and exam weight must sum to 100."})
        return attrs


class EnrolmentSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Enrolment
        fields = [
            "id",
            "institution",
            "student",
            "course",
            "session",
            "semester",
            "created_at",
            "updated_at",
        ]
        read_only_fields = READ_ONLY_AUDIT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["student"].queryset = User.objects.filter(
                institution=institution, role=Role.STUDENT
            )
        else:
            self.fields["student"].queryset = User.objects.none()


class CourseAssignmentSerializer(serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(read_only=True)
    # Denormalised display fields so list screens don't have to fetch the
    # whole user/course directories just to label a row.
    lecturer_name = serializers.CharField(source="lecturer.full_name", read_only=True)
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = CourseAssignment
        fields = [
            "id",
            "institution",
            "lecturer",
            "lecturer_name",
            "course",
            "course_code",
            "course_title",
            "session",
            "semester",
            "created_at",
            "updated_at",
        ]
        read_only_fields = READ_ONLY_AUDIT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["lecturer"].queryset = User.objects.filter(
                institution=institution, role=Role.LECTURER
            )
        else:
            self.fields["lecturer"].queryset = User.objects.none()


class ImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, uploaded):
        if not (uploaded.name or "").lower().endswith((".csv", ".xlsx")):
            raise serializers.ValidationError("Only .csv and .xlsx files are supported.")
        if uploaded.size > settings.IMPORT_MAX_FILE_BYTES:
            limit_mb = settings.IMPORT_MAX_FILE_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"File exceeds the maximum size of {limit_mb} MB.")
        return uploaded


class ImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportJob
        fields = [
            "id",
            "kind",
            "status",
            "filename",
            "total_rows",
            "created_count",
            "skipped_count",
            "errors",
            "message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
