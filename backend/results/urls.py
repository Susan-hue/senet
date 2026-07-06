from django.urls import path

from results.views import (
    ResultDetailView,
    ResultListCreateView,
    ScoreEntryView,
    SubmitResultView,
)

urlpatterns = [
    path("results", ResultListCreateView.as_view(), name="result-list"),
    path("results/<uuid:pk>", ResultDetailView.as_view(), name="result-detail"),
    path("results/<uuid:pk>/scores", ScoreEntryView.as_view(), name="result-scores"),
    path("results/<uuid:pk>/submit", SubmitResultView.as_view(), name="result-submit"),
]
