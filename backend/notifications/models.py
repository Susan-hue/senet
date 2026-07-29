"""Notification log and the SMS/USSD result-check registration.

Two things live here. ``Notification`` is the append-only delivery log: what was
sent, to whom, on which channel, and how it ended up. ``ResultCheckRegistration``
is the binding that makes the SMS/USSD result check safe — a phone number proven
to belong to a student, plus the PIN they must present to read anything.
"""

from django.db import models
from django.utils import timezone

from accounts.models import AcademicBase, Role, User


class AppendOnlyError(Exception):
    """Raised when code attempts to rewrite the notification log."""


class NotificationChannel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"


class NotificationStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class NotificationEvent(models.TextChoices):
    RESULT_RETURNED = "result_returned", "Result returned to lecturer"
    RESULT_PUBLISHED = "result_published", "Results published (ratified)"
    EXAM_SCHEDULED = "exam_scheduled", "Exam scheduled"
    EXAM_OPENED = "exam_opened", "Exam open for sitting"
    CHEATING_FLAG_RAISED = "cheating_flag_raised", "Integrity flag raised"
    CHEATING_FLAG_ESCALATED = "cheating_flag_escalated", "Integrity flag escalated"
    RESULT_CHECK_OTP = "result_check_otp", "Result-check phone verification code"
    RESULT_CHECK_REPLY = "result_check_reply", "Result-check reply"


class Notification(AcademicBase):
    """One message to one recipient on one channel.

    Append-only: what was sent (event, channel, recipient, subject, body) is
    frozen at creation. Only the delivery state — status, attempt count, provider
    reference, error, sent time — may change afterwards, and rows are never
    deleted. Fanning one event out to several people creates several rows so each
    delivery carries its own status.
    """

    # The only fields a later write may touch. Anything else is history.
    DELIVERY_FIELDS = frozenset(
        {"status", "attempts", "provider", "provider_message_id", "error", "sent_at", "updated_at"}
    )

    event = models.CharField(max_length=32, choices=NotificationEvent.choices)
    channel = models.CharField(max_length=10, choices=NotificationChannel.choices)
    # Null for a recipient with no user account — an inbound SMS reply is sent
    # back to a phone number, not to a session.
    recipient = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="notifications", null=True, blank=True
    )
    recipient_address = models.CharField(max_length=254)
    subject = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()

    status = models.CharField(
        max_length=10, choices=NotificationStatus.choices, default=NotificationStatus.QUEUED
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    provider = models.CharField(max_length=40, blank=True, default="")
    provider_message_id = models.CharField(max_length=120, blank=True, default="")
    error = models.CharField(max_length=500, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    # Idempotency handle for events that a periodic sweep may re-observe (an exam
    # opening, a sheet being ratified). Empty means "no deduplication".
    dedupe_key = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["institution", "status"]),
            models.Index(fields=["recipient", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "dedupe_key"],
                condition=~models.Q(dedupe_key=""),
                name="uniq_notification_dedupe_key",
            ),
        ]

    def __str__(self):
        return f"{self.event} → {self.recipient_address} via {self.channel} ({self.status})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            update_fields = kwargs.get("update_fields")
            if update_fields is None or not set(update_fields) <= self.DELIVERY_FIELDS:
                raise AppendOnlyError(
                    "A notification's content is append-only; only delivery state may change."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Notification log entries cannot be deleted.")

    def mark_sent(self, *, provider, message_id=""):
        self.status = NotificationStatus.SENT
        self.provider = provider[:40]
        self.provider_message_id = (message_id or "")[:120]
        self.error = ""
        self.sent_at = timezone.now()
        self.attempts += 1
        self.save(
            update_fields=[
                "status",
                "provider",
                "provider_message_id",
                "error",
                "sent_at",
                "attempts",
                "updated_at",
            ]
        )

    def mark_attempt_failed(self, *, provider, error, final):
        """Record a failed send. ``final`` marks the retries exhausted, at which
        point the row settles on FAILED; until then it stays queued for retry."""
        self.status = NotificationStatus.FAILED if final else NotificationStatus.QUEUED
        self.provider = provider[:40]
        self.error = str(error)[:500]
        self.attempts += 1
        self.save(update_fields=["status", "provider", "error", "attempts", "updated_at"])


class ResultCheckRegistration(AcademicBase):
    """A student's phone binding for the SMS/USSD result check.

    The binding is what makes the channel safe. A student registers from the
    authenticated portal, proves they hold the SIM by entering a one-time code we
    text to it, and sets a PIN. From then on a result check must arrive *from that
    number* and carry both the matric number and the PIN. Only the hashes of the
    PIN and the OTP are ever stored.

    ``msisdn`` is unique across the whole table (not per tenant) once verified: an
    inbound text carries nothing but its sender, so one phone number has to
    resolve to exactly one student — and therefore exactly one institution.
    """

    student = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="result_check_registration",
        limit_choices_to={"role": Role.STUDENT},
    )
    msisdn = models.CharField(max_length=20, help_text="E.164, e.g. +2348030000000")
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    pin_hash = models.CharField(max_length=128)
    otp_hash = models.CharField(max_length=128, blank=True, default="")
    otp_expires_at = models.DateTimeField(null=True, blank=True)

    # Shared by OTP verification and result checks: enough wrong answers locks
    # the registration for a cooling-off period.
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_result_check_registration"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["msisdn"],
                condition=models.Q(is_verified=True),
                name="uniq_verified_msisdn",
            ),
        ]

    def __str__(self):
        state = "verified" if self.is_verified else "pending"
        return f"{self.student_id} → {self.masked_msisdn} ({state})"

    @property
    def masked_msisdn(self):
        """Last four digits only — what the portal is allowed to echo back."""
        if not self.msisdn:
            return ""
        return "*" * max(len(self.msisdn) - 4, 0) + self.msisdn[-4:]

    @property
    def is_locked(self):
        return self.locked_until is not None and timezone.now() < self.locked_until
