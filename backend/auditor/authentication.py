"""Token authentication for the read-only auditor path.

The auditor is *not* a Django user. Authentication resolves the presented token
to an ``AuditorPrincipal`` — an object with no role and no database identity —
so none of the role-gated pipeline endpoints or write services will ever accept
it. The institution is taken from the token, never from a logged-in user, which
is what keeps the path tenant-isolated.
"""

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from auditor.models import AuditorToken, hash_token
from tenancy.scoping import set_current_institution

# The WSGI META key for the X-Auditor-Token request header — a header name, not
# a secret (bandit B105 false positive).
AUDITOR_TOKEN_HEADER = "HTTP_X_AUDITOR_TOKEN"  # nosec B105
AUTHORIZATION_KEYWORD = "Auditor"


class AuditorPrincipal:
    """A read-only, role-less request principal backed by an AuditorToken."""

    # DRF treats the request as authenticated, but this object is not a User and
    # carries no role, so every role-based permission in the app rejects it.
    is_authenticated = True
    is_anonymous = False
    is_active = True
    is_staff = False
    role = None
    pk = None
    id = None

    def __init__(self, token):
        self.token = token
        self.institution = token.institution
        self.institution_id = token.institution_id

    def __str__(self):
        return f"auditor:{self.token_id}"

    @property
    def token_id(self):
        return self.token.id


def _extract_raw_token(request):
    raw = request.META.get(AUDITOR_TOKEN_HEADER)
    if raw:
        return raw.strip()
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) == 2 and parts[0] == AUTHORIZATION_KEYWORD:
        return parts[1].strip()
    return None


class AuditorTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        raw = _extract_raw_token(request)
        if not raw:
            return None

        token = (
            AuditorToken.all_objects.select_related("institution")
            .filter(token_hash=hash_token(raw))
            .first()
        )
        if token is None:
            raise AuthenticationFailed("Invalid auditor token.")
        if not token.is_valid:
            raise AuthenticationFailed("This auditor token has expired or been revoked.")

        # The tenant is fixed by the token; all downstream reads are scoped to it.
        set_current_institution(token.institution)
        AuditorToken.all_objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return (AuditorPrincipal(token), token)

    def authenticate_header(self, request):
        return AUTHORIZATION_KEYWORD
