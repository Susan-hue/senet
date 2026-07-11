from django.urls import path

from results.views import (
    AmendmentApproveView,
    AmendmentDetailView,
    AmendmentListView,
    AmendmentReturnView,
    ApprovalWorklistView,
    ApproveResultView,
    BatchRatifyView,
    ExternalExaminerReportListCreateView,
    RaiseAmendmentView,
    ResultDetailView,
    ResultListCreateView,
    ReturnResultView,
    ScoreEntryView,
    SubmitResultView,
)

urlpatterns = [
    path("results", ResultListCreateView.as_view(), name="result-list"),
    path("results/worklist", ApprovalWorklistView.as_view(), name="result-worklist"),
    path("results/ratify", BatchRatifyView.as_view(), name="result-batch-ratify"),
    path(
        "results/external-examiner-reports",
        ExternalExaminerReportListCreateView.as_view(),
        name="external-examiner-reports",
    ),
    path("results/amendments", AmendmentListView.as_view(), name="amendment-list"),
    path("results/amendments/<uuid:pk>", AmendmentDetailView.as_view(), name="amendment-detail"),
    path(
        "results/amendments/<uuid:pk>/approve",
        AmendmentApproveView.as_view(),
        name="amendment-approve",
    ),
    path(
        "results/amendments/<uuid:pk>/return",
        AmendmentReturnView.as_view(),
        name="amendment-return",
    ),
    path("results/<uuid:pk>", ResultDetailView.as_view(), name="result-detail"),
    path("results/<uuid:pk>/scores", ScoreEntryView.as_view(), name="result-scores"),
    path("results/<uuid:pk>/submit", SubmitResultView.as_view(), name="result-submit"),
    path("results/<uuid:pk>/approve", ApproveResultView.as_view(), name="result-approve"),
    path("results/<uuid:pk>/return", ReturnResultView.as_view(), name="result-return"),
    path(
        "results/<uuid:pk>/amendments", RaiseAmendmentView.as_view(), name="result-raise-amendment"
    ),
]
