"""CBT-as-CA-item tests: a graded CBT feeds the assessments CA aggregation,
weighting holds, manual and CBT items coexist, and scoping/tenant isolation hold."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
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
from assessments.models import AssessmentGrade, AssessmentItem
from assessments.services import aggregate_ca_for_student, create_item, grade_student
from cbt.ca import link_exam_to_ca_item
from cbt.models import Exam, Question, QuestionBank
from cbt.services import create_exam, save_answer, start_attempt, submit_attempt
from tenancy.models import Institution
from tenancy.scoping import set_current_institution


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=email.split("@")[0],
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class CaIntegrationBase(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas", code="veritas")
        self.faculty = Faculty.all_objects.create(institution=self.inst, name="Sci", code="SCI")
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="CS", code="CSC"
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
        self.other_lecturer = _member(self.inst, "lect2@veritas.edu", Role.LECTURER)
        self.student = _member(self.inst, "stud@veritas.edu", Role.STUDENT)
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

    def make_item(self, *, title, max_score, weight, kind=AssessmentItem.Kind.TEST):
        return create_item(
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title=title,
            kind=kind,
            max_score=Decimal(max_score),
            weight=Decimal(weight),
            due_date=timezone.now() + timedelta(days=7),
        )

    def make_cbt_exam(self, marks_list):
        bank = QuestionBank.all_objects.create(
            institution=self.inst,
            course=self.course,
            title=f"Bank {timezone.now().timestamp()}",
            created_by=self.lecturer,
        )
        for marks in marks_list:
            Question.all_objects.create(
                institution=self.inst,
                bank=bank,
                type="mcq",
                prompt="Q",
                options=["A", "B"],
                correct_answer=0,
                marks=Decimal(marks),
                created_by=self.lecturer,
            )
        now = timezone.now()
        return create_exam(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            banks=[bank],
            title="CBT CA",
            exam_type=Exam.ExamType.CA,
            duration_minutes=60,
            opens_at=now - timedelta(minutes=30),
            closes_at=now + timedelta(minutes=60),
            num_questions=len(marks_list),
            shuffle_questions=False,
            shuffle_options=False,
        )

    def take_exam(self, exam, correct_count, *, submit=True):
        attempt = start_attempt(student=self.student, exam=exam)
        for index, aq in enumerate(attempt.attempt_questions.order_by("position")):
            correct = index < correct_count
            save_answer(
                student=self.student,
                attempt=attempt,
                question_id=aq.question_id,
                raw_response=aq.option_order.index(0 if correct else 1),
            )
        if submit:
            submit_attempt(student=self.student, attempt=attempt)
            attempt.refresh_from_db()
        return attempt


class CbtFeedsCaTests(CaIntegrationBase):
    def test_full_score_feeds_scaled_grade_and_aggregation(self):
        item = self.make_item(title="Online Test", max_score=20, weight=30)
        exam = self.make_cbt_exam([10])
        link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=item)

        attempt = self.take_exam(exam, correct_count=1)
        self.assertEqual(attempt.score, Decimal("10.00"))

        grade = AssessmentGrade.all_objects.get(item=item, student=self.student)
        self.assertEqual(grade.score, Decimal("20.00"))  # 100% scaled onto max 20
        # (20/20) * 30 = 30 CA points.
        self.assertEqual(
            aggregate_ca_for_student(self.course, self.session, self.semester, self.student),
            Decimal("30.00"),
        )

    def test_partial_score_scales_and_weights_correctly(self):
        item = self.make_item(title="Online Test", max_score=20, weight=30)
        exam = self.make_cbt_exam([5, 5])
        link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=item)

        self.take_exam(exam, correct_count=1)  # 5 of 10 => 50%
        grade = AssessmentGrade.all_objects.get(item=item, student=self.student)
        self.assertEqual(grade.score, Decimal("10.00"))  # 50% of max 20
        self.assertEqual(
            aggregate_ca_for_student(self.course, self.session, self.semester, self.student),
            Decimal("15.00"),  # (10/20) * 30
        )

    def test_manual_and_cbt_items_coexist(self):
        manual = self.make_item(title="Assignment", max_score=10, weight=10)
        grade_student(lecturer=self.lecturer, item=manual, student=self.student, score=Decimal("8"))

        cbt_item = self.make_item(title="Online Test", max_score=20, weight=30)
        exam = self.make_cbt_exam([10])
        link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=cbt_item)
        self.take_exam(exam, correct_count=1)

        # manual: (8/10)*10 = 8 ; cbt: (20/20)*30 = 30 ; total 38.
        self.assertEqual(
            aggregate_ca_for_student(self.course, self.session, self.semester, self.student),
            Decimal("38.00"),
        )

    def test_score_flows_only_when_graded(self):
        item = self.make_item(title="Online Test", max_score=20, weight=30)
        exam = self.make_cbt_exam([10])
        link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=item)

        self.take_exam(exam, correct_count=1, submit=False)  # in progress
        self.assertFalse(
            AssessmentGrade.all_objects.filter(item=item, student=self.student).exists()
        )

        attempt = start_attempt(student=self.student, exam=exam)
        submit_attempt(student=self.student, attempt=attempt)
        self.assertTrue(
            AssessmentGrade.all_objects.filter(item=item, student=self.student).exists()
        )

    def test_linking_backfills_already_graded_attempts(self):
        item = self.make_item(title="Online Test", max_score=20, weight=30)
        exam = self.make_cbt_exam([10])
        self.take_exam(exam, correct_count=1)  # graded before linking
        self.assertFalse(
            AssessmentGrade.all_objects.filter(item=item, student=self.student).exists()
        )

        link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=item)
        grade = AssessmentGrade.all_objects.get(item=item, student=self.student)
        self.assertEqual(grade.score, Decimal("20.00"))


class LinkScopingTests(CaIntegrationBase):
    def test_only_assigned_lecturer_can_link(self):
        item = self.make_item(title="Online Test", max_score=20, weight=30)
        exam = self.make_cbt_exam([10])
        with self.assertRaises(PermissionDenied):
            link_exam_to_ca_item(actor=self.other_lecturer, exam=exam, item=item)

    def test_cannot_link_mismatched_term(self):
        other_session = Session.all_objects.create(
            institution=self.inst, name="2024/2025", start_date="2024-10-01", end_date="2025-07-31"
        )
        other_sem = Semester.all_objects.create(
            institution=self.inst,
            session=other_session,
            name="First",
            start_date="2024-10-01",
            end_date="2025-02-28",
        )
        item = AssessmentItem.all_objects.create(
            institution=self.inst,
            course=self.course,
            session=other_session,
            semester=other_sem,
            created_by=self.lecturer,
            title="Other term",
            kind=AssessmentItem.Kind.TEST,
            max_score=Decimal("20"),
            weight=Decimal("30"),
            due_date=timezone.now() + timedelta(days=7),
        )
        exam = self.make_cbt_exam([10])
        with self.assertRaises(ValidationError):
            link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=item)

    def test_cannot_link_cross_tenant_item(self):
        inst2 = Institution.objects.create(name="Bells", code="bells")
        fac2 = Faculty.all_objects.create(institution=inst2, name="E", code="ENG")
        dept2 = Department.all_objects.create(
            institution=inst2, faculty=fac2, name="EEE", code="EEE"
        )
        sess2 = Session.all_objects.create(
            institution=inst2, name="2025/2026", start_date="2025-10-01", end_date="2026-07-31"
        )
        sem2 = Semester.all_objects.create(
            institution=inst2,
            session=sess2,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        course2 = Course.all_objects.create(
            institution=inst2, department=dept2, code="EEE 101", title="C", credit_units=3
        )
        foreign_item = AssessmentItem.all_objects.create(
            institution=inst2,
            course=course2,
            session=sess2,
            semester=sem2,
            created_by=_member(inst2, "l@bells.edu", Role.LECTURER),
            title="Foreign",
            kind=AssessmentItem.Kind.TEST,
            max_score=Decimal("20"),
            weight=Decimal("30"),
            due_date=timezone.now() + timedelta(days=7),
        )
        exam = self.make_cbt_exam([10])
        with self.assertRaises(ValidationError):
            link_exam_to_ca_item(actor=self.lecturer, exam=exam, item=foreign_item)
