"""Per-event message copy.

One place to read every message the platform sends. Email gets the long form;
SMS and WhatsApp get a short form, because an SMS is billed per 160 characters
and read on a feature phone.
"""

from notifications.models import NotificationChannel, NotificationEvent

SHORT_CHANNELS = (NotificationChannel.SMS, NotificationChannel.WHATSAPP)


def _result_returned(context):
    course = context["course_code"]
    term = f"{context['session']} {context['semester']}"
    reason = context.get("reason") or "No reason given."
    return (
        f"Result returned for review — {course}",
        (
            f"Your result sheet for {course} ({term}) has been returned for review.\n\n"
            f"Reason: {reason}\n\n"
            "Sign in to make the corrections and resubmit."
        ),
        f"Senet: {course} ({term}) result returned for review. Reason: {reason}",
    )


def _result_published(context):
    course = context["course_code"]
    term = f"{context['session']} {context['semester']}"
    return (
        f"Results published — {course}",
        (
            f"Your result for {course} ({term}) has been ratified by Senate and is "
            "now published.\n\n"
            "Sign in to view it, or check by SMS if you have registered your phone."
        ),
        f"Senet: your {course} ({term}) result is published. Check the portal or SMS.",
    )


def _exam_scheduled(context):
    title = context["exam_title"]
    course = context["course_code"]
    opens = context["opens_at"]
    return (
        f"Exam scheduled — {course}",
        (
            f"A computer-based test has been scheduled for {course}.\n\n"
            f"Exam: {title}\n"
            f"Opens: {opens}\n"
            f"Closes: {context['closes_at']}\n"
            f"Duration: {context['duration_minutes']} minutes\n\n"
            "Be online and signed in before it opens."
        ),
        f"Senet: CBT for {course} ({title}) opens {opens}. Duration {context['duration_minutes']}min.",
    )


def _exam_opened(context):
    course = context["course_code"]
    return (
        f"Exam now open — {course}",
        (
            f"The computer-based test for {course} ({context['exam_title']}) is now open.\n\n"
            f"It closes at {context['closes_at']}. Sign in to start your attempt."
        ),
        f"Senet: {course} CBT is open now, closes {context['closes_at']}. Sign in to start.",
    )


def _cheating_flag_raised(context):
    return (
        f"[Integrity review] Flag raised — {context['exam_title']}",
        (
            "An exam attempt has been automatically flagged for integrity review.\n\n"
            f"Exam: {context['exam_title']}\n"
            f"Student: {context['student_name']}\n"
            f"Reasons: {context['reasons']}\n\n"
            "This is for review only — no score or attempt has been changed. "
            "Please review the integrity report and dismiss or escalate as appropriate."
        ),
        f"Senet: integrity flag raised on {context['exam_title']}. Review only, no score changed.",
    )


def _cheating_flag_escalated(context):
    return (
        f"[Integrity review] Flag escalated — {context['exam_title']}",
        (
            "An integrity flag has been escalated to you for review.\n\n"
            f"Exam: {context['exam_title']}\n"
            f"Student: {context['student_name']}\n"
            f"Reviewer notes: {context.get('notes') or '(none)'}\n\n"
            "This is for review only — no score or attempt has been changed."
        ),
        f"Senet: integrity flag escalated to you on {context['exam_title']}.",
    )


def _result_check_otp(context):
    code = context["code"]
    minutes = context["ttl_minutes"]
    body = (
        f"Your Senet result-check verification code is {code}. "
        f"It expires in {minutes} minutes. Do not share it with anyone."
    )
    return ("Your Senet verification code", body, body)


def _result_check_reply(context):
    body = context["text"]
    return ("Your Senet result summary", body, body)


def _announcement_posted(context):
    course = context["course_code"]
    title = context["title"]
    return (
        f"New announcement — {course}",
        (
            f"{context['author_name']} posted an announcement to {course}.\n\n"
            f"{title}\n\n"
            "Sign in to read it in full."
        ),
        f"Senet: new {course} announcement — {title}",
    )


_RENDERERS = {
    NotificationEvent.RESULT_RETURNED: _result_returned,
    NotificationEvent.RESULT_PUBLISHED: _result_published,
    NotificationEvent.EXAM_SCHEDULED: _exam_scheduled,
    NotificationEvent.EXAM_OPENED: _exam_opened,
    NotificationEvent.CHEATING_FLAG_RAISED: _cheating_flag_raised,
    NotificationEvent.CHEATING_FLAG_ESCALATED: _cheating_flag_escalated,
    NotificationEvent.RESULT_CHECK_OTP: _result_check_otp,
    NotificationEvent.RESULT_CHECK_REPLY: _result_check_reply,
    NotificationEvent.ANNOUNCEMENT_POSTED: _announcement_posted,
}


def render(event, channel, context):
    """(subject, body) for an event on a channel. Subject is ignored by the text
    channels but kept on the log row so every entry reads the same way."""
    renderer = _RENDERERS.get(event)
    if renderer is None:
        raise ValueError(f"No message defined for the '{event}' event.")
    subject, long_body, short_body = renderer(context)
    body = short_body if channel in SHORT_CHANNELS else long_body
    return subject[:255], body
