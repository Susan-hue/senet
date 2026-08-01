"""Notification endpoints.

Two very different surfaces live here. The registration and log endpoints are
ordinary authenticated, tenant-scoped API views. The two inbound webhooks are
public by necessity — an SMS gateway cannot hold a JWT — so they authenticate the
*caller* by HMAC signature over the raw body and authenticate the *requester*
inside ``resultcheck``, which is where the real access decision lives.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.pagination import paginated_response
from accounts.responses import error_response, success_response
from notifications import resultcheck, services
from notifications.models import ResultCheckRegistration
from notifications.permissions import CanViewNotifications, IsStudentMember
from notifications.serializers import (
    ConfirmRegistrationSerializer,
    InboundSmsSerializer,
    NotificationSerializer,
    ResultCheckRegistrationSerializer,
    StartRegistrationSerializer,
    UssdSerializer,
)
from tenancy.views import TenantAPIView


class NotificationListView(TenantAPIView):
    permission_classes = [CanViewNotifications]

    def get(self, request):
        qs = services.visible_notifications(request.user)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return paginated_response(request, self, qs, NotificationSerializer)


class ResultCheckRegistrationView(TenantAPIView):
    """Register / inspect / remove the phone binding used by the SMS check."""

    permission_classes = [IsStudentMember]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "result_check_otp"

    def get_throttles(self):
        # Only the OTP-sending POST is throttled; reading your own status is not.
        if self.request.method == "POST":
            return super().get_throttles()
        return []

    def get(self, request):
        registration = ResultCheckRegistration.all_objects.filter(student=request.user).first()
        if registration is None:
            return success_response(None, "No phone number registered.")
        return success_response(ResultCheckRegistrationSerializer(registration).data)

    def post(self, request):
        serializer = StartRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not start registration.", serializer.errors)
        registration = services.start_registration(
            student=request.user, **serializer.validated_data
        )
        return success_response(
            ResultCheckRegistrationSerializer(registration).data,
            "Verification code sent. Enter it to finish registering.",
        )

    def delete(self, request):
        services.unregister(student=request.user)
        return success_response(None, "Result-check registration removed.")


class ConfirmRegistrationView(TenantAPIView):
    permission_classes = [IsStudentMember]

    def post(self, request):
        serializer = ConfirmRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not verify the code.", serializer.errors)
        registration = services.confirm_registration(
            student=request.user, otp=serializer.validated_data["otp"]
        )
        return success_response(
            ResultCheckRegistrationSerializer(registration).data,
            "Phone number verified. You can now check results by SMS or USSD.",
        )


class InboundWebhookView(APIView):
    """Base for the gateway-facing endpoints.

    No user, no session, no tenant from the request: the caller proves itself
    with a signature, and the tenant is derived from the verified phone binding
    deeper in. These endpoints answer 200 for anything they accept, because an
    error status makes a gateway redeliver a message we already handled.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def signature_ok(self, request):
        return resultcheck.verify_webhook_signature(
            raw_body=request.body,
            signature=request.headers.get("X-Senet-Signature", ""),
        )


class InboundSmsView(InboundWebhookView):
    def post(self, request):
        if not self.signature_ok(request):
            return error_response("Invalid signature.", http_status=403)
        serializer = InboundSmsSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Malformed inbound message.", serializer.errors)
        reply = resultcheck.handle_inbound_sms(
            msisdn=serializer.validated_data["msisdn"],
            text=serializer.validated_data["text"],
        )
        # The reply goes out as an asynchronous SMS; the body is echoed for the
        # gateway's logs and for local testing.
        return success_response({"reply": reply}, "Handled.")


class InboundUssdView(InboundWebhookView):
    def post(self, request):
        if not self.signature_ok(request):
            return error_response("Invalid signature.", http_status=403)
        serializer = UssdSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Malformed USSD request.", serializer.errors)
        message, final = resultcheck.handle_ussd(**serializer.validated_data)
        # USSD is synchronous by nature: the network holds the session open and
        # renders whatever comes back, so this one reply is returned inline.
        return Response(
            {
                "sessionId": serializer.validated_data["session_id"],
                "message": message,
                "type": "release" if final else "response",
            }
        )
