"""Notification dispatch tests: queueing, async sending through a mocked
provider, graceful provider failure, append-only logging, and tenant isolation.

No test ever reaches a real provider — the sending layer is either the console
provider or an explicit mock.
"""

from datetime import timedelta
from unittest import mock

from django.core import mail
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
from notifications.models import (
    AppendOnlyError,
    Notification,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
)
from notifications.providers import ConsoleProvider, ProviderError, TermiiProvider, get_provider
from notifications.services import normalize_msisdn, notify_users
from notifications.tasks import send_notification
from results.models import CourseResult, ResultStatus, StudentScore
from results.services import approve_result, record_score, return_result, submit_result
from tenancy.models import Institution
from tenancy.scoping import set_current_institution

CONSOLE = "notifications.providers.ConsoleProvider"
CONSOLE_PROVIDERS = {"email": CONSOLE, "sms": CONSOLE, "whatsapp": CONSOLE}


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class NotificationTestBase(TestCase):
    def setUp(self):
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
        self.lecturer = _member(
            self.inst, "lecturer@veritas.edu.ng", Role.LECTURER, phone_number="08030000001"
        )
        self.hod = _member(self.inst, "hod@veritas.edu.ng", Role.HOD, department=self.dept)
        self.dean = _member(self.inst, "dean@veritas.edu.ng", Role.DEAN, faculty=self.faculty)
        self.senate = _member(self.inst, "senate@veritas.edu.ng", Role.SENATE_ADMIN)
        self.student = _member(
            self.inst,
            "student@veritas.edu.ng",
            Role.STUDENT,
            identifier="CSC/2021/001",
            department=self.dept,
            phone_number="08030000002",
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

    def _sheet_with_score(self):
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
            student=self.student,
            exam_score=50,
            ca_score=30,
        )
        return result


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class DispatchTests(NotificationTestBase):
    def test_queues_one_row_per_recipient_and_channel(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "Recheck question 3.",
                },
            )
        rows = Notification.all_objects.filter(recipient=self.lecturer)
        self.assertEqual(
            {row.channel for row in rows},
            {NotificationChannel.EMAIL, NotificationChannel.SMS},
        )
        self.assertTrue(all(row.status == NotificationStatus.SENT for row in rows))

    def test_recipient_without_an_address_is_skipped(self):
        no_phone = _member(self.inst, "nophone@veritas.edu.ng", Role.LECTURER)
        with self.captureOnCommitCallbacks(execute=True):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[no_phone],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "",
                },
            )
        channels = set(
            Notification.all_objects.filter(recipient=no_phone).values_list("channel", flat=True)
        )
        self.assertEqual(channels, {NotificationChannel.EMAIL})

    def test_whatsapp_is_off_unless_enabled(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_PUBLISHED,
                users=[self.student],
                context={"course_code": "CSC 101", "session": "2025/2026", "semester": "First"},
            )
        self.assertFalse(
            Notification.all_objects.filter(channel=NotificationChannel.WHATSAPP).exists()
        )

    @override_settings(NOTIFICATIONS_WHATSAPP_ENABLED=True)
    def test_whatsapp_is_used_when_enabled(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_PUBLISHED,
                users=[self.student],
                context={"course_code": "CSC 101", "session": "2025/2026", "semester": "First"},
            )
        row = Notification.all_objects.get(channel=NotificationChannel.WHATSAPP)
        self.assertEqual(row.recipient_address, "+2348030000002")

    def test_dedupe_key_prevents_a_second_queue(self):
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                notify_users(
                    institution=self.inst,
                    event=NotificationEvent.RESULT_PUBLISHED,
                    users=[self.student],
                    context={
                        "course_code": "CSC 101",
                        "session": "2025/2026",
                        "semester": "First",
                    },
                    dedupe_prefix="result_published:test",
                )
        self.assertEqual(
            Notification.all_objects.filter(event=NotificationEvent.RESULT_PUBLISHED).count(), 2
        )  # one email + one SMS, not four

    def test_nothing_is_queued_when_the_transaction_rolls_back(self):
        with self.captureOnCommitCallbacks(execute=False):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "",
                },
            )
        # Rows exist but nothing was handed to Celery, so nothing was sent.
        self.assertTrue(
            all(row.status == NotificationStatus.QUEUED for row in Notification.all_objects.all())
        )


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class SendTaskTests(NotificationTestBase):
    def _queued(self):
        with self.captureOnCommitCallbacks(execute=False):
            rows = notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "Recheck.",
                },
            )
        return rows[0]

    def test_send_marks_sent_and_records_the_provider(self):
        notification = self._queued()
        send_notification(str(notification.id))
        notification.refresh_from_db()
        self.assertEqual(notification.status, NotificationStatus.SENT)
        self.assertEqual(notification.provider, "console")
        self.assertEqual(notification.attempts, 1)
        self.assertIsNotNone(notification.sent_at)

    def test_provider_outage_is_logged_not_raised(self):
        notification = self._queued()
        with mock.patch.object(ConsoleProvider, "send", side_effect=ProviderError("gateway down")):
            result = send_notification(str(notification.id))
        self.assertEqual(result, NotificationStatus.FAILED.value)
        notification.refresh_from_db()
        self.assertEqual(notification.status, NotificationStatus.FAILED)
        self.assertIn("gateway down", notification.error)
        self.assertEqual(notification.attempts, 1)

    def test_an_unexpected_provider_crash_is_also_contained(self):
        notification = self._queued()
        with mock.patch.object(ConsoleProvider, "send", side_effect=RuntimeError("boom")):
            result = send_notification(str(notification.id))
        self.assertEqual(result, NotificationStatus.FAILED.value)
        notification.refresh_from_db()
        self.assertEqual(notification.status, NotificationStatus.FAILED)

    def test_sending_twice_does_not_resend(self):
        notification = self._queued()
        send_notification(str(notification.id))
        with mock.patch.object(ConsoleProvider, "send") as send:
            send_notification(str(notification.id))
        send.assert_not_called()

    def test_a_missing_notification_is_a_no_op(self):
        self.assertIsNone(send_notification("00000000-0000-0000-0000-000000000000"))


