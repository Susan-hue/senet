from django.urls import path

from auditor.views import (
    AuditorBroadsheetView,
    AuditorExaminerReportListView,
    AuditorOGRView,
    AuditorResultDetailView,
    AuditorResultListView,
    AuditorTokenListCreateView,
    AuditorTokenRevokeView,
)

urlpatterns = [
    # Token management (school_admin, JWT-authenticated).
    path("tokens", AuditorTokenListCreateView.as_view(), name="auditor-token-list"),
    path(
        "tokens/<uuid:pk>/revoke",
        AuditorTokenRevokeView.as_view(),
        name="auditor-token-revoke",
    ),
    # Read-only auditor path (auditor-token-authenticated).
    path("results", AuditorResultListView.as_view(), name="auditor-result-list"),
    path("results/<uuid:pk>", AuditorResultDetailView.as_view(), name="auditor-result-detail"),
    path(
        "results/<uuid:pk>/broadsheet",
        AuditorBroadsheetView.as_view(),
        name="auditor-result-broadsheet",
    ),
    path("results/<uuid:pk>/ogr", AuditorOGRView.as_view(), name="auditor-result-ogr"),
    path(
        "external-examiner-reports",
        AuditorExaminerReportListView.as_view(),
        name="auditor-examiner-reports",
    ),
]
