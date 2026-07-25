"""NUC Auditor Vault: temporary, revocable, scope-limited read-only access.

A ``school_admin`` mints an ``AuditorToken`` scoped to some programmes and/or
sessions with an expiry. An external NUC auditor presents the raw token on the
read-only auditor endpoints; we only ever store its hash. Every access is
appended to ``AuditorAccessLog``.
"""

import hashlib
import secrets

from django.db import models
from django.utils import timezone

from accounts.models import AcademicBase, User

RAW_TOKEN_BYTES = 32


def generate_raw_token():
    return secrets.token_urlsafe(RAW_TOKEN_BYTES)


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class AuditorToken(AcademicBase):
    label = models.CharField(max_length=200)
    # Only the hash is stored; the raw token is shown once at creation.
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    # Scope: an empty side means "unrestricted on that dimension". Creation
    # requires at least one programme or session, so a token is never wide open.
    programmes = models.ManyToManyField(
        "accounts.Programme", blank=True, related_name="auditor_tokens"
    )
    sessions = models.ManyToManyField("accounts.Session", blank=True, related_name="auditor_tokens")

    class Meta:
        db_table = "auditor_token"
        ordering = ["-created_at"]

    def __str__(self):
        return f"AuditorToken({self.label}) for {self.institution_id}"

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_valid(self):
        return not self.is_revoked and not self.is_expired


class AuditorAccessLog(AcademicBase):
    """Append-only trail of every request served on the auditor path."""

    token = models.ForeignKey(AuditorToken, on_delete=models.PROTECT, related_name="access_logs")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    resource = models.CharField(max_length=64)
    detail = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "auditor_access_log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.method} {self.path} via {self.token_id}"
