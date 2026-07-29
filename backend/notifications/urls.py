from django.urls import path

from notifications.views import (
    ConfirmRegistrationView,
    InboundSmsView,
    InboundUssdView,
    NotificationListView,
    ResultCheckRegistrationView,
)

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path(
        "result-check/registration",
        ResultCheckRegistrationView.as_view(),
        name="result-check-registration",
    ),
    path(
        "result-check/registration/verify",
        ConfirmRegistrationView.as_view(),
        name="result-check-verify",
    ),
    # Gateway-facing. Signed with the shared inbound secret, never authenticated
    # as a user.
    path("inbound/sms", InboundSmsView.as_view(), name="notification-inbound-sms"),
    path("inbound/ussd", InboundUssdView.as_view(), name="notification-inbound-ussd"),
]
