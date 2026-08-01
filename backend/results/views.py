import logging

from django.conf import settings
from django.http import FileResponse, HttpResponse
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from accounts.pagination import DirectoryPagination
from accounts.responses import error_response, success_response
from results import services
from results.exports import (
    PDF_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    build_broadsheet_xlsx,
    build_ogr_pdf,
    export_basename,
)
from results.models import AmendmentStatus, ExportJob, StudentScore
from results.permissions import CanViewResults, IsDean, IsLecturer, IsSenateAdmin
from results.serializers import (
    BatchRatifySerializer,
    CourseResultDetailSerializer,
    CourseResultSerializer,
    CreateExternalExaminerReportSerializer,
    CreateResultSerializer,
    ExportJobSerializer,
    ExternalExaminerReportSerializer,
    RaiseAmendmentSerializer,
    ResultAmendmentSerializer,
    ReturnReasonSerializer,
    ScoreInputSerializer,
    StudentScoreSerializer,
)
from results.tasks import generate_export
from tenancy.scoping import set_current_institution

logger = logging.getLogger(__name__)


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
        qs = services.filter_results(services.visible_results(request.user), request.query_params)
        qs = qs.select_related("course__department", "session", "semester", "lecturer").order_by(
            "-created_at"
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
            .select_related("course__department", "session", "semester", "lecturer")
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
    dean-approved sheets institution-wide.

    Boards drill rather than browse, so the role-scoped queryset is further
    narrowed by the ``faculty``/``department``/``session``/``semester``/``course``
    and ``search`` parameters before it is paginated. Filters can only subtract
    from what the role already allows."""

    permission_classes = [CanViewResults]

    def get(self, request):
        qs = services.filter_results(
            services.pending_results_for(request.user), request.query_params
        )
        qs = qs.select_related("course__department", "session", "semester", "lecturer").order_by(
            "-created_at"
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


def _visible_result_or_404(user, pk):
    result = (
        services.visible_results(user)
        .select_related("institution", "course__department", "session", "semester", "lecturer")
        .filter(pk=pk)
        .first()
    )
    if result is None:
        raise NotFound("Result not found.")
    return result


def _attachment(data, filename, content_type):
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


_EXPORT_CONTENT_TYPE = {
    ExportJob.Kind.BROADSHEET: XLSX_CONTENT_TYPE,
    ExportJob.Kind.OGR: PDF_CONTENT_TYPE,
}
_EXPORT_EXTENSION = {
    ExportJob.Kind.BROADSHEET: "xlsx",
    ExportJob.Kind.OGR: "pdf",
}
_EXPORT_BUILDER = {
    ExportJob.Kind.BROADSHEET: build_broadsheet_xlsx,
    ExportJob.Kind.OGR: build_ogr_pdf,
}


def _export_or_offload(request, result, kind):
    """Render an export inline, or hand large classes to a Celery worker.

    Classes over ``EXPORT_ASYNC_THRESHOLD`` return a 202 with an ExportJob to poll
    and download; smaller ones stream the file directly. Read-only either way."""
    extension = _EXPORT_EXTENSION[kind]
    class_size = StudentScore.all_objects.filter(result=result, is_current=True).count()
    if class_size > settings.EXPORT_ASYNC_THRESHOLD:
        job = ExportJob.all_objects.create(
            institution=result.institution,
            result=result,
            kind=kind,
            filename=export_basename(result, extension),
            requested_by=request.user,
        )
        try:
            generate_export.delay(str(job.id))
        except OperationalError:
            # Nothing will pick the job up, so it is failed here instead of
            # leaving the caller polling a job that never moves.
            logger.exception("Could not queue export job %s", job.id)
            job.status = ExportJob.Status.FAILED
            job.message = "The export could not be queued. Please try again."
            job.save(update_fields=["status", "message", "updated_at"])
            return error_response(job.message, http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return success_response(
            ExportJobSerializer(job).data,
            "The class is large; the export is being generated. Poll the job to download it.",
            status.HTTP_202_ACCEPTED,
        )
    data = _EXPORT_BUILDER[kind](result)
    return _attachment(data, export_basename(result, extension), _EXPORT_CONTENT_TYPE[kind])


class OGRExportView(TenantAPIView):
    """Official Grade Report PDF for a result the actor is allowed to see.

    Scoping is exactly ``visible_results`` — lecturer for their own sheet, HOD in
    department, Dean in faculty, senate/school admins institution-wide. Small
    classes render inline; large ones are generated on a Celery worker."""

    permission_classes = [CanViewResults]

    def get(self, request, pk):
        result = _visible_result_or_404(request.user, pk)
        return _export_or_offload(request, result, ExportJob.Kind.OGR)


class BroadsheetExportView(TenantAPIView):
    """Broadsheet .xlsx for a result. Small classes render inline; classes over
    ``EXPORT_ASYNC_THRESHOLD`` are generated by a Celery worker and returned as a
    job to poll and download."""

    permission_classes = [CanViewResults]

    def get(self, request, pk):
        result = _visible_result_or_404(request.user, pk)
        return _export_or_offload(request, result, ExportJob.Kind.BROADSHEET)


class ExportJobDetailView(TenantAPIView):
    """Poll an export job; once completed, streams the stored file."""

    permission_classes = [CanViewResults]

    def get(self, request, pk):
        job = (
            ExportJob.all_objects.filter(pk=pk, institution_id=request.user.institution_id)
            .select_related("result")
            .first()
        )
        if (
            job is None
            or not services.visible_results(request.user).filter(pk=job.result_id).exists()
        ):
            raise NotFound("Export job not found.")
        if job.status == ExportJob.Status.COMPLETED and job.file:
            return FileResponse(
                job.file.open("rb"),
                content_type=_EXPORT_CONTENT_TYPE[job.kind],
                as_attachment=True,
                filename=job.filename,
            )
        return success_response(ExportJobSerializer(job).data)


class ExternalExaminerReportListCreateView(TenantAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDean()]
        return [CanViewResults()]

    def get(self, request):
        qs = services.filter_examiner_reports(
            services.visible_examiner_reports(request.user), request.query_params
        )
        return _paginated(
            request,
            self,
            qs.select_related("faculty", "programme"),
            ExternalExaminerReportSerializer,
        )

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
