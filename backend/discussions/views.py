from rest_framework import status
from rest_framework.exceptions import NotFound

from accounts.coursework import (
    IsCourseParticipant,
    TenantAPIView,
    get_scoped,
    paginated,
    require_access,
    resolve_course_term,
)
from accounts.responses import error_response, success_response
from discussions import services
from discussions.models import Reply, Thread
from discussions.serializers import (
    CreateThreadSerializer,
    ReplyInputSerializer,
    ReplySerializer,
    ThreadSerializer,
    UpdateThreadSerializer,
)

THREAD_RELATIONS = ("course", "course__department", "session", "semester", "author")
REPLY_RELATIONS = (
    "thread",
    "thread__course",
    "thread__course__department",
    "thread__session",
    "thread__semester",
    "author",
)


def _get_thread(pk, user):
    return get_scoped(
        Thread, pk, user, select_related=THREAD_RELATIONS, message="Thread not found."
    )


class ThreadListCreateView(TenantAPIView):
    """The board. Both students and teaching staff may open a thread."""

    permission_classes = [IsCourseParticipant]

    def get(self, request):
        course, session, semester = resolve_course_term(request, required=False)
        if course is not None:
            require_access(request.user, course, session, semester)
        qs = (
            services.visible_threads(
                request.user, course=course, session=session, semester=semester
            )
            .select_related("course", "author")
            .order_by("-is_pinned", "-last_activity_at", "id")
        )
        return paginated(request, self, qs, ThreadSerializer)

    def post(self, request):
        serializer = CreateThreadSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not start the thread.", serializer.errors)
        thread = services.create_thread(actor=request.user, **serializer.validated_data)
        return success_response(
            ThreadSerializer(thread).data, "Thread started.", status.HTTP_201_CREATED
        )


class ThreadDetailView(TenantAPIView):
    permission_classes = [IsCourseParticipant]

    def get(self, request, pk):
        thread = (
            services.visible_threads(request.user)
            .select_related("course", "author")
            .filter(pk=pk)
            .first()
        )
        if thread is None:
            raise NotFound("Thread not found.")
        data = ThreadSerializer(thread).data
        data["can_moderate"] = services.can_moderate(request.user, thread)
        return success_response(data)

    def patch(self, request, pk):
        thread = _get_thread(pk, request.user)
        require_access(request.user, thread.course, thread.session, thread.semester)
        serializer = UpdateThreadSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Could not update the thread.", serializer.errors)
        thread = services.update_thread(
            actor=request.user, thread=thread, **serializer.validated_data
        )
        return success_response(ThreadSerializer(thread).data, "Thread updated.")

    def delete(self, request, pk):
        thread = _get_thread(pk, request.user)
        require_access(request.user, thread.course, thread.session, thread.semester)
        services.remove_thread(actor=request.user, thread=thread)
        return success_response(None, "Thread removed.")


class ReplyListCreateView(TenantAPIView):
    permission_classes = [IsCourseParticipant]

    def get(self, request, pk):
        thread = _get_thread(pk, request.user)
        require_access(request.user, thread.course, thread.session, thread.semester)
        if thread.is_removed:
            raise NotFound("Thread not found.")
        replies = services.visible_replies(request.user, thread=thread).order_by("created_at", "id")
        return paginated(request, self, replies, ReplySerializer)

    def post(self, request, pk):
        thread = _get_thread(pk, request.user)
        serializer = ReplyInputSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not post the reply.", serializer.errors)
        reply = services.create_reply(
            actor=request.user, thread=thread, body=serializer.validated_data["body"]
        )
        return success_response(
            ReplySerializer(reply).data, "Reply posted.", status.HTTP_201_CREATED
        )


class ReplyDetailView(TenantAPIView):
    permission_classes = [IsCourseParticipant]

    def patch(self, request, pk):
        reply = get_scoped(
            Reply, pk, request.user, select_related=REPLY_RELATIONS, message="Reply not found."
        )
        thread = reply.thread
        require_access(request.user, thread.course, thread.session, thread.semester)
        serializer = ReplyInputSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not update the reply.", serializer.errors)
        reply = services.update_reply(
            actor=request.user, reply=reply, body=serializer.validated_data["body"]
        )
        return success_response(ReplySerializer(reply).data, "Reply updated.")

    def delete(self, request, pk):
        reply = get_scoped(
            Reply, pk, request.user, select_related=REPLY_RELATIONS, message="Reply not found."
        )
        thread = reply.thread
        require_access(request.user, thread.course, thread.session, thread.semester)
        services.remove_reply(actor=request.user, reply=reply)
        return success_response(None, "Reply removed.")
