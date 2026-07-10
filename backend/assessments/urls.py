from django.urls import path

from assessments.views import (
    CaSummaryView,
    GradeView,
    ItemDetailView,
    ItemGradesView,
    ItemListCreateView,
    ItemSubmissionsView,
    MyGradesView,
    SubmitView,
)

urlpatterns = [
    path("items", ItemListCreateView.as_view(), name="assessment-item-list"),
    path("items/<uuid:pk>", ItemDetailView.as_view(), name="assessment-item-detail"),
    path("items/<uuid:pk>/submit", SubmitView.as_view(), name="assessment-item-submit"),
    path(
        "items/<uuid:pk>/submissions",
        ItemSubmissionsView.as_view(),
        name="assessment-item-submissions",
    ),
    path("items/<uuid:pk>/grade", GradeView.as_view(), name="assessment-item-grade"),
    path("items/<uuid:pk>/grades", ItemGradesView.as_view(), name="assessment-item-grades"),
    path("my-grades", MyGradesView.as_view(), name="assessment-my-grades"),
    path("ca-summary", CaSummaryView.as_view(), name="assessment-ca-summary"),
]
