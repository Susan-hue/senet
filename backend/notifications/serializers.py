from rest_framework import serializers

from notifications.models import Notification, ResultCheckRegistration


class NotificationSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(source="recipient.full_name", default="", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "event",
            "channel",
            "recipient",
            "recipient_name",
            "recipient_address",
            "subject",
            "status",
            "attempts",
            "provider",
            "error",
            "sent_at",
            "created_at",
        ]
        read_only_fields = fields


class ResultCheckRegistrationSerializer(serializers.ModelSerializer):
    """Never echoes the full number back — the portal only needs to confirm which
    phone is bound, and the log/UI should not be a place to read one off."""

    msisdn = serializers.CharField(source="masked_msisdn", read_only=True)

    class Meta:
        model = ResultCheckRegistration
        fields = ["id", "msisdn", "is_verified", "verified_at", "last_checked_at", "created_at"]
        read_only_fields = fields


class StartRegistrationSerializer(serializers.Serializer):
    msisdn = serializers.CharField(max_length=20)
    pin = serializers.CharField(max_length=16, write_only=True, trim_whitespace=True)


class ConfirmRegistrationSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=10, write_only=True, trim_whitespace=True)


class InboundSmsSerializer(serializers.Serializer):
    """Termii's inbound SMS shape. ``msisdn``/``from`` and ``text``/``message``
    both appear in their docs, so accept either spelling."""

    msisdn = serializers.CharField(max_length=32, required=False, allow_blank=True)
    text = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def to_internal_value(self, data):
        merged = {
            "msisdn": data.get("msisdn") or data.get("from") or data.get("sender") or "",
            "text": data.get("text") or data.get("message") or data.get("sms") or "",
        }
        return super().to_internal_value(merged)


class UssdSerializer(serializers.Serializer):
    session_id = serializers.CharField(max_length=120)
    msisdn = serializers.CharField(max_length=32)
    text = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def to_internal_value(self, data):
        merged = {
            "session_id": data.get("session_id") or data.get("sessionId") or "",
            "msisdn": data.get("msisdn") or data.get("from") or "",
            "text": data.get("text") or data.get("input") or "",
        }
        return super().to_internal_value(merged)
