"""Branded transactional email.

Every link in here is built from ``settings.FRONTEND_URL`` and never from the
incoming request. A link derived from the request host is both wrong (the API
and the app are different origins in this deployment) and a host-header
injection risk — an attacker who can set ``Host`` would otherwise receive
password-reset links pointed at their own domain.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def frontend_url(path, **params):
    """Absolute URL into the deployed frontend.

    ``FRONTEND_URL`` is normalised for a trailing slash so a misconfigured
    secret cannot produce a double-slashed link that some mail clients mangle.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    query = f"?{urlencode(params)}" if params else ""
    return f"{base}/{path.lstrip('/')}{query}"


def send_branded_email(*, to, subject, template, context):
    """Send the HTML template with its plain-text twin attached.

    Both parts are always sent: text-only clients need it, and a multipart
    message scores better with spam filters than HTML alone.
    """
    body = render_to_string(f"emails/{template}.txt", context)
    html = render_to_string(f"emails/{template}.html", context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    message.attach_alternative(html, "text/html")
    message.send()
