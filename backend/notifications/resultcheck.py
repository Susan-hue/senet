"""SMS/USSD result check.

A student with no data can text or dial for their GPA. SMS is an open channel:
anyone can send anything from any handset, and a matric number is not a secret —
it is printed on class lists and known to every course rep. So the matric number
is never the thing that identifies the requester.

How a request is authorised, in order:

1. **The sender's phone number identifies the student.** We look up the verified
   ``ResultCheckRegistration`` bound to the number the message came from. That
   binding only exists because the student created it while signed in to the
   portal and typed back a one-time code we texted to that SIM. A stranger texting
   from their own handset resolves to nothing, whatever matric they type.
2. **The matric number must match that student's own.** It confirms the sender is
   the account holder rather than someone who picked up their phone, and it is
   checked against the student we already resolved — never used to search.
3. **The PIN must match.** A secret the student set in the portal, stored only as
   a hash, so a borrowed or stolen handset is not enough.

Then the reply itself is constrained: only score rows on sheets **ratified by
Senate** are ever read, with that state written here as a literal rather than
taken from tenant configuration. Nothing in draft, submitted, HOD/Dean-approved
or returned state can reach this channel by any configuration mistake.

Failures reply with one generic message, so the channel cannot be used to learn
whether a matric exists or a PIN was close. Repeated failures lock the
registration, and every number is rate-limited.
"""

import hashlib
import hmac
import logging

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.cache import cache

from grading.services import classify, cumulative_summary, official_rows, term_summary
from notifications.models import (
    NotificationChannel,
    NotificationEvent,
    ResultCheckRegistration,
)
from notifications.services import (
    clear_failures,
    normalize_msisdn,
    notify_address,
    register_failure,
)
from results.models import ResultStatus
from tenancy.scoping import set_current_institution

logger = logging.getLogger(__name__)

# The only result state this channel may ever read. Deliberately a literal and
# not ``institution.gpa_source_status``: a tenant misconfiguring that setting
# must not be able to widen what an unauthenticated SMS can see.
PUBLISHED_STATUS = ResultStatus.RATIFIED_BY_SENATE

GENERIC_DENIAL = "We could not verify this request. Check your matric number and PIN and try again."
NOT_REGISTERED = (
    "This number is not registered for result checking. Sign in to the Senet portal to register it."
)
LOCKED = "Too many failed attempts. Please try again later."
RATE_LIMITED = "You have made too many requests. Please wait a minute and try again."
NO_RESULTS = "You have no published results yet. Results appear here once Senate ratifies them."

RESULT_KEYWORD = "RESULT"


class ResultCheckDenied(Exception):
    """A request that will not be answered with any result data. ``reply`` is the
    deliberately uninformative text sent back."""

    def __init__(self, reply):
        super().__init__(reply)
        self.reply = reply


# --------------------------------------------------------------------------- #
# Rate limiting and caching                                                    #
# --------------------------------------------------------------------------- #


def _rate_key(msisdn):
    return f"resultcheck:rate:{msisdn}"


def _summary_key(student_id):
    return f"resultcheck:summary:{student_id}"


