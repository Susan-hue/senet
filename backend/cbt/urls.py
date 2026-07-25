from django.urls import path

from cbt.views import (
    AttemptDetailView,
    AttemptFlagView,
    BankQuestionsView,
    BatchSaveAnswersView,
    DismissFlagView,
    EscalateFlagView,
    ExamDetailView,
    ExamListCreateView,
    FlagListView,
    IntegrityReportView,
    QuestionBankListCreateView,
    RecordProctorEventView,
    SaveAnswerView,
    StartAttemptView,
    SubmitAttemptView,
    WebcamView,
)

urlpatterns = [
    path("banks", QuestionBankListCreateView.as_view(), name="cbt-bank-list"),
    path("banks/<uuid:pk>/questions", BankQuestionsView.as_view(), name="cbt-bank-questions"),
    path("exams", ExamListCreateView.as_view(), name="cbt-exam-list"),
    path("exams/<uuid:pk>", ExamDetailView.as_view(), name="cbt-exam-detail"),
    path("exams/<uuid:pk>/start", StartAttemptView.as_view(), name="cbt-exam-start"),
    path("attempts/<uuid:pk>", AttemptDetailView.as_view(), name="cbt-attempt-detail"),
    path("attempts/<uuid:pk>/answer", SaveAnswerView.as_view(), name="cbt-attempt-answer"),
    path("attempts/<uuid:pk>/answers", BatchSaveAnswersView.as_view(), name="cbt-attempt-answers"),
    path("attempts/<uuid:pk>/submit", SubmitAttemptView.as_view(), name="cbt-attempt-submit"),
    path("attempts/<uuid:pk>/events", RecordProctorEventView.as_view(), name="cbt-attempt-events"),
    path("attempts/<uuid:pk>/webcam", WebcamView.as_view(), name="cbt-attempt-webcam"),
    path(
        "attempts/<uuid:pk>/integrity-report",
        IntegrityReportView.as_view(),
        name="cbt-attempt-integrity-report",
    ),
    path("attempts/<uuid:pk>/flag", AttemptFlagView.as_view(), name="cbt-attempt-flag"),
    path("flags", FlagListView.as_view(), name="cbt-flag-list"),
    path("flags/<uuid:pk>/dismiss", DismissFlagView.as_view(), name="cbt-flag-dismiss"),
    path("flags/<uuid:pk>/escalate", EscalateFlagView.as_view(), name="cbt-flag-escalate"),
]