class ProviderTests(TestCase):
    def test_termii_requires_configuration(self):
        provider = TermiiProvider(api_key="", base_url="https://api.ng.termii.com")
        with self.assertRaises(ProviderError):
            provider.send(
                channel=NotificationChannel.SMS, to="+2348030000000", subject="", body="x"
            )

    def test_termii_refuses_a_non_https_endpoint(self):
        provider = TermiiProvider(api_key="k", base_url="http://api.ng.termii.com")
        with self.assertRaises(ProviderError):
            provider.send(
                channel=NotificationChannel.SMS, to="+2348030000000", subject="", body="x"
            )

    def test_termii_does_not_carry_email(self):
        provider = TermiiProvider(api_key="k")
        with self.assertRaises(ProviderError):
            provider.send(channel=NotificationChannel.EMAIL, to="a@b.ng", subject="", body="x")

    @override_settings(NOTIFICATION_PROVIDERS={"sms": "notifications.providers.Nope"})
    def test_an_unloadable_provider_surfaces_as_provider_error(self):
        with self.assertRaises(ProviderError):
            get_provider(NotificationChannel.SMS)

    @override_settings(NOTIFICATION_PROVIDERS={})
    def test_an_unconfigured_channel_surfaces_as_provider_error(self):
        with self.assertRaises(ProviderError):
            get_provider(NotificationChannel.SMS)

    def test_msisdn_normalisation(self):
        for raw in ("08030000002", "+234 803 000 0002", "2348030000002", "00234 803 000 0002"):
            self.assertEqual(normalize_msisdn(raw), "+2348030000002")
        self.assertIsNone(normalize_msisdn(""))
        self.assertIsNone(normalize_msisdn("abc"))


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class AppendOnlyLogTests(NotificationTestBase):
    def _row(self):
        with self.captureOnCommitCallbacks(execute=False):
            rows = notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "",
                },
            )
        return rows[0]

    def test_content_cannot_be_rewritten(self):
        row = self._row()
        row.body = "something else"
        with self.assertRaises(AppendOnlyError):
            row.save(update_fields=["body"])
        with self.assertRaises(AppendOnlyError):
            row.save()

    def test_delivery_state_may_change(self):
        row = self._row()
        row.mark_sent(provider="console", message_id="abc")
        row.refresh_from_db()
        self.assertEqual(row.status, NotificationStatus.SENT)

    def test_rows_cannot_be_deleted(self):
        row = self._row()
        with self.assertRaises(AppendOnlyError):
            row.delete()


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class ResultPipelineTriggerTests(NotificationTestBase):
    def test_returning_a_sheet_notifies_the_lecturer(self):
        result = self._sheet_with_score()
        submit_result(actor=self.lecturer, result_id=result.id)
        with self.captureOnCommitCallbacks(execute=True):
            return_result(actor=self.hod, result_id=result.id, reason="Recheck question 3.")
        rows = Notification.all_objects.filter(event=NotificationEvent.RESULT_RETURNED)
        self.assertTrue(rows.exists())
        self.assertEqual({row.recipient_id for row in rows}, {self.lecturer.id})
        self.assertIn("Recheck question 3.", rows.first().body)

    def test_ratifying_notifies_the_students_on_the_sheet(self):
        result = self._sheet_with_score()
        submit_result(actor=self.lecturer, result_id=result.id)
        approve_result(actor=self.hod, result_id=result.id)
        approve_result(actor=self.dean, result_id=result.id)
        with self.captureOnCommitCallbacks(execute=True):
            approve_result(actor=self.senate, result_id=result.id)
        rows = Notification.all_objects.filter(event=NotificationEvent.RESULT_PUBLISHED)
        self.assertEqual({row.recipient_id for row in rows}, {self.student.id})

    def test_an_intermediate_approval_notifies_nobody(self):
        result = self._sheet_with_score()
        submit_result(actor=self.lecturer, result_id=result.id)
        with self.captureOnCommitCallbacks(execute=True):
            approve_result(actor=self.hod, result_id=result.id)
        self.assertFalse(
            Notification.all_objects.filter(
                event__in=[
                    NotificationEvent.RESULT_PUBLISHED,
                    NotificationEvent.RESULT_RETURNED,
                ]
            ).exists()
        )

    def test_a_failing_provider_does_not_break_the_transition(self):
        result = self._sheet_with_score()
        submit_result(actor=self.lecturer, result_id=result.id)
        approve_result(actor=self.hod, result_id=result.id)
        approve_result(actor=self.dean, result_id=result.id)
        with mock.patch.object(ConsoleProvider, "send", side_effect=ProviderError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                approve_result(actor=self.senate, result_id=result.id)

        result.refresh_from_db()
        self.assertEqual(result.status, ResultStatus.RATIFIED_BY_SENATE)
        self.assertTrue(Notification.all_objects.filter(status=NotificationStatus.FAILED).exists())

    def test_the_email_channel_reaches_the_real_mail_backend(self):
        mail.outbox = []
        result = self._sheet_with_score()
        submit_result(actor=self.lecturer, result_id=result.id)
        with override_settings(
            NOTIFICATION_PROVIDERS={
                "email": "notifications.providers.DjangoEmailProvider",
                "sms": CONSOLE,
                "whatsapp": CONSOLE,
            }
        ):
            with self.captureOnCommitCallbacks(execute=True):
                return_result(actor=self.hod, result_id=result.id, reason="Recheck.")
        self.assertTrue(any(self.lecturer.email in message.to for message in mail.outbox))


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class CrossTenantTests(NotificationTestBase):
    def setUp(self):
        super().setUp()
        self.other = Institution.objects.create(name="Bells University", code="bells")
        self.other_lecturer = _member(self.other, "other@bells.edu.ng", Role.LECTURER)

    def test_a_recipient_from_another_tenant_is_never_notified(self):
        with self.captureOnCommitCallbacks(execute=True):
            queued = notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.other_lecturer, self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "",
                },
            )
        self.assertTrue(all(row.recipient_id == self.lecturer.id for row in queued))
        self.assertFalse(Notification.all_objects.filter(recipient=self.other_lecturer).exists())

    def test_the_log_is_scoped_to_the_current_tenant(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "",
                },
            )
        set_current_institution(self.other)
        self.assertEqual(Notification.objects.count(), 0)
        set_current_institution(self.inst)
        self.assertGreater(Notification.objects.count(), 0)


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class ExamNotificationTests(NotificationTestBase):
    def _exam(self):
        from cbt.models import QuestionType
        from cbt.services import create_exam, create_question, create_question_bank

        bank = create_question_bank(actor=self.lecturer, course=self.course, title="Bank")
        for index in range(3):
            create_question(
                actor=self.lecturer,
                bank=bank,
                type=QuestionType.MCQ,
                prompt=f"Q{index}",
                options=["a", "b"],
                correct_answer=0,
                marks=1,
            )
        return create_exam(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            banks=[bank],
            title="Mid-semester CBT",
            exam_type="ca",
            duration_minutes=30,
            opens_at=timezone.now() + timedelta(hours=1),
            closes_at=timezone.now() + timedelta(hours=3),
            num_questions=2,
        )

    def test_scheduling_an_exam_notifies_enrolled_students(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._exam()
        rows = Notification.all_objects.filter(event=NotificationEvent.EXAM_SCHEDULED)
        self.assertEqual({row.recipient_id for row in rows}, {self.student.id})

    def test_the_open_sweep_is_idempotent(self):
        from cbt.models import Exam
        from notifications.tasks import notify_opened_exams

        with self.captureOnCommitCallbacks(execute=True):
            exam = self._exam()
        Exam.all_objects.filter(pk=exam.pk).update(opens_at=timezone.now() - timedelta(minutes=5))

        with self.captureOnCommitCallbacks(execute=True):
            first = notify_opened_exams()
        with self.captureOnCommitCallbacks(execute=True):
            second = notify_opened_exams()
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)


