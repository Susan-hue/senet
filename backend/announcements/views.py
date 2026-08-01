from rest_framework import status
from rest_framework.exceptions import NotFound

from accounts.coursework import (
    IsCourseManager,
    IsCourseParticipant,
    TenantAPIView,
    get_scoped,
    paginated,
    require_access,
    resolve_course_term,
)
from accounts.responses import error_response, success_response
from announcements import services
from announcements.models import Announcement
from announcements.serializers import (
    AnnouncementSerializer,
    CreateAnnouncementSerializer,
    UpdateAnnouncementSerializer,
)

RELATIONS = ("course", "course__department", "session", "semester", "author")


class AnnouncementListCreateView(TenantAPIView):
    def get_permissions(self):
        return [IsCourseManager()] if self.request.method == "POST" else [IsCourseParticipant()]

    def get(self, request):
        """The class's announcement feed.

        A course-term may be given to read one course's feed; without it a
        student gets every course they are enrolled in, which is the portal's
        combined view.
        """
        course, session, semester = resolve_course_term(request, required=False)
        if course is not None:
            require_access(request.user, course, session, semester)
        qs = (
            services.visible_announcements(
                request.user, course=course, session=session, semester=semester
            )
            .select_related("course", "author")
            .order_by("-is_pinned", "-created_at", "id")
        )
        return paginated(request, self, qs, AnnouncementSerializer)

    def post(self, request):
        serializer = CreateAnnouncementSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not post the announcement.", serializer.errors)
        announcement = services.create_announcement(actor=request.user, **serializer.validated_data)
        return success_response(
            AnnouncementSerializer(announcement).data,
            "Announcement posted.",
            status.HTTP_201_CREATED,
        )


class AnnouncementDetailView(TenantAPIView):
    def get_permissions(self):
        return [IsCourseParticipant()] if self.request.method == "GET" else [IsCourseManager()]

    def get(self, request, pk):
        announcement = (
            services.visible_announcements(request.user)
            .select_related("course", "author")
            .filter(pk=pk)
            .first()
        )
        if announcement is None:
            raise NotFound("Announcement not found.")
        return success_response(AnnouncementSerializer(announcement).data)

    def patch(self, request, pk):
        announcement = get_scoped(
            Announcement,
            pk,
            request.user,
            select_related=RELATIONS,
            message="Announcement not found.",
        )
        serializer = UpdateAnnouncementSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Could not update the announcement.", serializer.errors)
        announcement = services.update_announcement(
            actor=request.user, announcement=announcement, **serializer.validated_data
        )
        return success_response(AnnouncementSerializer(announcement).data, "Announcement updated.")

    def delete(self, request, pk):
        announcement = get_scoped(
            Announcement,
            pk,
            request.user,
            select_related=RELATIONS,
            message="Announcement not found.",
        )
        services.delete_announcement(actor=request.user, announcement=announcement)
        return success_response(None, "Announcement deleted.")
