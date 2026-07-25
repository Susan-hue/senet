"""CBT proctoring tests: event capture, auto-flagging, review flow, webcam access
scoping, integrity report, and retention config."""

import tempfile
from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
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
from auditor.services import create_auditor_token
from cbt.models import (
    AppendOnlyError,
    CheatingFlag,
    CheatingFlagStatus,
    Exam,
    ProctorEvent,
    ProctorEventType,
    WebcamCapture,
)
from cbt.proctoring import create_webcam_capture, dismiss_flag, escalate_flag
from cbt.services import create_exam, save_answer, start_attempt, submit_attempt
from tenancy.models import Institution
from tenancy.scoping import set_current_institution

TMP_MEDIA = tempfile.mkdtemp(prefix="senet-cbt-proctor-")


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class ProctorTestBase(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
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
            title="Intro",
            credit_units=3,
        )

        self.lecturer = _member(self.inst, "lect@veritas.edu", Role.LECTURER, department=self.dept)
        self.other_lecturer = _member(
            self.inst, "lect2@veritas.edu", Role.LECTURER, department=self.dept
        )
        self.hod = _member(self.inst, "hod@veritas.edu", Role.HOD, department=self.dept)
        self.dean = _member(self.inst, "dean@veritas.edu", Role.DEAN, faculty=self.faculty)
        self.exam_officer = _member(self.inst, "eo@veritas.edu", Role.EXAM_OFFICER)
        self.school_admin = _member(self.inst, "admin@veritas.edu", Role.SCHOOL_ADMIN)
        self.student = _member(self.inst, "stud@veritas.edu", Role.STUDENT, department=self.dept)
        self.other_student = _member(self.inst, "stud2@veritas.edu", Role.STUDENT)

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
        set_current_institution(self.inst)

        from cbt.models import Question, QuestionBank

        self.bank = QuestionBank.all_objects.create(
            institution=self.inst, course=self.course, title="Pool", created_by=self.lecturer
        )
        self.question = Question.all_objects.create(
            institution=self.inst,
            bank=self.bank,
            type="mcq",
            prompt="Q",
            options=["A", "B"],
            correct_answer=0,
            marks=Decimal("10"),
            created_by=self.lecturer,
        )
        now = timezone.now()
        self.exam = create_exam(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            banks=[self.bank],
            title="Midterm",
            exam_type=Exam.ExamType.MAIN,
            duration_minutes=60,
            opens_at=now - timedelta(minutes=30),
            closes_at=now + timedelta(minutes=60),
            num_questions=1,
        )
        self.attempt = start_attempt(student=self.student, exam=self.exam)

    def post_event(self, event_type, detail=None, attempt=None, actor=None):
        self.client.force_authenticate(actor or self.student)
        return self.client.post(
            reverse("cbt-attempt-events", args=[(attempt or self.attempt).id]),
            {"type": event_type, "client_timestamp": timezone.now().isoformat(), "detail": detail},
            format="json",
        )

    def trip_flag(self):
        for _ in range(3):
            self.post_event(ProctorEventType.TAB_SWITCH)

    def grade_attempt(self):
        aq = self.attempt.attempt_questions.get()
        save_answer(
            student=self.student,
            attempt=self.attempt,
            question_id=aq.question_id,
            raw_response=aq.option_order.index(0),
        )
        submit_attempt(student=self.student, attempt=self.attempt)
        self.attempt.refresh_from_db()


