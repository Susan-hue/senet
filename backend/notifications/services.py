"""Dispatch and registration services.

Nothing here sends anything. A trigger calls one of the ``notify_*`` helpers,
which writes the log rows and hands each one to Celery on transaction commit —
so a request never waits on a provider, and a rolled-back transition never
produces a message about a change that did not happen.
"""

import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Role
from notifications.messages import render
from notifications.models import (
    Notification,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
    ResultCheckRegistration,
)

logger = logging.getLogger(__name__)

# Which channels each event may use. WhatsApp additionally depends on
# NOTIFICATIONS_WHATSAPP_ENABLED, so a tenant can run without it.
EVENT_CHANNELS = {
    NotificationEvent.RESULT_RETURNED: (NotificationChannel.EMAIL, NotificationChannel.SMS),
    NotificationEvent.RESULT_PUBLISHED: (
        NotificationChannel.EMAIL,
        NotificationChannel.SMS,
        NotificationChannel.WHATSAPP,
    ),
    NotificationEvent.EXAM_SCHEDULED: (
        NotificationChannel.EMAIL,
        NotificationChannel.SMS,
        NotificationChannel.WHATSAPP,
    ),
    NotificationEvent.EXAM_OPENED: (NotificationChannel.SMS,),
    NotificationEvent.CHEATING_FLAG_RAISED: (NotificationChannel.EMAIL,),
    NotificationEvent.CHEATING_FLAG_ESCALATED: (NotificationChannel.EMAIL,),
    NotificationEvent.RESULT_CHECK_OTP: (NotificationChannel.SMS,),
    NotificationEvent.RESULT_CHECK_REPLY: (NotificationChannel.SMS,),
}

_DIGITS = re.compile(r"\D+")


# --------------------------------------------------------------------------- #
# Phone numbers                                                                #
# --------------------------------------------------------------------------- #


def normalize_msisdn(raw):
    """Nigerian dialling habits ('0803…', '234803…', '+234 803 …') to one E.164
    string, so the number a student registers matches the number an inbound
    message arrives from. Returns None if it cannot be read as a number."""
    if not raw:
        return None
    digits = _DIGITS.sub("", str(raw))
    if not digits:
        return None
    country = settings.SMS_DEFAULT_COUNTRY_CODE
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = country + digits[1:]
    elif not digits.startswith(country) and len(digits) <= 10:
        digits = country + digits
    if not 10 <= len(digits) <= 15:
        return None
    return f"+{digits}"


# --------------------------------------------------------------------------- #
# Dispatch                                                                     #
# --------------------------------------------------------------------------- #


def _channel_enabled(channel):
    if channel == NotificationChannel.WHATSAPP:
        return settings.NOTIFICATIONS_WHATSAPP_ENABLED
    return True


def _phone_for(user):
    """A staff member's own number, or a student's verified result-check
    binding. An unverified binding is never texted."""
    number = normalize_msisdn(getattr(user, "phone_number", ""))
    if number:
        return number
    registration = ResultCheckRegistration.all_objects.filter(
        student_id=user.id, is_verified=True
    ).first()
    return registration.msisdn if registration else None


def _address_for(user, channel):
    if channel == NotificationChannel.EMAIL:
        return user.email or None
    return _phone_for(user)


def _enqueue(notification):
    """Hand the row to Celery once the trigger's transaction commits.

    A broker outage is recorded on the row and logged rather than raised: this
    runs in an ``on_commit`` callback of a request that has already committed
    its academic change, so an exception here would turn a successful
    transition into a 500 and leave the row QUEUED for a delivery that was
    never scheduled.
    """

    def _send():
        from notifications.tasks import send_notification

        try:
            send_notification.delay(str(notification.id))
        except OperationalError as exc:
            logger.exception("Could not queue notification %s", notification.id)
            notification.mark_attempt_failed(provider="broker", error=exc, final=True)

    transaction.on_commit(_send)


def queue_notification(
    *, institution, event, channel, address, context, recipient=None, dedupe_key=""
):
    """Write one log row and hand it to Celery on commit. A duplicate
    ``dedupe_key`` is a no-op, which is what makes the periodic sweeps safe."""
    if not address or not _channel_enabled(channel):
        return None
    if (
        dedupe_key
        and Notification.all_objects.filter(institution=institution, dedupe_key=dedupe_key).exists()
    ):
        return None

    subject, body = render(event, channel, context)
    notification = Notification.all_objects.create(
        institution=institution,
        event=event,
        channel=channel,
        recipient=recipient,
        recipient_address=address[:254],
        subject=subject,
        body=body,
        status=NotificationStatus.QUEUED,
        dedupe_key=dedupe_key,
    )
    _enqueue(notification)
    return notification


def notify_users(*, institution, event, users, context, dedupe_prefix=""):
    """Fan an event out to people, on every channel the event allows and the
    recipient can actually be reached on."""
    queued = []
    for user in users:
        if user is None or user.institution_id != institution.id:
            continue
        for channel in EVENT_CHANNELS.get(event, ()):
            dedupe_key = f"{dedupe_prefix}:{user.id}:{channel}" if dedupe_prefix else ""
            notification = queue_notification(
                institution=institution,
                event=event,
                channel=channel,
                address=_address_for(user, channel),
                context=context,
                recipient=user,
                dedupe_key=dedupe_key,
            )
            if notification is not None:
                queued.append(notification)
    return queued


