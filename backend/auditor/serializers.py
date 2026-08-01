from rest_framework import serializers

from accounts.models import Programme, Session
from auditor.models import AuditorToken
from tenancy.serializers import TenantScopedSerializerMixin


class AuditorTokenSerializer(serializers.ModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_revoked = serializers.BooleanField(read_only=True)
    programmes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    sessions = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = AuditorToken
        fields = [
            "id",
            "label",
            "created_by",
            "expires_at",
            "revoked_at",
            "last_used_at",
            "is_valid",
            "is_expired",
            "is_revoked",
            "programmes",
            "sessions",
            "created_at",
        ]
        read_only_fields = fields


class CreateAuditorTokenSerializer(TenantScopedSerializerMixin, serializers.Serializer):
    tenant_scoped_fields = {"programmes": Programme, "sessions": Session}

    label = serializers.CharField(max_length=200)
    expires_at = serializers.DateTimeField()
    programmes = serializers.PrimaryKeyRelatedField(
        queryset=Programme.objects.none(), many=True, required=False, default=list
    )
    sessions = serializers.PrimaryKeyRelatedField(
        queryset=Session.objects.none(), many=True, required=False, default=list
    )
