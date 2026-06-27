from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.db.models import ProtectedError
from rest_framework import generics, status
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import tokens
from accounts.models import (
    Course,
    Department,
    Enrolment,
    Faculty,
    Programme,
    Semester,
    Session,
)
from accounts.permissions import IsSchoolAdmin, IsTenantMember
from accounts.responses import error_response, success_response
from accounts.serializers import (
    CourseSerializer,
    DepartmentSerializer,
    EnrolmentSerializer,
    FacultySerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProgrammeSerializer,
    RegisterSerializer,
    SemesterSerializer,
    SessionSerializer,
)
from accounts.services import enrol_student
from accounts.tasks import send_password_reset_email, send_verification_email
from tenancy.scoping import set_current_institution

User = get_user_model()


def _refresh_cookie_kwargs():
    return {
        "key": settings.AUTH_REFRESH_COOKIE_NAME,
        "httponly": True,
        "secure": settings.AUTH_REFRESH_COOKIE_SECURE,
        "samesite": settings.AUTH_REFRESH_COOKIE_SAMESITE,
        "path": settings.AUTH_REFRESH_COOKIE_PATH,
    }


def _set_refresh_cookie(response, refresh):
    response.set_cookie(
        value=str(refresh),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        **_refresh_cookie_kwargs(),
    )


def _clear_refresh_cookie(response):
    response.set_cookie(value="", max_age=0, **_refresh_cookie_kwargs())


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Registration failed.", serializer.errors)
        user = serializer.save()
        token = tokens.make_email_verification_token(user)
        send_verification_email.delay(user.email, token)
        return success_response(
            {"id": str(user.id), "email": user.email},
            "Registration successful. Check your email to verify your account.",
            status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get("token", "")
        try:
            uid = tokens.read_email_verification_token(token)
        except signing.SignatureExpired:
            return error_response("Verification link has expired.")
        except signing.BadSignature:
            return error_response("Invalid verification link.")

        user = User.objects.filter(pk=uid).first()
        if user is None:
            return error_response("Invalid verification link.")

        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified", "updated_at"])
        return success_response(message="Email verified. You can now log in.")


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Login failed.", serializer.errors)

        user = authenticate(
            request,
            username=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return error_response("Invalid credentials.", http_status=status.HTTP_401_UNAUTHORIZED)
        if not user.is_verified:
            return error_response("Email not verified.", http_status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        response = success_response({"access": str(refresh.access_token)}, "Login successful.")
        _set_refresh_cookie(response, refresh)
        return response


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not raw:
            return error_response(
                "Refresh token missing.", http_status=status.HTTP_401_UNAUTHORIZED
            )
        try:
            refresh = RefreshToken(raw)
        except TokenError:
            return error_response(
                "Invalid or expired refresh token.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )

        user = User.objects.filter(pk=refresh.payload.get("user_id")).first()
        if user is None:
            return error_response(
                "Invalid refresh token.", http_status=status.HTTP_401_UNAUTHORIZED
            )

        refresh.blacklist()
        new_refresh = RefreshToken.for_user(user)
        response = success_response({"access": str(new_refresh.access_token)}, "Token refreshed.")
        _set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass
        response = success_response(message="Logout successful.")
        _clear_refresh_cookie(response)
        return response


# --------------------------------------------------------------------------- #
# Academic structure API                                                      #
# --------------------------------------------------------------------------- #


def _is_envelope(data):
    return isinstance(data, dict) and {"status", "data", "message", "errors"} <= set(data.keys())


class EnvelopeMixin:
    """Wrap successful generic responses in the {status,data,message,errors} envelope."""

    def finalize_response(self, request, response, *args, **kwargs):
        data = getattr(response, "data", None)
        if response.status_code < 400 and not _is_envelope(data):
            response.data = {"status": "success", "data": data, "message": "", "errors": None}
        return super().finalize_response(request, response, *args, **kwargs)


class TenantActivationMixin:
    """Activate tenant scoping from the DRF-authenticated user.

    CurrentInstitutionMiddleware runs before DRF resolves the JWT user, so the
    institution is set here (after authentication) so query scoping applies.
    """

    model = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_current_institution(getattr(request.user, "institution", None))

    def get_queryset(self):
        return self.model._default_manager.all()


class _StructuralPermissionMixin:
    """Reads for any tenant member; structural writes for school admins only."""

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsTenantMember()]
        return [IsSchoolAdmin()]


class _ProtectedDestroyMixin:
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except ProtectedError:
            return error_response(
                "This record cannot be deleted because other academic records depend on it.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_200_OK)


class CatalogListCreateView(
    TenantActivationMixin, EnvelopeMixin, _StructuralPermissionMixin, generics.ListCreateAPIView
):
    pass


class CatalogDetailView(
    TenantActivationMixin,
    EnvelopeMixin,
    _StructuralPermissionMixin,
    _ProtectedDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    pass


class FacultyListCreateView(CatalogListCreateView):
    model = Faculty
    serializer_class = FacultySerializer


class FacultyDetailView(CatalogDetailView):
    model = Faculty
    serializer_class = FacultySerializer


class DepartmentListCreateView(CatalogListCreateView):
    model = Department
    serializer_class = DepartmentSerializer


class DepartmentDetailView(CatalogDetailView):
    model = Department
    serializer_class = DepartmentSerializer


class ProgrammeListCreateView(CatalogListCreateView):
    model = Programme
    serializer_class = ProgrammeSerializer


class ProgrammeDetailView(CatalogDetailView):
    model = Programme
    serializer_class = ProgrammeSerializer


class SessionListCreateView(CatalogListCreateView):
    model = Session
    serializer_class = SessionSerializer


class SessionDetailView(CatalogDetailView):
    model = Session
    serializer_class = SessionSerializer


class SemesterListCreateView(CatalogListCreateView):
    model = Semester
    serializer_class = SemesterSerializer


class SemesterDetailView(CatalogDetailView):
    model = Semester
    serializer_class = SemesterSerializer


class CourseListCreateView(CatalogListCreateView):
    model = Course
    serializer_class = CourseSerializer


class CourseDetailView(CatalogDetailView):
    model = Course
    serializer_class = CourseSerializer


class EnrolmentListCreateView(TenantActivationMixin, EnvelopeMixin, generics.ListCreateAPIView):
    model = Enrolment
    serializer_class = EnrolmentSerializer
    permission_classes = [IsSchoolAdmin]

    def perform_create(self, serializer):
        serializer.instance = enrol_student(**serializer.validated_data)


class EnrolmentDetailView(
    TenantActivationMixin, EnvelopeMixin, _ProtectedDestroyMixin, generics.RetrieveDestroyAPIView
):
    model = Enrolment
    serializer_class = EnrolmentSerializer
    permission_classes = [IsSchoolAdmin]


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Invalid request.", serializer.errors)

        user = User.objects.filter(email=serializer.validated_data["email"]).first()
        if user is not None:
            token = tokens.make_password_reset_token(user)
            send_password_reset_email.delay(user.email, token)
        return success_response(
            message="If an account exists for that email, a reset link has been sent."
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Invalid request.", serializer.errors)

        try:
            uid = tokens.read_password_reset_token(serializer.validated_data["token"])
        except signing.SignatureExpired:
            return error_response("Reset link has expired.")
        except signing.BadSignature:
            return error_response("Invalid reset link.")

        user = User.objects.filter(pk=uid).first()
        if user is None:
            return error_response("Invalid reset link.")

        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password", "updated_at"])
        return success_response(message="Password has been reset. You can now log in.")
