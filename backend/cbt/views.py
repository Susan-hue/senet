from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.pagination import paginated_response
from accounts.responses import error_response, success_response
from auditor.authentication import AuditorTokenAuthentication
from cbt import ai, ca, proctoring, services
from cbt.models import CheatingFlag, Exam, ExamAttempt, Question, QuestionBank
from cbt.permissions import (
    IsCbtParticipant,
    IsExamManager,
    IsProctoringReviewer,
    IsStudent,
)
from cbt.serializers import (
    AnswerEchoSerializer,
    AttemptQuestionSerializer,
    CheatingFlagSerializer,
    CreateExamSerializer,
    CreateQuestionBankSerializer,
    CreateQuestionSerializer,
    ExamAttemptSerializer,
    ExamSerializer,
    GenerateQuestionsSerializer,
    LinkCaItemSerializer,
    ProctorEventSerializer,
    QuestionBankSerializer,
    QuestionSerializer,
    RecordEventSerializer,
    ReviewFlagSerializer,
    SaveAnswersBatchSerializer,
    SaveAnswerSerializer,
    WebcamCaptureSerializer,
    WebcamUploadSerializer,
)
from tenancy.views import TenantAPIView


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
        return paginated_response(request, self, qs, QuestionBankSerializer)

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
        return paginated_response(request, self, qs, QuestionSerializer)

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
        return paginated_response(request, self, qs, ExamSerializer)

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


# --------------------------------------------------------------------------- #
# Proctoring                                                                  #
# --------------------------------------------------------------------------- #


def _get_attempt_in_tenant(principal, pk):
    attempt = (
        ExamAttempt.all_objects.select_related(
            "exam", "exam__course", "exam__course__department", "student"
        )
        .filter(pk=pk, institution_id=principal.institution_id)
        .first()
    )
    if attempt is None:
        raise NotFound("Attempt not found.")
    return attempt


def _get_flag(user, pk):
    flag = (
        CheatingFlag.all_objects.select_related(
            "attempt", "attempt__exam", "attempt__exam__course", "attempt__exam__course__department"
        )
        .filter(pk=pk, institution_id=user.institution_id)
        .first()
    )
    if flag is None:
        raise NotFound("Flag not found.")
    return flag


class RecordProctorEventView(TenantAPIView):
    """The client reports a lockdown signal (tab-switch, blur, fullscreen-exit,
    copy/paste, heartbeat). Append-only; owner-only."""

    permission_classes = [IsStudent]

    def post(self, request, pk):
        attempt = _get_own_attempt(request.user, pk)
        serializer = RecordEventSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not record the event.", serializer.errors)
        event = proctoring.record_event(
            attempt=attempt,
            event_type=serializer.validated_data["type"],
            client_timestamp=serializer.validated_data["client_timestamp"],
            detail=serializer.validated_data["detail"],
        )
        return success_response(
            ProctorEventSerializer(event).data, "Event recorded.", status.HTTP_201_CREATED
        )


class WebcamView(TenantAPIView):
    """POST a webcam snapshot/clip (student, own attempt); GET the list of an
    attempt's captures (staff in scope or a valid auditor token — never a
    student, never cross-tenant)."""

    authentication_classes = [JWTAuthentication, AuditorTokenAuthentication]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsStudent()]
        return [IsAuthenticated()]

    def post(self, request, pk):
        attempt = _get_own_attempt(request.user, pk)
        serializer = WebcamUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not store the capture.", serializer.errors)
        capture = proctoring.create_webcam_capture(attempt=attempt, **serializer.validated_data)
        return success_response(
            WebcamCaptureSerializer(capture).data, "Capture stored.", status.HTTP_201_CREATED
        )

    def get(self, request, pk):
        attempt = _get_attempt_in_tenant(request.user, pk)
        if not proctoring.can_view_webcam(request.user, attempt):
            raise PermissionDenied("You are not permitted to view this attempt's webcam media.")
        captures = attempt.webcam_captures.order_by("captured_at")
        return success_response(WebcamCaptureSerializer(captures, many=True).data)