def notify_address(*, institution, event, channel, address, context, recipient=None):
    """Send to a bare address — used for the SMS reply path, where the recipient
    is a phone number rather than a signed-in user."""
    return queue_notification(
        institution=institution,
        event=event,
        channel=channel,
        address=address,
        context=context,
        recipient=recipient,
    )


def visible_notifications(user):
    """A school admin sees the tenant's log; everyone else sees their own."""
    qs = Notification.objects.all()
    if getattr(user, "role", None) == Role.SCHOOL_ADMIN:
        return qs
    return qs.filter(recipient=user)


# --------------------------------------------------------------------------- #
# Result-check registration                                                    #
# --------------------------------------------------------------------------- #

_STUDENT_ROLES = (Role.STUDENT, Role.COURSE_REP)


def validate_pin(pin):
    pin = (pin or "").strip()
    low = settings.RESULT_CHECK_PIN_MIN_LENGTH
    high = settings.RESULT_CHECK_PIN_MAX_LENGTH
    if not pin.isdigit() or not low <= len(pin) <= high:
        raise ValidationError({"pin": f"The PIN must be {low}–{high} digits."})
    if len(set(pin)) == 1:
        raise ValidationError({"pin": "The PIN cannot be a single repeated digit."})
    runs = "0123456789"
    if pin in runs or pin in runs[::-1]:
        raise ValidationError({"pin": "The PIN cannot be a run of consecutive digits."})
    return pin


def _generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def start_registration(*, student, msisdn, pin):
    """Bind a phone to a student, pending proof they hold the SIM.

    The binding is created unverified and a one-time code is texted to the
    number. Until that code comes back the registration cannot check a result,
    so claiming someone else's number achieves nothing.
    """
    if getattr(student, "role", None) not in _STUDENT_ROLES:
        raise PermissionDenied("Only a student can register for the SMS result check.")
    number = normalize_msisdn(msisdn)
    if number is None:
        raise ValidationError({"msisdn": "Enter a valid phone number."})
    pin = validate_pin(pin)

    taken = (
        ResultCheckRegistration.all_objects.filter(msisdn=number, is_verified=True)
        .exclude(student_id=student.id)
        .exists()
    )
    if taken:
        raise ValidationError({"msisdn": "This number is already registered to another student."})

    code = _generate_otp()
    expires_at = timezone.now() + timedelta(seconds=settings.RESULT_CHECK_OTP_TTL_SECONDS)
    registration, _created = ResultCheckRegistration.all_objects.update_or_create(
        student=student,
        defaults={
            "institution_id": student.institution_id,
            "msisdn": number,
            # Re-registering always re-proves the phone, even for the same number.
            "is_verified": False,
            "verified_at": None,
            "pin_hash": make_password(pin),
            "otp_hash": make_password(code),
            "otp_expires_at": expires_at,
            "failed_attempts": 0,
            "locked_until": None,
        },
    )
    notify_address(
        institution=student.institution,
        event=NotificationEvent.RESULT_CHECK_OTP,
        channel=NotificationChannel.SMS,
        address=number,
        context={"code": code, "ttl_minutes": settings.RESULT_CHECK_OTP_TTL_SECONDS // 60},
        recipient=student,
    )
    return registration


def confirm_registration(*, student, otp):
    """Complete the binding by presenting the texted code. Wrong codes count
    toward the same lockout the result check uses, so the code cannot be
    guessed by repetition."""
    registration = ResultCheckRegistration.all_objects.filter(student=student).first()
    if registration is None:
        raise ValidationError({"otp": "Register a phone number first."})
    if registration.is_locked:
        raise ValidationError({"otp": "Too many attempts. Try again later."})
    expired = registration.otp_expires_at is None or timezone.now() >= registration.otp_expires_at
    if not registration.otp_hash or expired:
        raise ValidationError({"otp": "This code has expired. Request a new one."})

    if not check_password((otp or "").strip(), registration.otp_hash):
        register_failure(registration)
        raise ValidationError({"otp": "That code is not correct."})

    # A number can only be verified against one student at a time.
    ResultCheckRegistration.all_objects.filter(
        msisdn=registration.msisdn, is_verified=True
    ).exclude(pk=registration.pk).update(is_verified=False, verified_at=None)

    registration.is_verified = True
    registration.verified_at = timezone.now()
    registration.otp_hash = ""
    registration.otp_expires_at = None
    registration.failed_attempts = 0
    registration.locked_until = None
    registration.save(
        update_fields=[
            "is_verified",
            "verified_at",
            "otp_hash",
            "otp_expires_at",
            "failed_attempts",
            "locked_until",
            "updated_at",
        ]
    )
    return registration


def register_failure(registration):
    """Count a failed verification and lock the registration once there have
    been too many. Shared by the OTP step and the SMS/USSD result check."""
    registration.failed_attempts += 1
    fields = ["failed_attempts", "updated_at"]
    if registration.failed_attempts >= settings.RESULT_CHECK_MAX_FAILURES:
        registration.locked_until = timezone.now() + timedelta(
            seconds=settings.RESULT_CHECK_LOCKOUT_SECONDS
        )
        registration.failed_attempts = 0
        fields.append("locked_until")
    registration.save(update_fields=fields)
    return registration


def clear_failures(registration):
    registration.failed_attempts = 0
    registration.locked_until = None
    registration.last_checked_at = timezone.now()
    registration.save(
        update_fields=["failed_attempts", "locked_until", "last_checked_at", "updated_at"]
    )


def unregister(*, student):
    ResultCheckRegistration.all_objects.filter(student=student).delete()
