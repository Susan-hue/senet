from django.urls import path

from cbt.views import (
    AttemptDetailView,
    BankQuestionsView,
    BatchSaveAnswersView,
    ExamDetailView,
    ExamListCreateView,
    QuestionBankListCreateView,
    SaveAnswerView,
    StartAttemptView,
    SubmitAttemptView,
)

urlpatterns = [
    # Authoring (managers).
    path("banks", QuestionBankListCreateView.as_view(), name="cbt-bank-list"),
    path("banks/<uuid:pk>/questions", BankQuestionsView.as_view(), name="cbt-bank-questions"),
    # Exams.
    path("exams", ExamListCreateView.as_view(), name="cbt-exam-list"),
    path("exams/<uuid:pk>", ExamDetailView.as_view(), name="cbt-exam-detail"),
    path("exams/<uuid:pk>/start", StartAttemptView.as_view(), name="cbt-exam-start"),
    # Attempts (students).
    path("attempts/<uuid:pk>", AttemptDetailView.as_view(), name="cbt-attempt-detail"),
    path("attempts/<uuid:pk>/answer", SaveAnswerView.as_view(), name="cbt-attempt-answer"),
    path("attempts/<uuid:pk>/answers", BatchSaveAnswersView.as_view(), name="cbt-attempt-answers"),
    path("attempts/<uuid:pk>/submit", SubmitAttemptView.as_view(), name="cbt-attempt-submit"),
]
