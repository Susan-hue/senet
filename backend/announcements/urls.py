from django.urls import path

from announcements.views import AnnouncementDetailView, AnnouncementListCreateView

urlpatterns = [
    path("", AnnouncementListCreateView.as_view(), name="announcement-list"),
    path("<uuid:pk>", AnnouncementDetailView.as_view(), name="announcement-detail"),
]
