from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from accounts.pagination import DirectoryPagination
from accounts.responses import error_response, success_response
from results import services
from results.permissions import CanViewResults, IsLecturer
from results.serializers import (
    CourseResultDetailSerializer,
    CourseResultSerializer,
    CreateResultSerializer,
    ScoreInputSerializer,
    StudentScoreSerializer,
)
from tenancy.scoping import set_current_institution


class TenantAPIView(APIView):
    """Activate tenant scoping after DRF resolves the JWT user."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_current_institution(getattr(request.user, "institution", None))


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
