from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from accounts.models import Course, Semester, Session
from cbt.models import (
    Answer,
    AttemptStatus,
    CheatingFlag,
    Exam,
    ExamAttempt,
    ProctorEvent,
    ProctorEventType,
    Question,
    QuestionBank,
    QuestionType,
    WebcamCapture,
)
from tenancy.scoping import get_current_institution


class QuestionBankSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    question_count = serializers.IntegerField(source="questions.count", read_only=True)

    class Meta:
        model = QuestionBank
        fields = [
            "id",
            "course",
            "course_code",
            "title",
            "description",
            "created_by",
            "question_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateQuestionBankSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["course"].queryset = Course.all_objects.filter(institution=institution)


class QuestionSerializer(serializers.ModelSerializer):
    """Full question, INCLUDING the correct answer. For question managers only —
    never returned on a student-facing endpoint."""

    class Meta:
        model = Question
        fields = [
            "id",
            "bank",
            "type",
            "prompt",
            "options",
            "correct_answer",
            "marks",
            "requires_manual_grading",
            "difficulty",
            "topic",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateQuestionSerializer(serializers.Serializer):
    bank = serializers.PrimaryKeyRelatedField(queryset=QuestionBank.objects.none())
    type = serializers.ChoiceField(choices=QuestionType.choices)
    prompt = serializers.CharField()
    options = serializers.JSONField(required=False, default=list)
    correct_answer = serializers.JSONField(required=False, allow_null=True, default=None)
    marks = serializers.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1"))
    difficulty = serializers.CharField(required=False, allow_blank=True, default="")
    topic = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["bank"].queryset = QuestionBank.all_objects.filter(institution=institution)


class ExamSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    bank_ids = serializers.PrimaryKeyRelatedField(source="banks", many=True, read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id",
            "course",
            "course_code",
            "course_title",
            "session",
            "semester",
            "created_by",
            "bank_ids",
            "title",
            "exam_type",
            "duration_minutes",
            "opens_at",
            "closes_at",
            "num_questions",
            "shuffle_questions",
            "shuffle_options",
            "pass_mark",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateExamSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.none())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.none())
    banks = serializers.PrimaryKeyRelatedField(queryset=QuestionBank.objects.none(), many=True)
    title = serializers.CharField(max_length=200)
    exam_type = serializers.ChoiceField(choices=Exam.ExamType.choices, default=Exam.ExamType.MAIN)
    duration_minutes = serializers.IntegerField(min_value=1)
    opens_at = serializers.DateTimeField()
    closes_at = serializers.DateTimeField()
    num_questions = serializers.IntegerField(min_value=1)
    shuffle_questions = serializers.BooleanField(default=True)
    shuffle_options = serializers.BooleanField(default=True)
    pass_mark = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("50"), min_value=Decimal("0")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        if institution is not None:
            self.fields["course"].queryset = Course.all_objects.filter(institution=institution)
            self.fields["session"].queryset = Session.all_objects.filter(institution=institution)
            self.fields["semester"].queryset = Semester.all_objects.filter(institution=institution)
            self.fields["banks"].child_relation.queryset = QuestionBank.all_objects.filter(
                institution=institution
            )


class ExamAttemptSerializer(serializers.ModelSerializer):
    passed = serializers.SerializerMethodField()
    # Authoritative countdown, computed server-side from the stored deadline so a
    # reconnecting client always resumes with the correct time remaining and can
    # never influence it.
    time_remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "exam",
            "student",
            "status",
            "started_at",
            "deadline",
            "time_remaining_seconds",
            "submitted_at",
            "score",
            "max_score",
            "requires_manual_grading",
            "passed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_time_remaining_seconds(self, attempt):
        if attempt.status != AttemptStatus.IN_PROGRESS:
            return 0
        remaining = (attempt.deadline - timezone.now()).total_seconds()
        return max(0, int(remaining))

    def get_passed(self, attempt):
        if attempt.status != AttemptStatus.GRADED or attempt.score is None or not attempt.max_score:
            return None
        percentage = (attempt.score / attempt.max_score) * 100
        return percentage >= attempt.exam.pass_mark


class AttemptQuestionSerializer(serializers.Serializer):
    """The student-safe question payload.

    Built by hand from ``AttemptQuestion`` + ``Question`` so that ONLY the prompt,
    marks, and options (in this attempt's display order) leave the server. There is
    no path here to ``Question.correct_answer`` — answer leakage is prevented by
    construction, not by remembering to exclude a field.
    """

    question = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    prompt = serializers.SerializerMethodField()
    marks = serializers.SerializerMethodField()
    position = serializers.IntegerField()
    options = serializers.SerializerMethodField()

    def get_question(self, aq):
        return str(aq.question_id)

    def get_type(self, aq):
        return aq.question.type

    def get_prompt(self, aq):
        return aq.question.prompt

    def get_marks(self, aq):
        return str(aq.question.marks)

    def get_options(self, aq):
        options = aq.question.options or []
        # Present options in this attempt's display order; the client refers to
        # them by position in this list. Non-choice questions have no options.
        return [options[i] for i in aq.option_order if 0 <= i < len(options)]


class AnswerEchoSerializer(serializers.ModelSerializer):
    """What the student gets back for a saved answer / on resume. Deliberately
    excludes ``is_correct`` and ``awarded_marks`` so correctness never leaks while
    the exam is live."""

    class Meta:
        model = Answer
        fields = ["question", "response", "updated_at"]
        read_only_fields = fields


class SaveAnswerSerializer(serializers.Serializer):
    question = serializers.UUIDField()
    # Shape depends on the question type; validated server-side against the
    # attempt's frozen question. May be null to clear an answer.
    response = serializers.JSONField(required=True, allow_null=True)


class SaveAnswersBatchSerializer(serializers.Serializer):
    """A buffered set of answers synced in one request on reconnect."""

    answers = SaveAnswerSerializer(many=True, allow_empty=False)


# --------------------------------------------------------------------------- #
# Proctoring                                                                  #
# --------------------------------------------------------------------------- #


class RecordEventSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=ProctorEventType.choices)
    client_timestamp = serializers.DateTimeField()
    detail = serializers.JSONField(required=False, allow_null=True, default=None)


class ProctorEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProctorEvent
        fields = ["id", "attempt", "type", "client_timestamp", "detail", "created_at"]
        read_only_fields = fields


class WebcamUploadSerializer(serializers.Serializer):
    media = serializers.FileField()
    kind = serializers.ChoiceField(
        choices=WebcamCapture.Kind.choices, default=WebcamCapture.Kind.SNAPSHOT
    )
    captured_at = serializers.DateTimeField()
    is_anomalous = serializers.BooleanField(required=False, default=False)
    anomaly_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=200
    )

    def validate_media(self, upload):
        name = (upload.name or "").lower()
        if not name.endswith(settings.CBT_WEBCAM_ALLOWED_EXTENSIONS):
            allowed = ", ".join(settings.CBT_WEBCAM_ALLOWED_EXTENSIONS)
            raise serializers.ValidationError(f"Only {allowed} files are accepted.")
        if upload.size > settings.CBT_WEBCAM_MAX_FILE_BYTES:
            limit_mb = settings.CBT_WEBCAM_MAX_FILE_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"File exceeds the maximum size of {limit_mb} MB.")
        return upload


class WebcamCaptureSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = WebcamCapture
        fields = [
            "id",
            "attempt",
            "kind",
            "media_url",
            "original_filename",
            "captured_at",
            "expires_at",
            "is_anomalous",
            "anomaly_reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_media_url(self, capture):
        try:
            return capture.media.url
        except (ValueError, NotImplementedError):
            return None


class CheatingFlagSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="attempt.student.full_name", read_only=True)
    exam_title = serializers.CharField(source="attempt.exam.title", read_only=True)

    class Meta:
        model = CheatingFlag
        fields = [
            "id",
            "attempt",
            "student_name",
            "exam_title",
            "status",
            "auto_raised",
            "reasons",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "escalated_to",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReviewFlagSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")