class ProctorEventTests(ProctorTestBase):
    def test_events_are_captured_append_only_and_attempt_scoped(self):
        self.assertEqual(self.post_event(ProctorEventType.HEARTBEAT).status_code, 201)
        self.assertEqual(self.post_event(ProctorEventType.FULLSCREEN_EXIT).status_code, 201)
        events = ProctorEvent.all_objects.filter(attempt=self.attempt)
        self.assertEqual(events.count(), 2)
        self.assertTrue(all(e.attempt_id == self.attempt.id for e in events))

    def test_event_cannot_be_edited_or_deleted(self):
        self.post_event(ProctorEventType.TAB_SWITCH)
        event = ProctorEvent.all_objects.filter(attempt=self.attempt).first()
        event.type = ProctorEventType.HEARTBEAT
        with self.assertRaises(AppendOnlyError):
            event.save()
        with self.assertRaises(AppendOnlyError):
            event.delete()

    def test_student_cannot_post_events_to_another_attempt(self):
        response = self.post_event(ProctorEventType.TAB_SWITCH, actor=self.other_student)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CheatingFlagTests(ProctorTestBase):
    def test_flag_auto_raises_on_threshold_without_touching_score_or_status(self):
        self.grade_attempt()
        before_status, before_score = self.attempt.status, self.attempt.score

        self.trip_flag()

        flag = CheatingFlag.all_objects.get(attempt=self.attempt)
        self.assertEqual(flag.status, CheatingFlagStatus.RAISED)
        self.assertTrue(flag.auto_raised)
        self.assertTrue(any(r["code"] == "repeated_tab_switch" for r in flag.reasons))

        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, before_status)
        self.assertEqual(self.attempt.score, before_score)

    def test_no_flag_below_threshold(self):
        self.post_event(ProctorEventType.TAB_SWITCH)
        self.post_event(ProctorEventType.TAB_SWITCH)
        self.assertFalse(CheatingFlag.all_objects.filter(attempt=self.attempt).exists())

    def test_only_one_flag_per_attempt(self):
        for _ in range(6):
            self.post_event(ProctorEventType.TAB_SWITCH)
        self.assertEqual(CheatingFlag.all_objects.filter(attempt=self.attempt).count(), 1)

    def test_notifies_lecturer_and_exam_officer_once(self):
        mail.outbox = []
        self.trip_flag()
        self.assertEqual(len(mail.outbox), 1)
        recipients = set(mail.outbox[0].to)
        self.assertIn(self.lecturer.email, recipients)
        self.assertIn(self.exam_officer.email, recipients)

    def test_webcam_anomaly_can_raise_a_flag(self):
        with override_settings(MEDIA_ROOT=TMP_MEDIA):
            create_webcam_capture(
                attempt=self.attempt,
                media=SimpleUploadedFile("s.jpg", b"x", content_type="image/jpeg"),
                kind=WebcamCapture.Kind.SNAPSHOT,
                captured_at=timezone.now(),
                is_anomalous=True,
                anomaly_reason="No face detected",
            )
        flag = CheatingFlag.all_objects.get(attempt=self.attempt)
        self.assertTrue(any(r["code"] == "webcam_anomaly" for r in flag.reasons))