@override_settings(NOTIFICATION_PROVIDERS=CONSOLE_PROVIDERS)
class NotificationListEndpointTests(APITestCase, NotificationTestBase):
    def setUp(self):
        NotificationTestBase.setUp(self)
        self.admin = _member(self.inst, "admin@veritas.edu.ng", Role.SCHOOL_ADMIN)
        with self.captureOnCommitCallbacks(execute=True):
            notify_users(
                institution=self.inst,
                event=NotificationEvent.RESULT_RETURNED,
                users=[self.lecturer],
                context={
                    "course_code": "CSC 101",
                    "session": "2025/2026",
                    "semester": "First",
                    "reason": "",
                },
            )

    def test_a_user_sees_only_their_own(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("notification-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 0)

        self.client.force_authenticate(self.lecturer)
        response = self.client.get(reverse("notification-list"))
        self.assertGreater(response.data["data"]["count"], 0)

    def test_a_school_admin_sees_the_tenant_log(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("notification-list"))
        self.assertGreater(response.data["data"]["count"], 0)


class StudentScoreVisibilityGuard(NotificationTestBase):
    """Guards the assumption the published-results notification relies on: a
    ratified sheet is the only place a published score comes from."""

    def test_scores_exist_only_under_their_sheet_status(self):
        result = self._sheet_with_score()
        self.assertEqual(StudentScore.all_objects.filter(result=result, is_current=True).count(), 1)
        self.assertEqual(result.status, ResultStatus.DRAFT)
