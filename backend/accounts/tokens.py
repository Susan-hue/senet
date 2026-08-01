import hashlib
import hmac

from django.conf import settings
from django.core import signing

EMAIL_VERIFICATION_SALT = "accounts.email-verification"
PASSWORD_RESET_SALT = "accounts.password-reset"  # nosec B105


def make_email_verification_token(user):
    return signing.dumps({"uid": str(user.pk)}, salt=EMAIL_VERIFICATION_SALT)


def read_email_verification_token(token):
    data = signing.loads(
        token, salt=EMAIL_VERIFICATION_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE
    )
    return data["uid"]


def password_fingerprint(user):
    """Digest of the stored password hash.

    Carried inside a reset token and re-checked when the token is used, so a link
    stops working the moment the password changes. That makes a reset link
    single-use and retires every link still sitting in a mailbox — a signature
    plus an expiry alone would let the same link be replayed for its whole
    lifetime, including by anyone who reads the message later.
    """
    return hashlib.sha256(user.password.encode()).hexdigest()


def password_fingerprint_matches(user, fingerprint):
    return hmac.compare_digest(password_fingerprint(user), fingerprint or "")


def make_password_reset_token(user):
    return signing.dumps(
        {"uid": str(user.pk), "pw": password_fingerprint(user)}, salt=PASSWORD_RESET_SALT
    )


def read_password_reset_token(token):
    """Returns ``(uid, fingerprint)``. The caller checks the fingerprint against
    the user it resolves, which is what keeps the link single-use."""
    data = signing.loads(token, salt=PASSWORD_RESET_SALT, max_age=settings.PASSWORD_RESET_MAX_AGE)
    return data["uid"], data.get("pw", "")
