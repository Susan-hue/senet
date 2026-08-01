from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from accounts.pagination import paginated_response
from accounts.responses import error_response, success_response
from auditor.authentication import AuditorTokenAuthentication
from auditor.models import AuditorAccessLog, AuditorToken
from auditor.permissions import IsSchoolAdmin, IsValidAuditor
from auditor.serializers import AuditorTokenSerializer, CreateAuditorTokenSerializer
from auditor.services import (
    auditor_result_or_none,
    auditor_visible_examiner_reports,
    auditor_visible_results,
    create_auditor_token,
    result_dossier,
    revoke_auditor_token,
)
from results.exports import (
    PDF_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    build_broadsheet_xlsx,
    build_ogr_pdf,
    current_scores,
    export_basename,
)
from results.serializers import (
    CourseResultSerializer,
    ExternalExaminerReportSerializer,
    StudentScoreSerializer,
)
from tenancy.scoping import set_current_institution
from tenancy.views import TenantAPIView


def _attachment(data, filename, content_type):
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --------------------------------------------------------------------------- #
# Token management (school_admin, JWT-authenticated)                          #
# --------------------------------------------------------------------------- #


class AuditorTokenListCreateView(TenantAPIView):
    permission_classes = [IsSchoolAdmin]

    def get(self, request):
        qs = AuditorToken.objects.prefetch_related("programmes", "sessions").order_by("-created_at")
        return paginated_response(request, self, qs, AuditorTokenSerializer)

    def post(self, request):
        serializer = CreateAuditorTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the auditor token.", serializer.errors)
        token, raw = create_auditor_token(actor=request.user, **serializer.validated_data)
        data = AuditorTokenSerializer(token).data
        # Shown once and never again — only the hash is persisted.
        data["token"] = raw
        return success_response(
            data,
            "Auditor token created. Copy the token now; it will not be shown again.",
            status.HTTP_201_CREATED,
        )


class AuditorTokenRevokeView(TenantAPIView):
    permission_classes = [IsSchoolAdmin]

    def post(self, request, pk):
        token = AuditorToken.objects.filter(pk=pk).first()
        if token is None:
            raise NotFound("Auditor token not found.")
        token = revoke_auditor_token(actor=request.user, token=token)
        return success_response(AuditorTokenSerializer(token).data, "Auditor token revoked.")


# --------------------------------------------------------------------------- #
# Auditor read-only path (auditor-token-authenticated)                        #
# --------------------------------------------------------------------------- #


class AuditorReadView(APIView):
    """Base for every auditor endpoint.

    Read-only by construction: token auth yields a role-less principal, the
    permission demands a SAFE_METHOD, ``http_method_names`` exposes only GET, and
    each successful access is appended to the audit trail before the handler runs.
    """

    authentication_classes = [AuditorTokenAuthentication]
    permission_classes = [IsValidAuditor]
    http_method_names = ["get", "head", "options"]
    resource = "auditor"

    def initial(self, request, *args, **kwargs):
        # Runs authentication + permission checks first; only logs real, allowed
        # accesses (a rejected token raises before we reach this point).
        super().initial(request, *args, **kwargs)
        token = request.user.token
        set_current_institution(token.institution)
        AuditorAccessLog.all_objects.create(
            institution=token.institution,
            token=token,
            method=request.method,
            path=request.path[:255],
            resource=self.resource,
            detail={key: str(value) for key, value in kwargs.items()} or None,
            ip_address=request.META.get("REMOTE_ADDR"),
        )

    @property
    def token(self):
        return self.request.user.token


class AuditorResultListView(AuditorReadView):
    resource = "results"

    def get(self, request):
        qs = auditor_visible_results(self.token)
        return paginated_response(request, self, qs, CourseResultSerializer)


class AuditorResultDetailView(AuditorReadView):
    resource = "result_detail"

    def get(self, request, pk):
        result = auditor_result_or_none(self.token, pk)
        if result is None:
            raise NotFound("Result not found within this token's scope.")
        data = CourseResultSerializer(result).data
        data["scores"] = StudentScoreSerializer(current_scores(result), many=True).data
        data.update(result_dossier(result))
        return success_response(data)


class AuditorBroadsheetView(AuditorReadView):
    resource = "broadsheet"

    def get(self, request, pk):
        result = auditor_result_or_none(self.token, pk)
        if result is None:
            raise NotFound("Result not found within this token's scope.")
        data = build_broadsheet_xlsx(result)
        return _attachment(data, export_basename(result, "xlsx"), XLSX_CONTENT_TYPE)


class AuditorOGRView(AuditorReadView):
    resource = "ogr"

    def get(self, request, pk):
        result = auditor_result_or_none(self.token, pk)
        if result is None:
            raise NotFound("Result not found within this token's scope.")
        data = build_ogr_pdf(result)
        return _attachment(data, export_basename(result, "pdf"), PDF_CONTENT_TYPE)


class AuditorExaminerReportListView(AuditorReadView):
    resource = "external_examiner_reports"

    def get(self, request):
        qs = auditor_visible_examiner_reports(self.token)
        return paginated_response(request, self, qs, ExternalExaminerReportSerializer)