class ReviewFlowTests(ProctorTestBase):
    def _flag(self):
        self.trip_flag()
        return CheatingFlag.all_objects.get(attempt=self.attempt)

    def test_lecturer_can_dismiss(self):
        flag = self._flag()
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("cbt-flag-dismiss", args=[flag.id]), {"notes": "Known accommodation."}
        )
        self.assertEqual(response.status_code, 200)
        flag.refresh_from_db()
        self.assertEqual(flag.status, CheatingFlagStatus.DISMISSED)
        self.assertEqual(flag.reviewed_by_id, self.lecturer.id)

    def test_lecturer_can_escalate_to_hod(self):
        flag = self._flag()
        mail.outbox = []
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("cbt-flag-escalate", args=[flag.id]), {"notes": "Please review."}
        )
        self.assertEqual(response.status_code, 200)
        flag.refresh_from_db()
        self.assertEqual(flag.status, CheatingFlagStatus.ESCALATED)
        self.assertEqual(flag.escalated_to_id, self.hod.id)
        self.assertTrue(any(self.hod.email in m.to for m in mail.outbox))

    def test_exam_officer_has_visibility_but_cannot_review(self):
        flag = self._flag()
        self.client.force_authenticate(self.exam_officer)
        self.assertEqual(
            self.client.get(reverse("cbt-attempt-flag", args=[self.attempt.id])).status_code, 200
        )
        self.assertEqual(
            self.client.post(reverse("cbt-flag-dismiss", args=[flag.id])).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unassigned_lecturer_cannot_review(self):
        flag = self._flag()
        with self.assertRaises(PermissionDenied):
            dismiss_flag(actor=self.other_lecturer, flag=flag)

    def test_review_never_changes_the_attempt(self):
        self.grade_attempt()
        before = (self.attempt.status, self.attempt.score)
        flag = self._flag()
        dismiss_flag(actor=self.lecturer, flag=flag)
        escalate_flag(actor=self.lecturer, flag=flag)
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.status, self.attempt.score), before)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class WebcamAccessTests(ProctorTestBase):
    def setUp(self):
        super().setUp()
        self.capture = create_webcam_capture(
            attempt=self.attempt,
            media=SimpleUploadedFile("snap.jpg", b"data", content_type="image/jpeg"),
            kind=WebcamCapture.Kind.SNAPSHOT,
            captured_at=timezone.now(),
        )
        self.url = reverse("cbt-attempt-webcam", args=[self.attempt.id])

    def _get_as(self, user):
        self.client.force_authenticate(user)
        return self.client.get(self.url)

    def test_authorized_staff_can_view(self):
        for user in (self.lecturer, self.hod, self.dean, self.exam_officer, self.school_admin):
            response = self._get_as(user)
            self.assertEqual(response.status_code, 200, user.role)
            self.assertEqual(len(response.data["data"]), 1)

    def test_students_including_subject_are_denied(self):
        self.assertEqual(self._get_as(self.student).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._get_as(self.other_student).status_code, status.HTTP_403_FORBIDDEN)

    def test_unassigned_lecturer_denied(self):
        self.assertEqual(self._get_as(self.other_lecturer).status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_staff_denied(self):
        inst2 = Institution.objects.create(name="Bells", code="bells")
        admin2 = _member(inst2, "a@bells.edu", Role.SCHOOL_ADMIN)
        self.assertEqual(self._get_as(admin2).status_code, status.HTTP_404_NOT_FOUND)

    def test_valid_auditor_token_can_view(self):
        _, raw = create_auditor_token(
            actor=self.school_admin,
            label="NUC",
            expires_at=timezone.now() + timedelta(days=1),
            programmes=[self.programme],
            sessions=[self.session],
        )
        self.client.force_authenticate(None)
        response = self.client.get(self.url, HTTP_X_AUDITOR_TOKEN=raw)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)

    def test_out_of_scope_auditor_denied(self):
        other_session = Session.all_objects.create(
            institution=self.inst, name="2024/2025", start_date="2024-10-01", end_date="2025-07-31"
        )
        _, raw = create_auditor_token(
            actor=self.school_admin,
            label="NUC",
            expires_at=timezone.now() + timedelta(days=1),
            sessions=[other_session],
        )
        self.client.force_authenticate(None)
        response = self.client.get(self.url, HTTP_X_AUDITOR_TOKEN=raw)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class WebcamRetentionModelTests(ProctorTestBase):
    def test_default_retention_is_ninety_days(self):
        self.assertEqual(self.inst.webcam_retention_days, 90)

    @override_settings(MEDIA_ROOT=TMP_MEDIA)
    def test_expires_at_follows_institution_config(self):
        self.inst.webcam_retention_days = 30
        self.inst.save(update_fields=["webcam_retention_days"])
        self.attempt.institution.refresh_from_db()
        capture = create_webcam_capture(
            attempt=self.attempt,
            media=SimpleUploadedFile("s.jpg", b"x", content_type="image/jpeg"),
            kind=WebcamCapture.Kind.SNAPSHOT,
            captured_at=timezone.now(),
        )
        expected = timezone.now() + timedelta(days=30)
        self.assertAlmostEqual(capture.expires_at, expected, delta=timedelta(minutes=1))


class IntegrityReportTests(ProctorTestBase):
    def test_report_aggregates_events_flag_webcam_and_timing(self):
        self.post_event(ProctorEventType.HEARTBEAT)
        self.post_event(ProctorEventType.FOCUS_LOSS, detail={"duration_seconds": 5})
        self.trip_flag()
        with override_settings(MEDIA_ROOT=TMP_MEDIA):
            create_webcam_capture(
                attempt=self.attempt,
                media=SimpleUploadedFile("s.jpg", b"x", content_type="image/jpeg"),
                kind=WebcamCapture.Kind.SNAPSHOT,
                captured_at=timezone.now(),
            )

        self.client.force_authenticate(self.lecturer)
        data = self.client.get(
            reverse("cbt-attempt-integrity-report", args=[self.attempt.id])
        ).data["data"]

        self.assertEqual(data["total_events"], 5)
        self.assertEqual(data["event_counts"][ProctorEventType.TAB_SWITCH], 3)
        self.assertEqual(data["flag"]["status"], CheatingFlagStatus.RAISED)
        self.assertEqual(data["webcam"]["count"], 1)
        self.assertIn("allowed_seconds", data["timing"])
        self.assertEqual(data["timing"]["heartbeat_count"], 1)

    def test_report_denied_to_students(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("cbt-attempt-integrity-report", args=[self.attempt.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
