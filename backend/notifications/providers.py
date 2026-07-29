"""Sending providers behind one interface.

The rest of the app calls ``get_provider(channel).send(...)`` and never names a
vendor. Termii carries SMS and WhatsApp (Nigeria-native, one API for both);
email goes out over the existing Django/Resend path. Swapping a vendor is a
settings change, and every credential comes from the environment.

A provider only ever raises ``ProviderError``. The caller (the Celery send task)
turns that into a logged failure — a provider outage never reaches a request.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from django.utils.module_loading import import_string

from notifications.models import NotificationChannel

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Any failure talking to a sending provider."""


class NotificationProvider:
    name = "provider"

    def send(self, *, channel, to, subject, body):
        """Deliver one message. Returns the provider's message id (may be empty)
        or raises ProviderError."""
        raise NotImplementedError


class ConsoleProvider(NotificationProvider):
    """Development/CI default: records the message in the log and succeeds."""

    name = "console"

    def send(self, *, channel, to, subject, body):
        logger.info("[notifications:%s] to=%s subject=%s body=%s", channel, to, subject, body)
        return ""


class DjangoEmailProvider(NotificationProvider):
    """Email over the configured Django backend (SMTP/Resend in deployment)."""

    name = "django-email"

    def send(self, *, channel, to, subject, body):
        try:
            sent = send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001 - normalise every backend failure
            raise ProviderError(f"Email send failed: {exc}") from exc
        if not sent:
            raise ProviderError("Email backend accepted no recipients.")
        return ""


class TermiiProvider(NotificationProvider):
    """SMS and WhatsApp via Termii.

    Both channels are the same endpoint with a different ``channel`` value and
    sender id. The API key is read from settings (environment) on every send, so
    rotating it needs no code change.
    """

    name = "termii"

    # Termii's own channel names for the messaging endpoint.
    _TERMII_CHANNEL = {
        NotificationChannel.SMS: "generic",
        NotificationChannel.WHATSAPP: "whatsapp",
    }

    def __init__(self, *, api_key=None, base_url=None, timeout=None):
        self.api_key = settings.TERMII_API_KEY if api_key is None else api_key
        self.base_url = (settings.TERMII_BASE_URL if base_url is None else base_url).rstrip("/")
        self.timeout = settings.TERMII_TIMEOUT_SECONDS if timeout is None else timeout

    def _sender_id(self, channel):
        if channel == NotificationChannel.WHATSAPP:
            return settings.TERMII_WHATSAPP_SENDER_ID
        return settings.TERMII_SENDER_ID

    def send(self, *, channel, to, subject, body):
        termii_channel = self._TERMII_CHANNEL.get(channel)
        if termii_channel is None:
            raise ProviderError(f"Termii does not carry the '{channel}' channel.")
        if not self.api_key:
            raise ProviderError("SMS/WhatsApp sending is not configured.")
        if not self.base_url.startswith("https://"):
            raise ProviderError("The Termii base URL must be https.")

        payload = json.dumps(
            {
                "to": to,
                "from": self._sender_id(channel),
                "sms": body,
                "type": "plain",
                "channel": termii_channel,
                "api_key": self.api_key,
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - scheme checked https above
            f"{self.base_url}/api/sms/send",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Termii returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Could not reach Termii: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderError("Termii timed out.") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError("Termii returned a malformed response.") from exc
        if isinstance(data, dict) and data.get("code") not in (None, "ok"):
            raise ProviderError(f"Termii rejected the message: {data.get('message', 'unknown')}")
        return str(data.get("message_id", "")) if isinstance(data, dict) else ""


def get_provider(channel):
    """Resolve the configured provider for a channel. Unknown channels and bad
    import paths surface as ProviderError so the send task logs them like any
    other delivery failure."""
    path = settings.NOTIFICATION_PROVIDERS.get(str(channel))
    if not path:
        raise ProviderError(f"No provider configured for the '{channel}' channel.")
    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise ProviderError(f"Could not load the '{channel}' provider: {exc}") from exc
    return provider_class()
