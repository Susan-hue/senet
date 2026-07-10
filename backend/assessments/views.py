from django.db.models import Exists, OuterRef
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.views import APIView

from accounts.models import CourseAssignment, Enrolment, Role
from accounts.pagination import DirectoryPagination
from accounts.responses import error_response, success_response
from accounts.services import lecturer_can_access_course
from assessments import services
from assessments.models import AssessmentGrade, AssessmentItem, Submission
from assessments.permissions import (
    IsGradeReader,
    IsLecturer,
    IsLecturerOrStudent,
    IsStudent,
)
from assessments.serializers import (
    AssessmentItemSerializer,
    CreateItemSerializer,
    GradeInputSerializer,
    GradeSerializer,
    SubmissionSerializer,
    SubmissionUploadSerializer,
)
from tenancy.scoping import set_current_institution


class TenantAPIView(APIView):
    """Activate tenant scoping after DRF resolves the JWT user."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_current_institution(getattr(request.user, "institution", None))


def _visible_items(user):
    """Items the user may see: lecturers their assigned course terms, students
    the course terms they are enrolled in."""
    qs = AssessmentItem.objects.all()
    if user.role == Role.LECTURER:
        assigned = CourseAssignment.all_objects.filter(
            lecturer=user,
            course=OuterRef("course"),
            session=OuterRef("session"),
            semester=OuterRef("semester"),
        )
        return qs.filter(Exists(assigned))
    if user.role in (Role.STUDENT, Role.COURSE_REP):
        enrolled = Enrolment.all_objects.filter(
            student=user,
            course=OuterRef("course"),
            session=OuterRef("session"),
            semester=OuterRef("semester"),
        )
        return qs.filter(Exists(enrolled))
    return qs.none()


def _get_item(pk, user):
    item = (
        AssessmentItem.all_objects.select_related(
            "course", "course__department", "session", "semester"
        )
        .filter(pk=pk, institution_id=user.institution_id)
        .first()
    )
    if item is None:
        raise NotFound("Assessment item not found.")
    return item


def _paginated(request, view, qs, serializer_class, **serializer_kwargs):
    paginator = DirectoryPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    rows = serializer_class(page, many=True, **serializer_kwargs).data
    return success_response(paginator.get_paginated_response(rows).data)


class ItemListCreateView(TenantAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsLecturer()]
        return [IsLecturerOrStudent()]

    def get(self, request):
        qs = _visible_items(request.user).select_related("course")
        for param in ("course", "session", "semester"):
            value = request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        return _paginated(request, self, qs, AssessmentItemSerializer)

    def post(self, request):
        serializer = CreateItemSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the assessment item.", serializer.errors)
        item = services.create_item(lecturer=request.user, **serializer.validated_data)
        return success_response(
            AssessmentItemSerializer(item).data,
            "Assessment item created.",
            status.HTTP_201_CREATED,
        )


class ItemDetailView(TenantAPIView):
    permission_classes = [IsLecturerOrStudent]

    def get(self, request, pk):
        item = _visible_items(request.user).select_related("course").filter(pk=pk).first()
        if item is None:
            raise NotFound("Assessment item not found.")
        data = AssessmentItemSerializer(item).data
        if request.user.role in (Role.STUDENT, Role.COURSE_REP):
            submission = Submission.all_objects.filter(item=item, student=request.user).first()
            grade = AssessmentGrade.all_objects.filter(
                item=item, student=request.user, is_released=True
            ).first()
            data["my_submission"] = SubmissionSerializer(submission).data if submission else None
            data["my_grade"] = GradeSerializer(grade).data if grade else None
        return success_response(data)


class SubmitView(TenantAPIView):
    permission_classes = [IsStudent]

    def post(self, request, pk):
        item = _get_item(pk, request.user)
        serializer = SubmissionUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not accept the submission.", serializer.errors)
        submission = services.submit_file(
            student=request.user, item=item, upload=serializer.validated_data["file"]
        )
        message = (
            "Submission received after the deadline and flagged as late."
            if submission.is_late
            else "Submission received."
        )
        return success_response(SubmissionSerializer(submission).data, message)


class ItemSubmissionsView(TenantAPIView):
    permission_classes = [IsLecturer]

    def get(self, request, pk):
        item = _get_item(pk, request.user)
        if not lecturer_can_access_course(request.user, item.course, item.session, item.semester):
            raise PermissionDenied("You are not assigned to this course for this term.")
        qs = (
            Submission.all_objects.filter(item=item)
            .select_related("student")
            .order_by("submitted_at", "id")
        )
        return _paginated(request, self, qs, SubmissionSerializer)


class GradeView(TenantAPIView):
    permission_classes = [IsLecturer]

    def post(self, request, pk):
        item = _get_item(pk, request.user)
        serializer = GradeInputSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not record the grade.", serializer.errors)
        grade = services.grade_student(
            lecturer=request.user, item=item, **serializer.validated_data
        )
        return success_response(GradeSerializer(grade).data, "Grade recorded.")


class ItemGradesView(TenantAPIView):
    """Existing grades for an assessment item, for the lecturer marking it (and
    HODs/deans/admins in scope). Backs the roster on the grading page so already
    entered scores survive a reload."""

    permission_classes = [IsGradeReader]

    def get(self, request, pk):
        item = _get_item(pk, request.user)
        if not services.can_read_item_grades(request.user, item):
            raise PermissionDenied("You are not permitted to read grades for this course.")
        qs = (
            AssessmentGrade.all_objects.filter(item=item)
            .select_related("item", "student", "submission")
            .order_by("student__full_name", "id")
        )
        return _paginated(request, self, qs, GradeSerializer)


class MyGradesView(TenantAPIView):
    permission_classes = [IsStudent]

    def get(self, request):
        qs = (
            AssessmentGrade.objects.filter(student=request.user, is_released=True)
            .select_related("item", "student")
            .order_by("-created_at", "id")
        )
        for param in ("course", "session", "semester"):
            value = request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"item__{param}_id": value})
        return _paginated(request, self, qs, GradeSerializer)


class CaSummaryView(TenantAPIView):
    """Per-student aggregated CA for a course term — the bridge the lecturer
    uses to move graded assessment work into the results pipeline."""

    permission_classes = [IsLecturer]

    def get(self, request):
        params = {}
        errors = {}
        for name in ("course", "session", "semester"):
            value = request.query_params.get(name)
            if not value:
                errors[name] = "This query parameter is required."
            params[name] = value
        if errors:
            return error_response("course, session and semester are required.", errors)

        item = (
            AssessmentItem.all_objects.filter(
                institution_id=request.user.institution_id,
                course_id=params["course"],
                session_id=params["session"],
                semester_id=params["semester"],
            )
            .select_related("course", "session", "semester")
            .first()
        )
        if item is None:
            return error_response(
                "No assessment items exist for this course and term.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if not lecturer_can_access_course(request.user, item.course, item.session, item.semester):
            raise PermissionDenied("You are not assigned to this course for this term.")

        enrolments = (
            Enrolment.all_objects.filter(
                institution_id=request.user.institution_id,
                course=item.course,
                session=item.session,
                semester=item.semester,
            )
            .select_related("student")
            .order_by("student__full_name", "id")
        )
        paginator = DirectoryPagination()
        page = paginator.paginate_queryset(enrolments, request, view=self)
        rows = [
            {
                "student": str(enrolment.student_id),
                "student_name": enrolment.student.full_name,
                "student_identifier": enrolment.student.identifier,
                "ca_score": str(
                    services.aggregate_ca_for_student(
                        item.course, item.session, item.semester, enrolment.student
                    )
                ),
            }
            for enrolment in page
        ]
        return success_response(paginator.get_paginated_response(rows).data)
