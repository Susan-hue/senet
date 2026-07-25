from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.views import APIView

from accounts.pagination import DirectoryPagination
from accounts.responses import error_response, success_response
from cbt import services
from cbt.models import Exam, ExamAttempt, Question, QuestionBank
from cbt.permissions import IsCbtParticipant, IsExamManager, IsStudent
from cbt.serializers import (
    AnswerEchoSerializer,
    AttemptQuestionSerializer,
    CreateExamSerializer,
    CreateQuestionBankSerializer,
    CreateQuestionSerializer,
    ExamAttemptSerializer,
    ExamSerializer,
    QuestionBankSerializer,
    QuestionSerializer,
    SaveAnswersBatchSerializer,
    SaveAnswerSerializer,
)
from tenancy.scoping import set_current_institution


class TenantAPIView(APIView):
    """Activate tenant scoping after DRF resolves the JWT user."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_current_institution(getattr(request.user, "institution", None))


def _paginated(request, view, qs, serializer_class):
    paginator = DirectoryPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    rows = serializer_class(page, many=True).data
    return success_response(paginator.get_paginated_response(rows).data)


def _get_bank(user, pk):
    bank = (
        QuestionBank.all_objects.select_related("course", "course__department")
        .filter(pk=pk, institution_id=user.institution_id)
        .first()
    )
    if bank is None:
        raise NotFound("Question bank not found.")
    return bank


def _get_exam_in_tenant(user, pk):
    exam = (
        Exam.all_objects.select_related("course", "course__department", "session", "semester")
        .filter(pk=pk, institution_id=user.institution_id)
        .first()
    )
    if exam is None:
        raise NotFound("Exam not found.")
    return exam


def _get_own_attempt(user, pk):
    attempt = (
        ExamAttempt.all_objects.select_related("exam")
        .filter(pk=pk, institution_id=user.institution_id)
        .first()
    )
    if attempt is None or attempt.student_id != user.id:
        raise NotFound("Attempt not found.")
    return attempt


def _attempt_payload(attempt):
    """Attempt state + the student-safe assembled paper + saved answers. This is
    the only place the paper is returned, and it goes through the answer-free
    ``AttemptQuestionSerializer``."""
    questions = attempt.attempt_questions.select_related("question").order_by("position")
    answers = attempt.answers.all()
    return {
        "attempt": ExamAttemptSerializer(attempt).data,
        "questions": AttemptQuestionSerializer(questions, many=True).data,
        "answers": AnswerEchoSerializer(answers, many=True).data,
    }


# --------------------------------------------------------------------------- #
# Authoring (managers)                                                        #
# --------------------------------------------------------------------------- #


class QuestionBankListCreateView(TenantAPIView):
    permission_classes = [IsExamManager]

    def get(self, request):
        qs = QuestionBank.objects.select_related("course").order_by("title", "id")
        course = request.query_params.get("course")
        if course:
            qs = qs.filter(course_id=course)
        qs = [bank for bank in qs if services.can_manage_bank(request.user, bank.course)]
        return _paginated(request, self, qs, QuestionBankSerializer)

    def post(self, request):
        serializer = CreateQuestionBankSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the question bank.", serializer.errors)
        bank = services.create_question_bank(actor=request.user, **serializer.validated_data)
        return success_response(
            QuestionBankSerializer(bank).data, "Question bank created.", status.HTTP_201_CREATED
        )


class BankQuestionsView(TenantAPIView):
    """List/add questions in a bank. Manager-only, and the full question
    (including the correct answer) is returned here — this endpoint is never
    reachable by a student."""

    permission_classes = [IsExamManager]

    def get(self, request, pk):
        bank = _get_bank(request.user, pk)
        if not services.can_manage_bank(request.user, bank.course):
            raise PermissionDenied("You are not permitted to manage this bank.")
        qs = Question.all_objects.filter(bank=bank).order_by("created_at", "id")
        return _paginated(request, self, qs, QuestionSerializer)

    def post(self, request, pk):
        bank = _get_bank(request.user, pk)
        serializer = CreateQuestionSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the question.", serializer.errors)
        question = services.create_question(
            actor=request.user, bank=bank, **serializer.validated_data
        )
        return success_response(
            QuestionSerializer(question).data, "Question added.", status.HTTP_201_CREATED
        )


# --------------------------------------------------------------------------- #
# Exams (list visible to all; create by managers)                            #
# --------------------------------------------------------------------------- #


class ExamListCreateView(TenantAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsExamManager()]
        return [IsCbtParticipant()]

    def get(self, request):
        qs = services.visible_exams(request.user).order_by("-created_at")
        for param in ("course", "session", "semester"):
            value = request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        return _paginated(request, self, qs, ExamSerializer)

    def post(self, request):
        serializer = CreateExamSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the exam.", serializer.errors)
        exam = services.create_exam(actor=request.user, **serializer.validated_data)
        return success_response(ExamSerializer(exam).data, "Exam created.", status.HTTP_201_CREATED)


class ExamDetailView(TenantAPIView):
    permission_classes = [IsCbtParticipant]

    def get(self, request, pk):
        exam = services.visible_exams(request.user).filter(pk=pk).first()
        if exam is None:
            raise NotFound("Exam not found.")
        return success_response(ExamSerializer(exam).data)


# --------------------------------------------------------------------------- #
# Attempts (students)                                                         #
# --------------------------------------------------------------------------- #


class StartAttemptView(TenantAPIView):
    permission_classes = [IsStudent]

    def post(self, request, pk):
        exam = _get_exam_in_tenant(request.user, pk)
        attempt = services.start_attempt(student=request.user, exam=exam)
        return success_response(
            _attempt_payload(attempt),
            "Attempt ready.",
            status.HTTP_200_OK,
        )


class AttemptDetailView(TenantAPIView):
    """Resume an attempt after a disconnect: the same frozen paper in its stored
    order, every answer saved so far, and the authoritative time remaining.

    Resuming never reshuffles (the assembly is read from ``AttemptQuestion``, never
    re-drawn) and never resets the timer (``deadline`` is the stored server value);
    it only opportunistically finalizes an attempt whose deadline has already
    passed."""

    permission_classes = [IsStudent]

    def get(self, request, pk):
        attempt = _get_own_attempt(request.user, pk)
        services.finalize_if_expired(attempt)
        return success_response(_attempt_payload(attempt))


class SaveAnswerView(TenantAPIView):
    permission_classes = [IsStudent]

    def post(self, request, pk):
        attempt = _get_own_attempt(request.user, pk)
        serializer = SaveAnswerSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not save the answer.", serializer.errors)
        answer = services.save_answer(
            student=request.user,
            attempt=attempt,
            question_id=serializer.validated_data["question"],
            raw_response=serializer.validated_data["response"],
        )
        return success_response(AnswerEchoSerializer(answer).data, "Answer saved.")


class BatchSaveAnswersView(TenantAPIView):
    """Sync a batch of buffered answers in one request (offline reconnect).
    Idempotent, all-or-nothing, and rejected after the deadline."""

    permission_classes = [IsStudent]

    def post(self, request, pk):
        attempt = _get_own_attempt(request.user, pk)
        serializer = SaveAnswersBatchSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not save the answers.", serializer.errors)
        answers = services.save_answers_batch(
            student=request.user,
            attempt=attempt,
            items=serializer.validated_data["answers"],
        )
        return success_response(
            AnswerEchoSerializer(answers, many=True).data,
            f"{len(answers)} answer(s) saved.",
        )


class SubmitAttemptView(TenantAPIView):
    permission_classes = [IsStudent]

    def post(self, request, pk):
        attempt = _get_own_attempt(request.user, pk)
        attempt = services.submit_attempt(student=request.user, attempt=attempt)
        return success_response(ExamAttemptSerializer(attempt).data, "Attempt submitted.")
