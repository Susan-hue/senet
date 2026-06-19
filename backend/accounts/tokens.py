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


def make_password_reset_token(user):
    return signing.dumps({"uid": str(user.pk)}, salt=PASSWORD_RESET_SALT)


def read_password_reset_token(token):
    data = signing.loads(token, salt=PASSWORD_RESET_SALT, max_age=settings.PASSWORD_RESET_MAX_AGE)
    return data["uid"]
