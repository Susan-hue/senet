from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from accounts.pagination import DirectoryPagination
from accounts.responses import error_response, success_response
from results import services
from results.models import AmendmentStatus
from results.permissions import CanViewResults, IsDean, IsLecturer, IsSenateAdmin
from results.serializers import (
    BatchRatifySerializer,
    CourseResultDetailSerializer,
    CourseResultSerializer,
    CreateExternalExaminerReportSerializer,
    CreateResultSerializer,
    ExternalExaminerReportSerializer,
    RaiseAmendmentSerializer,
    ResultAmendmentSerializer,
    ReturnReasonSerializer,
    ScoreInputSerializer,
    StudentScoreSerializer,
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


class ResultListCreateView(TenantAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsLecturer()]
        return [CanViewResults()]

    def get(self, request):
        qs = (
            services.visible_results(request.user)
            .select_related("course", "lecturer")
            .order_by("-created_at")
        )
        paginator = DirectoryPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        rows = CourseResultSerializer(page, many=True).data
        return success_response(paginator.get_paginated_response(rows).data)

    def post(self, request):
        serializer = CreateResultSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the result sheet.", serializer.errors)
        result = services.create_draft_result(lecturer=request.user, **serializer.validated_data)
        return success_response(
            CourseResultSerializer(result).data,
            "Draft result sheet created.",
            status.HTTP_201_CREATED,
        )


class ResultDetailView(TenantAPIView):
    permission_classes = [CanViewResults]

    def get(self, request, pk):
        result = (
            services.visible_results(request.user)
            .select_related("course", "lecturer")
            .filter(pk=pk)
            .first()
        )
        if result is None:
            raise NotFound("Result not found.")
        return success_response(CourseResultDetailSerializer(result).data)


class ScoreEntryView(TenantAPIView):
    permission_classes = [IsLecturer]

    def post(self, request, pk):
        serializer = ScoreInputSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not record the score.", serializer.errors)
        row = services.record_score(actor=request.user, result_id=pk, **serializer.validated_data)
        return success_response(StudentScoreSerializer(row).data, "Score recorded.")


class SubmitResultView(TenantAPIView):
    permission_classes = [IsLecturer]

    def post(self, request, pk):
        result = services.submit_result(actor=request.user, result_id=pk)
        return success_response(
            CourseResultSerializer(result).data, "Result submitted to your HOD."
        )


class ApprovalWorklistView(TenantAPIView):
    """The sheets awaiting the current actor's approval — HODs see submissions in
    their department, Deans HOD-approved sheets in their faculty, Senate admins
    dean-approved sheets institution-wide."""

    permission_classes = [CanViewResults]

    def get(self, request):
        qs = (
            services.pending_results_for(request.user)
            .select_related("course", "lecturer")
            .order_by("-created_at")
        )
        return _paginated(request, self, qs, CourseResultSerializer)


class ApproveResultView(TenantAPIView):
    """Advance a sheet one stage for the actor's role. The guarded transition
    service enforces the exact from-state, role and scope, and audits the move."""

    permission_classes = [CanViewResults]

    def post(self, request, pk):
        result = services.approve_result(actor=request.user, result_id=pk)
        return success_response(CourseResultSerializer(result).data, "Result approved.")


class ReturnResultView(TenantAPIView):
    permission_classes = [CanViewResults]

    def post(self, request, pk):
        serializer = ReturnReasonSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("A reason is required to return a result.", serializer.errors)
        result = services.return_result(
            actor=request.user, result_id=pk, reason=serializer.validated_data["reason"]
        )
        return success_response(
            CourseResultSerializer(result).data, "Result returned to the lecturer."
        )


class BatchRatifyView(TenantAPIView):
    """Senate ratifies several dean-approved sheets in one action. All-or-nothing;
    each sheet is individually scope-checked, locked and audited."""

    permission_classes = [IsSenateAdmin]

    def post(self, request):
        serializer = BatchRatifySerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not ratify the results.", serializer.errors)
        ratified = services.batch_ratify(
            actor=request.user,
            result_ids=serializer.validated_data["result_ids"],
            reason=serializer.validated_data.get("reason", ""),
        )
        return success_response(
            CourseResultSerializer(ratified, many=True).data,
            f"Ratified {len(ratified)} result sheet(s).",
        )


class ExternalExaminerReportListCreateView(TenantAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDean()]
        return [CanViewResults()]

    def get(self, request):
        qs = services.visible_examiner_reports(request.user).select_related("faculty", "programme")
        return _paginated(request, self, qs, ExternalExaminerReportSerializer)

    def post(self, request):
        serializer = CreateExternalExaminerReportSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "Could not capture the external examiner report.", serializer.errors
            )
        report = services.create_external_examiner_report(
            actor=request.user, **serializer.validated_data
        )
        return success_response(
            ExternalExaminerReportSerializer(report).data,
            "External examiner report captured.",
            status.HTTP_201_CREATED,
        )


class RaiseAmendmentView(TenantAPIView):
    permission_classes = [CanViewResults]

    def post(self, request, pk):
        serializer = RaiseAmendmentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not raise the amendment.", serializer.errors)
        amendment = services.raise_amendment(
            actor=request.user, result_id=pk, **serializer.validated_data
        )
        return success_response(
            ResultAmendmentSerializer(amendment).data,
            "Amendment raised for approval.",
            status.HTTP_201_CREATED,
        )


class AmendmentListView(TenantAPIView):
    permission_classes = [CanViewResults]

    def get(self, request):
        qs = (
            services.visible_amendments(request.user)
            .select_related("student", "result__course")
            .order_by("-created_at")
        )
        return _paginated(request, self, qs, ResultAmendmentSerializer)


class AmendmentDetailView(TenantAPIView):
    permission_classes = [CanViewResults]

    def get(self, request, pk):
        amendment = (
            services.visible_amendments(request.user)
            .select_related("student", "result__course")
            .filter(pk=pk)
            .first()
        )
        if amendment is None:
            raise NotFound("Amendment not found.")
        return success_response(ResultAmendmentSerializer(amendment).data)


class AmendmentApproveView(TenantAPIView):
    permission_classes = [CanViewResults]

    def post(self, request, pk):
        amendment = services.approve_amendment(actor=request.user, amendment_id=pk)
        if amendment.status == AmendmentStatus.APPLIED:
            message = "Amendment ratified; the original score has been superseded."
        else:
            message = "Amendment approved."
        return success_response(ResultAmendmentSerializer(amendment).data, message)


class AmendmentReturnView(TenantAPIView):
    permission_classes = [CanViewResults]

    def post(self, request, pk):
        serializer = ReturnReasonSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("A reason is required to return an amendment.", serializer.errors)
        amendment = services.return_amendment(
            actor=request.user, amendment_id=pk, reason=serializer.validated_data["reason"]
        )
        return success_response(ResultAmendmentSerializer(amendment).data, "Amendment returned.")
