"""Assessments tests: item creation guards, submissions with late flagging,
grading, weighted CA aggregation, and the feed into the results pipeline."""

import tempfile
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APITestCase

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Enrolment,
    Faculty,
    Role,
    Semester,
    Session,
    User,
)
from assessments.models import AssessmentGrade, AssessmentItem, Submission
from assessments.services import (
    aggregate_ca_for_student,
    create_item,
    grade_student,
    submit_file,
)
from results.services import create_draft_result, record_score
from tenancy.models import Institution

TMP_MEDIA = tempfile.mkdtemp(prefix="senet-test-media-")


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


def _pdf(name="essay.pdf", content=b"%PDF-1.4 senet test file"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class AssessmentsTestBase(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        self.faculty = Faculty.all_objects.create(institution=self.inst, name="Science", code="SCI")
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="Computer Science", code="CSC"
        )
        self.session = Session.all_objects.create(
            institution=self.inst,
            name="2025/2026",
            start_date="2025-10-01",
            end_date="2026-07-31",
            is_current=True,
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

        self.lecturer = _member(self.inst, "lect@veritas.edu", Role.LECTURER, department=self.dept)
        self.other_lecturer = _member(
            self.inst, "lect2@veritas.edu", Role.LECTURER, department=self.dept
        )
        self.student = _member(self.inst, "stud@veritas.edu", Role.STUDENT, department=self.dept)
        self.other_student = _member(
            self.inst, "stud2@veritas.edu", Role.STUDENT, department=self.dept
        )

        CourseAssignment.all_objects.create(
            institution=self.inst,
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
        )
        for student in (self.student, self.other_student):
            Enrolment.all_objects.create(
                institution=self.inst,
                student=student,
                course=self.course,
                session=self.session,
                semester=self.semester,
            )

    def make_item(self, title="Assignment 1", weight="20", max_score="20", due_in_days=7):
        return create_item(
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title=title,
            kind=AssessmentItem.Kind.ASSIGNMENT,
            max_score=Decimal(max_score),
            weight=Decimal(weight),
            due_date=timezone.now() + timedelta(days=due_in_days),
        )


class ItemCreationTests(AssessmentsTestBase):
    def test_assigned_lecturer_creates_item_via_api(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("assessment-item-list"),
            {
                "course": str(self.course.id),
                "session": str(self.session.id),
                "semester": str(self.semester.id),
                "title": "Midterm Test",
                "kind": "test",
                "max_score": "30",
                "weight": "15",
                "due_date": (timezone.now() + timedelta(days=7)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["kind"], "test")

    def test_unassigned_lecturer_cannot_create_item(self):
        self.client.force_authenticate(self.other_lecturer)
        response = self.client.post(
            reverse("assessment-item-list"),
            {
                "course": str(self.course.id),
                "session": str(self.session.id),
                "semester": str(self.semester.id),
                "title": "Sneaky Item",
                "kind": "assignment",
                "max_score": "10",
                "weight": "10",
                "due_date": (timezone.now() + timedelta(days=7)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(AssessmentItem.all_objects.count(), 0)

    def test_weights_cannot_exceed_ca_portion(self):
        self.make_item(title="A1", weight="25")
        # Institution CA portion defaults to 40; 25 + 20 would exceed it.
        with self.assertRaises(ValidationError):
            self.make_item(title="A2", weight="20")
        item = self.make_item(title="A2 smaller", weight="15")
        self.assertEqual(item.weight, Decimal("15"))

    def test_duplicate_title_rejected_per_term(self):
        self.make_item(title="Assignment 1")
        with self.assertRaises(ValidationError):
            self.make_item(title="Assignment 1")

    def test_students_see_items_for_enrolled_courses_only(self):
        self.make_item()
        outsider = _member(self.inst, "stud3@veritas.edu", Role.STUDENT)
        for user, expected in ((self.student, 1), (outsider, 0)):
            self.client.force_authenticate(user)
            response = self.client.get(reverse("assessment-item-list"))
            self.assertEqual(response.data["data"]["count"], expected)


class SubmissionTests(AssessmentsTestBase):
    def test_student_submits_before_deadline(self):
        item = self.make_item()
        self.client.force_authenticate(self.student)
        response = self.client.post(
            reverse("assessment-item-submit", args=[item.id]),
            {"file": _pdf()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertFalse(data["is_late"])
        self.assertEqual(data["original_filename"], "essay.pdf")

    def test_late_submission_flagged_not_blocked(self):
        item = self.make_item(due_in_days=-1)
        self.client.force_authenticate(self.student)
        response = self.client.post(
            reverse("assessment-item-submit", args=[item.id]),
            {"file": _pdf()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["is_late"])
        self.assertIn("late", response.data["message"])

    def test_disallowed_file_type_rejected(self):
        item = self.make_item()
        self.client.force_authenticate(self.student)
        upload = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        response = self.client.post(
            reverse("assessment-item-submit", args=[item.id]),
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(ASSESSMENT_MAX_FILE_BYTES=10)
    def test_oversized_file_rejected(self):
        item = self.make_item()
        self.client.force_authenticate(self.student)
        response = self.client.post(
            reverse("assessment-item-submit", args=[item.id]),
            {"file": _pdf(content=b"x" * 100)},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unenrolled_student_cannot_submit(self):
        item = self.make_item()
        outsider = _member(self.inst, "stud3@veritas.edu", Role.STUDENT)
        self.client.force_authenticate(outsider)
        response = self.client.post(
            reverse("assessment-item-submit", args=[item.id]),
            {"file": _pdf()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_resubmission_replaces_until_graded(self):
        item = self.make_item()
        first = submit_file(student=self.student, item=item, upload=_pdf("v1.pdf"))
        second = submit_file(student=self.student, item=item, upload=_pdf("v2.pdf"))
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.original_filename, "v2.pdf")
        self.assertEqual(Submission.all_objects.filter(item=item).count(), 1)

        grade_student(lecturer=self.lecturer, item=item, student=self.student, score=Decimal("15"))
        with self.assertRaises(ValidationError):
            submit_file(student=self.student, item=item, upload=_pdf("v3.pdf"))

    def test_lecturer_lists_submissions_for_assigned_item_only(self):
        item = self.make_item()
        submit_file(student=self.student, item=item, upload=_pdf())
        self.client.force_authenticate(self.lecturer)
        response = self.client.get(reverse("assessment-item-submissions", args=[item.id]))
        self.assertEqual(response.data["data"]["count"], 1)

        self.client.force_authenticate(self.other_lecturer)
        response = self.client.get(reverse("assessment-item-submissions", args=[item.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class GradingTests(AssessmentsTestBase):
    def test_lecturer_grades_with_feedback_via_api(self):
        item = self.make_item()
        submit_file(student=self.student, item=item, upload=_pdf())
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("assessment-item-grade", args=[item.id]),
            {
                "student": str(self.student.id),
                "score": "16",
                "feedback": "Good structure; weak conclusion.",
                "is_released": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["score"], "16.00")
        self.assertEqual(data["feedback"], "Good structure; weak conclusion.")
        self.assertIsNotNone(data["submission"])

    def test_grade_without_submission_allowed(self):
        item = self.make_item(title="In-class test")
        grade = grade_student(
            lecturer=self.lecturer, item=item, student=self.student, score=Decimal("12")
        )
        self.assertIsNone(grade.submission)

    def test_unassigned_lecturer_cannot_grade(self):
        item = self.make_item()
        with self.assertRaises(PermissionDenied):
            grade_student(
                lecturer=self.other_lecturer,
                item=item,
                student=self.student,
                score=Decimal("10"),
            )

    def test_score_above_item_max_rejected(self):
        item = self.make_item(max_score="20")
        with self.assertRaises(ValidationError):
            grade_student(
                lecturer=self.lecturer, item=item, student=self.student, score=Decimal("25")
            )

    def test_regrade_updates_single_row(self):
        item = self.make_item()
        grade_student(lecturer=self.lecturer, item=item, student=self.student, score=Decimal("10"))
        grade = grade_student(
            lecturer=self.lecturer, item=item, student=self.student, score=Decimal("14")
        )
        self.assertEqual(grade.score, Decimal("14"))
        self.assertEqual(AssessmentGrade.all_objects.filter(item=item).count(), 1)


class StudentVisibilityTests(AssessmentsTestBase):
    def test_student_sees_own_released_grade_only(self):
        item = self.make_item()
        grade_student(
            lecturer=self.lecturer,
            item=item,
            student=self.student,
            score=Decimal("15"),
            feedback="Released feedback",
            is_released=True,
        )
        grade_student(
            lecturer=self.lecturer,
            item=item,
            student=self.other_student,
            score=Decimal("18"),
            is_released=True,
        )

        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("assessment-my-grades"))
        rows = response.data["data"]["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["student"], self.student.id)
        self.assertEqual(rows[0]["feedback"], "Released feedback")

    def test_unreleased_grade_hidden_from_student(self):
        item = self.make_item()
        grade_student(lecturer=self.lecturer, item=item, student=self.student, score=Decimal("15"))
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("assessment-my-grades"))
        self.assertEqual(response.data["data"]["count"], 0)

        detail = self.client.get(reverse("assessment-item-detail", args=[item.id]))
        self.assertIsNone(detail.data["data"]["my_grade"])

    def test_item_detail_shows_own_submission_and_released_grade(self):
        item = self.make_item()
        submit_file(student=self.student, item=item, upload=_pdf())
        grade_student(
            lecturer=self.lecturer,
            item=item,
            student=self.student,
            score=Decimal("15"),
            is_released=True,
        )
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("assessment-item-detail", args=[item.id]))
        data = response.data["data"]
        self.assertEqual(data["my_submission"]["original_filename"], "essay.pdf")
        self.assertEqual(data["my_grade"]["score"], "15.00")


class CaAggregationTests(AssessmentsTestBase):
    def test_weighted_aggregation(self):
        # 15/20 on a weight-20 item -> 15 points; 30/40 on a weight-10 item -> 7.5.
        item1 = self.make_item(title="A1", weight="20", max_score="20")
        item2 = self.make_item(title="A2", weight="10", max_score="40")
        self.make_item(title="Ungraded", weight="10", max_score="10")
        grade_student(lecturer=self.lecturer, item=item1, student=self.student, score=Decimal("15"))
        grade_student(lecturer=self.lecturer, item=item2, student=self.student, score=Decimal("30"))
        total = aggregate_ca_for_student(self.course, self.session, self.semester, self.student)
        self.assertEqual(total, Decimal("22.50"))

    def test_student_with_no_grades_aggregates_to_zero(self):
        self.make_item()
        total = aggregate_ca_for_student(self.course, self.session, self.semester, self.student)
        self.assertEqual(total, Decimal("0.00"))

    def test_aggregation_feeds_results_pipeline(self):
        item = self.make_item(title="A1", weight="20", max_score="20")
        grade_student(lecturer=self.lecturer, item=item, student=self.student, score=Decimal("15"))
        result = create_draft_result(
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
        )
        row = record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            exam_score=Decimal("50"),
        )
        self.assertEqual(row.ca_score, Decimal("15.00"))
        self.assertEqual(row.total, Decimal("65.00"))
        self.assertEqual(row.grade, "B")

    def test_ca_summary_endpoint(self):
        item = self.make_item(title="A1", weight="20", max_score="20")
        grade_student(lecturer=self.lecturer, item=item, student=self.student, score=Decimal("10"))
        self.client.force_authenticate(self.lecturer)
        response = self.client.get(
            reverse("assessment-ca-summary"),
            {
                "course": str(self.course.id),
                "session": str(self.session.id),
                "semester": str(self.semester.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = {r["student"]: r["ca_score"] for r in response.data["data"]["results"]}
        self.assertEqual(rows[str(self.student.id)], "10.00")
        self.assertEqual(rows[str(self.other_student.id)], "0.00")

    def test_ca_summary_requires_assignment(self):
        self.make_item()
        self.client.force_authenticate(self.other_lecturer)
        response = self.client.get(
            reverse("assessment-ca-summary"),
            {
                "course": str(self.course.id),
                "session": str(self.session.id),
                "semester": str(self.semester.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TenantIsolationTests(AssessmentsTestBase):
    def setUp(self):
        super().setUp()
        self.foreign = Institution.objects.create(name="FUTO", code="futo")
        self.foreign_lecturer = _member(self.foreign, "lect@futo.edu", Role.LECTURER)
        self.foreign_student = _member(self.foreign, "stud@futo.edu", Role.STUDENT)
        self.item = self.make_item()

    def test_foreign_lecturer_sees_no_items(self):
        self.client.force_authenticate(self.foreign_lecturer)
        response = self.client.get(reverse("assessment-item-list"))
        self.assertEqual(response.data["data"]["count"], 0)

    def test_foreign_student_cannot_submit(self):
        self.client.force_authenticate(self.foreign_student)
        response = self.client.post(
            reverse("assessment-item-submit", args=[self.item.id]),
            {"file": _pdf()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_foreign_lecturer_cannot_read_submissions_or_grade(self):
        self.client.force_authenticate(self.foreign_lecturer)
        response = self.client.get(reverse("assessment-item-submissions", args=[self.item.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.post(
            reverse("assessment-item-grade", args=[self.item.id]),
            {"student": str(self.student.id), "score": "10"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
