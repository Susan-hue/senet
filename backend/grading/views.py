from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.views import APIView

from accounts.models import Role, Semester, Session, User
from accounts.pagination import DirectoryPagination
from accounts.responses import error_response, success_response
from grading import services
from grading.models import AcademicStanding
from grading.permissions import (
    CanTriggerComputation,
    CanViewStanding,
    can_view_student,
)
from grading.serializers import AcademicStandingSerializer, ComputeRequestSerializer
from grading.tasks import compute_department_standing
from tenancy.scoping import set_current_institution


class TenantAPIView(APIView):
    """Activate tenant scoping after DRF resolves the JWT user."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_current_institution(getattr(request.user, "institution", None))


def _term_from_params(request):
    session_id = request.query_params.get("session")
    semester_id = request.query_params.get("semester")
    if not session_id or not semester_id:
        return None, None
    institution = request.user.institution
    session = Session.all_objects.filter(pk=session_id, institution=institution).first()
    semester = Semester.all_objects.filter(pk=semester_id, institution=institution).first()
    if session is None or semester is None:
        raise NotFound("Session or semester not found.")
    return session, semester


def _serializable(summary):
    term = summary["term"]
    if term is not None and term["gpa"] is not None:
        term["gpa"] = str(term["gpa"])
    cumulative = summary["cumulative"]
    if cumulative["cgpa"] is not None:
        cumulative["cgpa"] = str(cumulative["cgpa"])
    return summary


class MyStandingView(TenantAPIView):
    permission_classes = [CanViewStanding]

    def get(self, request):
        if request.user.role not in (Role.STUDENT, Role.COURSE_REP):
            raise PermissionDenied("Only students have a personal academic standing.")
        session, semester = _term_from_params(request)
        return success_response(
            _serializable(services.student_summary(request.user, session, semester))
        )


class StudentStandingView(TenantAPIView):
    permission_classes = [CanViewStanding]

    def get(self, request, student_id):
        student = (
            User.objects.filter(
                pk=student_id,
                institution=request.user.institution,
                role__in=(Role.STUDENT, Role.COURSE_REP),
            )
            .select_related("department")
            .first()
        )
        if student is None:
            raise NotFound("Student not found.")
        if not can_view_student(request.user, student):
            raise PermissionDenied("This student is outside your scope.")
        session, semester = _term_from_params(request)
        return success_response(_serializable(services.student_summary(student, session, semester)))


def _department_in_scope(actor, department):
    if actor.role == Role.HOD:
        return actor.department_id == department.id
    if actor.role == Role.DEAN:
        return actor.faculty_id is not None and department.faculty_id == actor.faculty_id
    return actor.role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN)


class ComputeStandingView(TenantAPIView):
    permission_classes = [CanTriggerComputation]

    def post(self, request):
        serializer = ComputeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not start the computation.", serializer.errors)
        department = serializer.validated_data["department"]
        if not _department_in_scope(request.user, department):
            raise PermissionDenied("This department is outside your scope.")

        session = serializer.validated_data["session"]
        semester = serializer.validated_data["semester"]
        compute_department_standing.delay(str(department.id), str(session.id), str(semester.id))
        return success_response(
            {
                "department": str(department.id),
                "session": str(session.id),
                "semester": str(semester.id),
            },
            "Standing computation queued for the department.",
            status.HTTP_202_ACCEPTED,
        )


class StandingListView(TenantAPIView):
    permission_classes = [CanTriggerComputation]

    def get(self, request):
        qs = AcademicStanding.objects.select_related("student").order_by("student__full_name", "id")
        user = request.user
        if user.role == Role.HOD:
            qs = qs.filter(student__department_id=user.department_id)
        elif user.role == Role.DEAN:
            qs = qs.filter(student__department__faculty_id=user.faculty_id)

        for param in ("session", "semester"):
            value = request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        department = request.query_params.get("department")
        if department:
            qs = qs.filter(student__department_id=department)

        paginator = DirectoryPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        rows = AcademicStandingSerializer(page, many=True).data
        return success_response(paginator.get_paginated_response(rows).data)