class IntegrityReportView(TenantAPIView):
    permission_classes = [IsProctoringReviewer]

    def get(self, request, pk):
        attempt = _get_attempt_in_tenant(request.user, pk)
        if not proctoring.can_view_proctoring(request.user, attempt):
            raise PermissionDenied("You are not permitted to view this attempt's integrity data.")
        return success_response(proctoring.build_integrity_report(attempt))


class AttemptFlagView(TenantAPIView):
    permission_classes = [IsProctoringReviewer]

    def get(self, request, pk):
        attempt = _get_attempt_in_tenant(request.user, pk)
        if not proctoring.can_view_proctoring(request.user, attempt):
            raise PermissionDenied("You are not permitted to view this attempt's flag.")
        flag = CheatingFlag.all_objects.filter(attempt=attempt).first()
        if flag is None:
            raise NotFound("No flag for this attempt.")
        return success_response(CheatingFlagSerializer(flag).data)


class FlagListView(TenantAPIView):
    permission_classes = [IsProctoringReviewer]

    def get(self, request):
        qs = proctoring.visible_flags(request.user)
        for param in ("status",):
            value = request.query_params.get(param)
            if value:
                qs = qs.filter(**{param: value})
        return paginated_response(request, self, qs, CheatingFlagSerializer)


class DismissFlagView(TenantAPIView):
    permission_classes = [IsProctoringReviewer]

    def post(self, request, pk):
        flag = _get_flag(request.user, pk)
        serializer = ReviewFlagSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not dismiss the flag.", serializer.errors)
        flag = proctoring.dismiss_flag(
            actor=request.user, flag=flag, notes=serializer.validated_data["notes"]
        )
        return success_response(CheatingFlagSerializer(flag).data, "Flag dismissed.")


class EscalateFlagView(TenantAPIView):
    permission_classes = [IsProctoringReviewer]

    def post(self, request, pk):
        flag = _get_flag(request.user, pk)
        serializer = ReviewFlagSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not escalate the flag.", serializer.errors)
        flag = proctoring.escalate_flag(
            actor=request.user, flag=flag, notes=serializer.validated_data["notes"]
        )
        return success_response(CheatingFlagSerializer(flag).data, "Flag escalated to the HOD.")


class GenerateQuestionsView(TenantAPIView):
    """Draft CBT questions from a lecturer's notes/topic via the AI provider.
    Authorized managers only. Returns an un-saved preview — nothing is written to
    the bank until the lecturer reviews/edits and posts them explicitly."""

    permission_classes = [IsExamManager]

    def post(self, request, pk):
        bank = _get_bank(request.user, pk)
        if not services.can_manage_bank(request.user, bank.course):
            raise PermissionDenied("You are not permitted to manage this bank.")
        serializer = GenerateQuestionsSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not generate questions.", serializer.errors)
        try:
            drafts = ai.generate_draft_questions(
                notes=serializer.validated_data["notes"],
                count=serializer.validated_data["count"],
                question_types=serializer.validated_data["question_types"],
            )
        except ai.AIProviderError as exc:
            return error_response(str(exc), http_status=status.HTTP_502_BAD_GATEWAY)
        return success_response(
            {"bank": str(bank.id), "drafts": drafts},
            "Draft questions generated. Review and edit each one before adding it to the bank.",
        )


class LinkCaItemView(TenantAPIView):
    """Link a CBT exam to a Continuous Assessment item so graded attempts feed the
    CA aggregation. Assigned lecturer / admins in scope only."""

    permission_classes = [IsExamManager]

    def post(self, request, pk):
        exam = _get_exam_in_tenant(request.user, pk)
        serializer = LinkCaItemSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not link the CA item.", serializer.errors)
        exam = ca.link_exam_to_ca_item(
            actor=request.user, exam=exam, item=serializer.validated_data["item"]
        )
        return success_response(ExamSerializer(exam).data, "Exam linked to the CA item.")
