from django.urls import path

from grading.views import (
    ComputeStandingView,
    MyStandingView,
    StandingListView,
    StudentStandingView,
)

urlpatterns = [
    path("my-standing", MyStandingView.as_view(), name="grading-my-standing"),
    path(
        "students/<uuid:student_id>/standing",
        StudentStandingView.as_view(),
        name="grading-student-standing",
    ),
    path("compute", ComputeStandingView.as_view(), name="grading-compute"),
    path("standings", StandingListView.as_view(), name="grading-standing-list"),
]
