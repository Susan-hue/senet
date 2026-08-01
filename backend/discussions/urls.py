from django.urls import path

from discussions.views import (
    ReplyDetailView,
    ReplyListCreateView,
    ThreadDetailView,
    ThreadListCreateView,
)

urlpatterns = [
    path("threads", ThreadListCreateView.as_view(), name="discussion-thread-list"),
    path("threads/<uuid:pk>", ThreadDetailView.as_view(), name="discussion-thread-detail"),
    path("threads/<uuid:pk>/replies", ReplyListCreateView.as_view(), name="discussion-reply-list"),
    path("replies/<uuid:pk>", ReplyDetailView.as_view(), name="discussion-reply-detail"),
]