def enforce_rate_limit(msisdn):
    """Per-number sliding counter. Deliberately keyed on the sender rather than
    the source IP: on results day every message in the country arrives from the
    provider's gateway, so an IP counter would throttle a whole campus. One
    student cannot text faster than this; a campus is unaffected."""
    key = _rate_key(msisdn)
    window = settings.RESULT_CHECK_RATE_WINDOW_SECONDS
    cache.get_or_set(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        # The window expired between the two calls; this request starts a new one.
        cache.set(key, 1, window)
        count = 1
    if count > settings.RESULT_CHECK_RATE_LIMIT:
        raise ResultCheckDenied(RATE_LIMITED)


def invalidate_summary(student_id):
    cache.delete(_summary_key(str(student_id)))


# --------------------------------------------------------------------------- #
# The published-results read                                                   #
# --------------------------------------------------------------------------- #


def published_summary(student):
    """GPA/CGPA and the latest term's courses, built only from Senate-ratified
    sheets. Cached briefly: results day is one spike of identical lookups, and a
    few minutes of staleness on an already-published result is harmless."""
    key = _summary_key(str(student.id))
    cached = cache.get(key)
    if cached is not None:
        return cached

    rows = list(official_rows(student, status=PUBLISHED_STATUS))
    if not rows:
        summary = None
    else:
        latest = rows[-1].result
        cumulative = cumulative_summary(student, status=PUBLISHED_STATUS)
        term = term_summary(student, latest.session, latest.semester, status=PUBLISHED_STATUS)
        summary = {
            "session": latest.session.name,
            "semester": latest.semester.name,
            "gpa": str(term["gpa"]) if term["gpa"] is not None else None,
            "cgpa": str(cumulative["cgpa"]) if cumulative["cgpa"] is not None else None,
            "credit_units": term["credit_units"],
            "classification": classify(student.institution, cumulative["cgpa"])["name"],
            "courses": [
                {"code": line["course_code"], "grade": line["grade"]} for line in term["courses"]
            ],
        }
    cache.set(key, summary, settings.RESULT_CHECK_CACHE_SECONDS)
    return summary


def format_summary(student, summary):
    if summary is None:
        return NO_RESULTS
    courses = ", ".join(f"{line['code']} {line['grade']}" for line in summary["courses"])
    parts = [
        f"{student.full_name}",
        f"{summary['session']} {summary['semester']}",
        f"GPA {summary['gpa'] or '-'} | CGPA {summary['cgpa'] or '-'}",
    ]
    if courses:
        parts.append(courses)
    if summary["classification"]:
        parts.append(f"Class: {summary['classification']}")
    parts.append("Senate-ratified results only.")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Verification                                                                 #
# --------------------------------------------------------------------------- #


def _matric_matches(student, supplied):
    """Case- and space-insensitive, constant-time comparison of the student's own
    matric number with the one supplied."""
    stored = (student.identifier or "").strip().upper().replace(" ", "")
    given = (supplied or "").strip().upper().replace(" ", "")
    if not stored or not given:
        return False
    return hmac.compare_digest(stored, given)


def authorise(*, msisdn, matric, pin):
    """Resolve and authorise a request, or raise ResultCheckDenied.

    Returns the verified registration. The institution is taken from the binding
    and activated for tenant scoping, so every read that follows is confined to
    the student's own tenant.
    """
    number = normalize_msisdn(msisdn)
    if number is None:
        raise ResultCheckDenied(GENERIC_DENIAL)
    enforce_rate_limit(number)

    registration = (
        ResultCheckRegistration.all_objects.select_related("student__institution")
        .filter(msisdn=number, is_verified=True)
        .first()
    )
    if registration is None:
        # Safe to be specific: this only tells the sender about their own number.
        raise ResultCheckDenied(NOT_REGISTERED)
    if registration.is_locked:
        raise ResultCheckDenied(LOCKED)

    # The tenant follows from the binding, never from anything in the message.
    set_current_institution(registration.institution)

    student = registration.student
    matric_ok = _matric_matches(student, matric)
    pin_ok = check_password((pin or "").strip(), registration.pin_hash)
    # Both checks always run, and one message covers both failures, so the reply
    # never reveals which half was wrong or whether a matric exists.
    if not (matric_ok and pin_ok):
        register_failure(registration)
        logger.info("Result check denied for %s", registration.masked_msisdn)
        raise ResultCheckDenied(GENERIC_DENIAL)

    clear_failures(registration)
    return registration


def check_result(*, msisdn, matric, pin):
    """Full request: authorise, then render the published summary. Returns the
    reply text. Never raises for a denied request — the denial *is* the reply."""
    try:
        registration = authorise(msisdn=msisdn, matric=matric, pin=pin)
    except ResultCheckDenied as denied:
        return denied.reply
    student = registration.student
    return format_summary(student, published_summary(student))


def reply_by_sms(*, msisdn, text, institution):
    """Queue the reply. Sending is asynchronous like every other notification, so
    the provider's webhook gets its 200 immediately.

    An unrecognised number gets no reply at all. Every notification belongs to a
    tenant — that is the invariant the whole platform rests on — and a number
    with no verified binding belongs to none of them. Staying silent also means
    an unsolicited text costs no institution money and confirms nothing to
    whoever sent it.
    """
    number = normalize_msisdn(msisdn)
    if number is None or institution is None:
        return None
    return notify_address(
        institution=institution,
        event=NotificationEvent.RESULT_CHECK_REPLY,
        channel=NotificationChannel.SMS,
        address=number,
        context={"text": text},
    )


# --------------------------------------------------------------------------- #
# Inbound SMS                                                                  #
# --------------------------------------------------------------------------- #


def parse_sms_command(text):
    """``RESULT <matric> <pin>`` — the keyword is optional so a student who just
    texts their matric and PIN still gets through. Returns (matric, pin)."""
    parts = (text or "").strip().split()
    if parts and parts[0].upper() == RESULT_KEYWORD:
        parts = parts[1:]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


def handle_inbound_sms(*, msisdn, text):
    """Answer one inbound SMS. Returns the reply text that was queued."""
    matric, pin = parse_sms_command(text)
    if matric is None:
        reply = (
            f"To check your result, text: {RESULT_KEYWORD} <matric number> <PIN>. "
            "Register your phone in the Senet portal first."
        )
    else:
        reply = check_result(msisdn=msisdn, matric=matric, pin=pin)
    institution = _institution_for(msisdn)
    reply_by_sms(msisdn=msisdn, text=reply, institution=institution)
    return reply


def _institution_for(msisdn):
    """The tenant an inbound message belongs to, resolved only through a verified
    binding. Unknown numbers have no tenant, and their reply is not logged
    against one."""
    number = normalize_msisdn(msisdn)
    if number is None:
        return None
    registration = (
        ResultCheckRegistration.all_objects.select_related("institution")
        .filter(msisdn=number, is_verified=True)
        .first()
    )
    return registration.institution if registration else None


# --------------------------------------------------------------------------- #
# USSD                                                                         #
# --------------------------------------------------------------------------- #

ASK_MATRIC = "ask_matric"
ASK_PIN = "ask_pin"

USSD_PROMPT_MATRIC = "Senet Result Check\nEnter your matric number:"
USSD_PROMPT_PIN = "Enter your result-check PIN:"


def _ussd_key(session_id):
    return f"resultcheck:ussd:{session_id}"


def handle_ussd(*, session_id, msisdn, text):
    """One step of a USSD session. Returns (message, is_final).

    The dialogue only collects input; the same ``check_result`` authorisation
    runs at the end, so USSD is no more trusted than SMS. Session state lives in
    the cache with a short TTL and never holds the PIN.
    """
    key = _ussd_key(session_id)
    state = cache.get(key) or {"step": ASK_MATRIC}
    entry = (text or "").strip()

    if state["step"] == ASK_MATRIC:
        if not entry:
            cache.set(key, {"step": ASK_MATRIC}, settings.USSD_SESSION_TTL_SECONDS)
            return USSD_PROMPT_MATRIC, False
        cache.set(key, {"step": ASK_PIN, "matric": entry}, settings.USSD_SESSION_TTL_SECONDS)
        return USSD_PROMPT_PIN, False

    if state["step"] == ASK_PIN:
        cache.delete(key)
        if not entry:
            return GENERIC_DENIAL, True
        return check_result(msisdn=msisdn, matric=state.get("matric"), pin=entry), True

    cache.delete(key)
    return USSD_PROMPT_MATRIC, False


# --------------------------------------------------------------------------- #
# Webhook authentication                                                       #
# --------------------------------------------------------------------------- #


def verify_webhook_signature(*, raw_body, signature):
    """HMAC-SHA256 of the raw request body under the shared inbound secret.

    Fails closed: with no ``TERMII_INBOUND_SECRET`` configured, nothing is
    accepted. An inbound endpoint that trusts an unsigned caller would let anyone
    on the internet impersonate the SMS gateway.
    """
    secret = settings.TERMII_INBOUND_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())
