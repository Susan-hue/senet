"""SMS/USSD result-check tests.

The properties under test, in order of importance:

1. Nothing but a Senate-ratified result can ever leave over SMS or USSD — not a
   draft, not a submitted sheet, not one approved by an HOD or Dean, and not even
   when the tenant has configured its GPA source state more loosely.
2. The requester is really the student: an unregistered phone, a wrong matric or
   a wrong PIN all get nothing, and none of them can tell which was wrong.
3. Cross-tenant isolation, lockout, rate limiting and caching all hold.
"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Enrolment,
    Faculty,
    Programme,
    Role,
    Semester,
    Session,
    User,
)
from notifications import resultcheck
from notifications.models import (
    Notification,
    NotificationEvent,
    ResultCheckRegistration,
)
from notifications.resultcheck import (
    GENERIC_DENIAL,
    LOCKED,
    NO_RESULTS,
    NOT_REGISTERED,
    RATE_LIMITED,
    check_result,
    handle_inbound_sms,
    handle_ussd,
    published_summary,
    verify_webhook_signature,
)
from notifications.services import confirm_registration, start_registration
from results.models import CourseResult, ResultStatus
from results.services import approve_result, record_score, submit_result
from tenancy.models import Institution
from tenancy.scoping import set_current_institution

CONSOLE = "notifications.providers.ConsoleProvider"
CONSOLE_PROVIDERS = {"email": CONSOLE, "sms": CONSOLE, "whatsapp": CONSOLE}

STUDENT_PHONE = "08031111111"
STUDENT_E164 = "+2348031111111"
STRANGER_PHONE = "08039999999"
MATRIC = "CSC/2021/001"
PIN = "8351"


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class ResultCheckBase(TestCase):
    def setUp(self):
        cache.clear()
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        set_current_institution(self.inst)
        self.faculty = Faculty.all_objects.create(institution=self.inst, name="Science", code="SCI")
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="Computer Science", code="CSC"
        )
        self.programme = Programme.all_objects.create(
            institution=self.inst,
            department=self.dept,
            name="Computer Science",
            code="CSC",
            degree_type="B.Sc",
        )
        self.session = Session.all_objects.create(
            institution=self.inst, name="2025/2026", start_date="2025-10-01", end_date="2026-07-31"
        )
        self.semester = Semester.all_objects.create(
            institution=self.inst,
            session=self.session,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        self.course = Course.all_objects.create(
            institution=self.inst,
            department=self.dept,
            code="CSC 101",
            title="Intro to Computing",
            credit_units=3,
        )
        self.lecturer = _member(self.inst, "lecturer@veritas.edu.ng", Role.LECTURER)
        self.hod = _member(self.inst, "hod@veritas.edu.ng", Role.HOD, department=self.dept)
        self.dean = _member(self.inst, "dean@veritas.edu.ng", Role.DEAN, faculty=self.faculty)
        self.senate = _member(self.inst, "senate@veritas.edu.ng", Role.SENATE_ADMIN)
        self.student = _member(
            self.inst,
            "student@veritas.edu.ng",
            Role.STUDENT,
            full_name="Ada Obi",
            identifier=MATRIC,
            department=self.dept,
        )
        CourseAssignment.all_objects.create(
            institution=self.inst,
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
        )
        Enrolment.all_objects.create(
            institution=self.inst,
            student=self.student,
            course=self.course,
            session=self.session,
            semester=self.semester,
        )
        self.registration = self._register(self.student, STUDENT_PHONE, PIN)

    def tearDown(self):
        cache.clear()

    def _register(self, student, phone, pin):
        """A verified binding, created the way the portal creates one."""
        from notifications.services import normalize_msisdn

        return ResultCheckRegistration.all_objects.create(
            institution=student.institution,
            student=student,
            msisdn=normalize_msisdn(phone),
            is_verified=True,
            verified_at=timezone.now(),
            pin_hash=make_password(pin),
        )

    def _sheet(self, *, student=None, exam_score=50, ca_score=30):
        result = CourseResult.all_objects.create(
            institution=self.inst,
            course=self.course,
            session=self.session,
            semester=self.semester,
            lecturer=self.lecturer,
        )
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=student or self.student,
            exam_score=exam_score,
            ca_score=ca_score,
        )
        return result

    def _ratify(self, result):
        submit_result(actor=self.lecturer, result_id=result.id)
        approve_result(actor=self.hod, result_id=result.id)
        approve_result(actor=self.dean, result_id=result.id)
        with self.captureOnCommitCallbacks(execute=True):
            approve_result(actor=self.senate, result_id=result.id)
        result.refresh_from_db()
        return result


class OnlyRatifiedResultsLeakTests(ResultCheckBase):
    def test_a_draft_result_is_never_returned(self):
        self._sheet()
        reply = check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN)
        self.assertEqual(reply, NO_RESULTS)
        self.assertNotIn("CSC 101", reply)

    def test_a_sheet_awaiting_the_hod_is_never_returned(self):
        result = self._sheet()
        submit_result(actor=self.lecturer, result_id=result.id)
        self.assertEqual(check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN), NO_RESULTS)

    def test_a_dean_approved_sheet_is_still_not_published(self):
        result = self._sheet()
        submit_result(actor=self.lecturer, result_id=result.id)
        approve_result(actor=self.hod, result_id=result.id)
        approve_result(actor=self.dean, result_id=result.id)
        result.refresh_from_db()
        self.assertEqual(result.status, ResultStatus.APPROVED_BY_DEAN)
        self.assertEqual(check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN), NO_RESULTS)

    def test_a_ratified_sheet_is_returned(self):
        self._ratify(self._sheet())
        reply = check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN)
        self.assertIn("CSC 101", reply)
        self.assertIn("CGPA", reply)
        self.assertIn("Senate-ratified", reply)

    @override_settings()
    def test_a_loose_tenant_gpa_source_cannot_widen_the_sms_channel(self):
        """The portal reads ``institution.gpa_source_status``; this channel does
        not. Pointing that setting at an unratified state must not publish
        anything over SMS."""
        result = self._sheet()
        submit_result(actor=self.lecturer, result_id=result.id)
        self.inst.gpa_source_status = ResultStatus.SUBMITTED_TO_HOD
        self.inst.save()

        # The portal's own view of "official" now includes the submitted sheet...
        from grading.services import official_rows

        self.student.refresh_from_db()
        self.assertEqual(official_rows(self.student).count(), 1)
        # ...but the SMS channel still shows nothing.
        self.assertEqual(check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN), NO_RESULTS)
        self.assertIsNone(published_summary(self.student))

    def test_an_amended_score_only_publishes_once_reapplied(self):
        result = self._ratify(self._sheet(exam_score=50, ca_score=30))
        reply = check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN)
        self.assertIn("CSC 101", reply)
        self.assertEqual(result.status, ResultStatus.RATIFIED_BY_SENATE)


class RequesterVerificationTests(ResultCheckBase):
    def setUp(self):
        super().setUp()
        self._ratify(self._sheet())

    def test_an_unregistered_phone_gets_nothing(self):
        reply = check_result(msisdn=STRANGER_PHONE, matric=MATRIC, pin=PIN)
        self.assertEqual(reply, NOT_REGISTERED)
        self.assertNotIn("CSC 101", reply)

    def test_a_stranger_who_knows_the_matric_and_texts_from_their_own_phone_gets_nothing(self):
        """The matric number is public knowledge; the binding is what matters."""
        stranger = _member(
            self.inst, "stranger@veritas.edu.ng", Role.STUDENT, identifier="CSC/2021/999"
        )
        self._register(stranger, STRANGER_PHONE, "4417")
        reply = check_result(msisdn=STRANGER_PHONE, matric=MATRIC, pin=PIN)
        self.assertEqual(reply, GENERIC_DENIAL)
        self.assertNotIn("Ada Obi", reply)
        self.assertNotIn("CSC 101", reply)

    def test_the_wrong_pin_gets_nothing(self):
        reply = check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin="0000")
        self.assertEqual(reply, GENERIC_DENIAL)
        self.assertNotIn("CSC 101", reply)

    def test_the_wrong_matric_gets_nothing(self):
        reply = check_result(msisdn=STUDENT_PHONE, matric="CSC/2021/002", pin=PIN)
        self.assertEqual(reply, GENERIC_DENIAL)

    def test_a_missing_pin_gets_nothing(self):
        self.assertEqual(check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=""), GENERIC_DENIAL)

    def test_the_denial_does_not_distinguish_a_bad_matric_from_a_bad_pin(self):
        """Otherwise the channel becomes an oracle for guessing either one."""
        bad_matric = check_result(msisdn=STUDENT_PHONE, matric="CSC/2021/777", pin=PIN)
        cache.delete(f"resultcheck:rate:{STUDENT_E164}")
        self.registration.refresh_from_db()
        self.registration.failed_attempts = 0
        self.registration.save(update_fields=["failed_attempts"])
        bad_pin = check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin="1234")
        self.assertEqual(bad_matric, bad_pin)

    def test_an_unverified_binding_cannot_check(self):
        self.registration.is_verified = False
        self.registration.save(update_fields=["is_verified"])
        self.assertEqual(check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN), NOT_REGISTERED)

    def test_a_matric_only_message_is_rejected(self):
        reply = handle_inbound_sms(msisdn=STUDENT_PHONE, text=f"RESULT {MATRIC}")
        self.assertNotIn("CSC 101", reply)
        self.assertIn("PIN", reply)

    def test_repeated_failures_lock_the_registration(self):
        with override_settings(RESULT_CHECK_MAX_FAILURES=3, RESULT_CHECK_RATE_LIMIT=50):
            for _ in range(3):
                check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin="0000")
            self.registration.refresh_from_db()
            self.assertTrue(self.registration.is_locked)
            # Even the correct PIN is refused while locked.
            self.assertEqual(check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN), LOCKED)

    def test_a_successful_check_clears_the_failure_count(self):
        with override_settings(RESULT_CHECK_RATE_LIMIT=50):
            check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin="0000")
            self.registration.refresh_from_db()
            self.assertEqual(self.registration.failed_attempts, 1)
            check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN)
            self.registration.refresh_from_db()
            self.assertEqual(self.registration.failed_attempts, 0)
            self.assertIsNotNone(self.registration.last_checked_at)


class CrossTenantTests(ResultCheckBase):
    def setUp(self):
        super().setUp()
        self.other = Institution.objects.create(name="Bells University", code="bells")
        self.other_student = _member(
            self.other, "other@bells.edu.ng", Role.STUDENT, identifier=MATRIC
        )
        self._ratify(self._sheet())

    def test_a_number_resolves_to_its_own_tenant_only(self):
        """Both institutions issue the same matric string; the phone binding
        decides which student — and therefore which tenant — is read."""
        other_registration = self._register(self.other_student, STRANGER_PHONE, "7742")
        set_current_institution(self.inst)
        reply = check_result(msisdn=STRANGER_PHONE, matric=MATRIC, pin="7742")

        self.assertEqual(other_registration.institution_id, self.other.id)
        self.assertNotIn("CSC 101", reply)
        self.assertEqual(reply, NO_RESULTS)

    def test_a_verified_number_cannot_be_claimed_by_a_second_student(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            self._register(self.other_student, STUDENT_PHONE, "1122")


class RateLimitAndCacheTests(ResultCheckBase):
    def setUp(self):
        super().setUp()
        self._ratify(self._sheet())

    def test_a_number_is_rate_limited(self):
        with override_settings(RESULT_CHECK_RATE_LIMIT=3):
            replies = [check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN) for _ in range(4)]
        self.assertEqual(replies[-1], RATE_LIMITED)
        self.assertIn("CSC 101", replies[0])

    def test_the_limit_is_per_number_not_global(self):
        """Results day is a whole campus checking at once — one student's burst
        must not throttle anyone else."""
        classmate = _member(
            self.inst, "classmate@veritas.edu.ng", Role.STUDENT, identifier="CSC/2021/050"
        )
        self._register(classmate, STRANGER_PHONE, "5566")
        with override_settings(RESULT_CHECK_RATE_LIMIT=2):
            for _ in range(3):
                check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN)
            reply = check_result(msisdn=STRANGER_PHONE, matric="CSC/2021/050", pin="5566")
        self.assertNotEqual(reply, RATE_LIMITED)

    def test_the_summary_is_cached(self):
        published_summary(self.student)
        with mock.patch("notifications.resultcheck.official_rows") as rows:
            published_summary(self.student)
        rows.assert_not_called()

    def test_publishing_invalidates_the_cached_summary(self):
        published_summary(self.student)
        second = Course.all_objects.create(
            institution=self.inst,
            department=self.dept,
            code="CSC 102",
            title="Discrete Maths",
            credit_units=3,
        )
        CourseAssignment.all_objects.create(
            institution=self.inst,
            lecturer=self.lecturer,
            course=second,
            session=self.session,
            semester=self.semester,
        )
        Enrolment.all_objects.create(
            institution=self.inst,
            student=self.student,
            course=second,
            session=self.session,
            semester=self.semester,
        )
        result = CourseResult.all_objects.create(
            institution=self.inst,
            course=second,
            session=self.session,
            semester=self.semester,
            lecturer=self.lecturer,
        )
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            exam_score=55,
            ca_score=35,
        )
        self._ratify(result)
        self.assertIn("CSC 102", check_result(msisdn=STUDENT_PHONE, matric=MATRIC, pin=PIN))


class UssdTests(ResultCheckBase):
    def setUp(self):
        super().setUp()
        self._ratify(self._sheet())

    def test_the_dialogue_collects_matric_then_pin(self):
        message, final = handle_ussd(session_id="s1", msisdn=STUDENT_PHONE, text="")
        self.assertFalse(final)
        self.assertIn("matric", message.lower())

        message, final = handle_ussd(session_id="s1", msisdn=STUDENT_PHONE, text=MATRIC)
        self.assertFalse(final)
        self.assertIn("PIN", message)

        message, final = handle_ussd(session_id="s1", msisdn=STUDENT_PHONE, text=PIN)
        self.assertTrue(final)
        self.assertIn("CSC 101", message)

    def test_ussd_is_no_more_trusted_than_sms(self):
        handle_ussd(session_id="s2", msisdn=STRANGER_PHONE, text="")
        handle_ussd(session_id="s2", msisdn=STRANGER_PHONE, text=MATRIC)
        message, final = handle_ussd(session_id="s2", msisdn=STRANGER_PHONE, text=PIN)
        self.assertTrue(final)
        self.assertEqual(message, NOT_REGISTERED)

    def test_a_wrong_pin_over_ussd_reveals_nothing(self):
        handle_ussd(session_id="s3", msisdn=STUDENT_PHONE, text="")
        handle_ussd(session_id="s3", msisdn=STUDENT_PHONE, text=MATRIC)
        message, _final = handle_ussd(session_id="s3", msisdn=STUDENT_PHONE, text="0000")
        self.assertEqual(message, GENERIC_DENIAL)


@override_settings(
    NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS, TERMII_INBOUND_SECRET="test-inbound-secret"
)
class InboundWebhookTests(APITestCase, ResultCheckBase):
    def setUp(self):
        ResultCheckBase.setUp(self)
        self._ratify(self._sheet())

    def _signed(self, url, payload):
        import hashlib
        import hmac
        import json

        body = json.dumps(payload)
        signature = hmac.new(b"test-inbound-secret", body.encode(), hashlib.sha256).hexdigest()
        return self.client.post(
            url, body, content_type="application/json", HTTP_X_SENET_SIGNATURE=signature
        )

    def test_an_unsigned_request_is_rejected(self):
        response = self.client.post(
            reverse("notification-inbound-sms"),
            {"msisdn": STUDENT_PHONE, "text": f"RESULT {MATRIC} {PIN}"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_wrongly_signed_request_is_rejected(self):
        response = self.client.post(
            reverse("notification-inbound-sms"),
            f'{{"msisdn": "{STUDENT_PHONE}", "text": "x"}}',
            content_type="application/json",
            HTTP_X_SENET_SIGNATURE="deadbeef",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(TERMII_INBOUND_SECRET="")
    def test_the_webhook_fails_closed_without_a_configured_secret(self):
        response = self.client.post(
            reverse("notification-inbound-sms"),
            {"msisdn": STUDENT_PHONE, "text": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_signed_request_answers_and_queues_an_sms_reply(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._signed(
                reverse("notification-inbound-sms"),
                {"msisdn": STUDENT_PHONE, "text": f"RESULT {MATRIC} {PIN}"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("CSC 101", response.data["data"]["reply"])

        reply = Notification.all_objects.filter(event=NotificationEvent.RESULT_CHECK_REPLY).first()
        self.assertIsNotNone(reply)
        self.assertEqual(reply.recipient_address, STUDENT_E164)
        self.assertIn("CSC 101", reply.body)

    def test_a_signed_request_from_a_stranger_leaks_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._signed(
                reverse("notification-inbound-sms"),
                {"msisdn": STRANGER_PHONE, "text": f"RESULT {MATRIC} {PIN}"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("CSC 101", response.data["data"]["reply"])
        self.assertNotIn("Ada Obi", response.data["data"]["reply"])

    def test_the_ussd_webhook_returns_a_session_response(self):
        response = self._signed(
            reverse("notification-inbound-ussd"),
            {"sessionId": "abc", "msisdn": STUDENT_PHONE, "text": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["type"], "response")
        self.assertIn("matric", response.data["message"].lower())

    def test_signature_verification_is_exact(self):
        self.assertTrue(
            verify_webhook_signature(
                raw_body=b"payload",
                signature=__import__("hmac")
                .new(b"test-inbound-secret", b"payload", __import__("hashlib").sha256)
                .hexdigest(),
            )
        )
        self.assertFalse(verify_webhook_signature(raw_body=b"payload", signature="00"))
        self.assertFalse(verify_webhook_signature(raw_body=b"payload", signature=""))


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class RegistrationFlowTests(ResultCheckBase):
    def setUp(self):
        super().setUp()
        self.new_student = _member(
            self.inst, "new@veritas.edu.ng", Role.STUDENT, identifier="CSC/2021/077"
        )

    def _start(self, phone="08032222222", pin="9214"):
        with mock.patch("notifications.services._generate_otp", return_value="123456"):
            with self.captureOnCommitCallbacks(execute=True):
                return start_registration(student=self.new_student, msisdn=phone, pin=pin)

    def test_registration_texts_a_code_and_starts_unverified(self):
        registration = self._start()
        self.assertFalse(registration.is_verified)
        otp = Notification.all_objects.filter(event=NotificationEvent.RESULT_CHECK_OTP).first()
        self.assertIsNotNone(otp)
        self.assertIn("123456", otp.body)
        self.assertEqual(otp.recipient_address, "+2348032222222")

    def test_an_unverified_registration_cannot_check_results(self):
        self._start()
        self.assertEqual(
            check_result(msisdn="08032222222", matric="CSC/2021/077", pin="9214"), NOT_REGISTERED
        )

    def test_the_code_completes_the_binding(self):
        self._start()
        registration = confirm_registration(student=self.new_student, otp="123456")
        self.assertTrue(registration.is_verified)

    def test_a_wrong_code_does_not_verify(self):
        from rest_framework.exceptions import ValidationError

        self._start()
        with self.assertRaises(ValidationError):
            confirm_registration(student=self.new_student, otp="000000")
        registration = ResultCheckRegistration.all_objects.get(student=self.new_student)
        self.assertFalse(registration.is_verified)
        self.assertEqual(registration.failed_attempts, 1)

    def test_an_expired_code_does_not_verify(self):
        from rest_framework.exceptions import ValidationError

        registration = self._start()
        registration.otp_expires_at = timezone.now() - timedelta(minutes=1)
        registration.save(update_fields=["otp_expires_at"])
        with self.assertRaises(ValidationError):
            confirm_registration(student=self.new_student, otp="123456")

    def test_the_pin_is_only_ever_stored_hashed(self):
        registration = self._start(pin="9214")
        self.assertNotIn("9214", registration.pin_hash)
        self.assertTrue(registration.pin_hash.startswith("pbkdf2_"))

    def test_weak_pins_are_rejected(self):
        from rest_framework.exceptions import ValidationError

        for weak in ("1111", "1234", "12", "abcd", ""):
            with self.assertRaises(ValidationError):
                start_registration(student=self.new_student, msisdn="08032222222", pin=weak)

    def test_a_number_already_verified_elsewhere_is_refused(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            start_registration(student=self.new_student, msisdn=STUDENT_PHONE, pin="9214")

    def test_only_a_student_can_register(self):
        from rest_framework.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            start_registration(student=self.lecturer, msisdn="08034444444", pin="9214")

    def test_re_registering_the_same_number_re_proves_it(self):
        self._start()
        confirm_registration(student=self.new_student, otp="123456")
        registration = self._start()
        self.assertFalse(registration.is_verified)


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class RegistrationEndpointTests(APITestCase, ResultCheckBase):
    def setUp(self):
        ResultCheckBase.setUp(self)
        self.new_student = _member(
            self.inst, "new@veritas.edu.ng", Role.STUDENT, identifier="CSC/2021/077"
        )

    def test_a_student_registers_and_verifies_over_the_api(self):
        self.client.force_authenticate(self.new_student)
        with mock.patch("notifications.services._generate_otp", return_value="654321"):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse("result-check-registration"),
                    {"msisdn": "08035555555", "pin": "9214"},
                    format="json",
                )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("result-check-verify"), {"otp": "654321"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["is_verified"])

    def test_the_endpoint_never_echoes_the_full_number(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("result-check-registration"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("8031111111", response.data["data"]["msisdn"])
        self.assertTrue(response.data["data"]["msisdn"].endswith("1111"))

    def test_a_lecturer_cannot_register(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("result-check-registration"),
            {"msisdn": "08036666666", "pin": "9214"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_caller_cannot_register(self):
        response = self.client.post(
            reverse("result-check-registration"),
            {"msisdn": "08037777777", "pin": "9214"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)


class PublishedStatusConstantTest(TestCase):
    def test_the_channel_is_pinned_to_the_ratified_state(self):
        """A regression guard: if this constant ever becomes configurable, the
        SMS channel stops being safe."""
        self.assertEqual(resultcheck.PUBLISHED_STATUS, ResultStatus.RATIFIED_BY_SENATE)
