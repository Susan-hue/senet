"""CBT engine tests.

Focus areas, all exercised below:
* assembly draws + randomizes per student and is stable across reloads
* the student question payload never carries a correct answer
* the server deadline is authoritative — saves/submits are refused after it
* answer auto-save is idempotent
* objective auto-grading is correct (and independent of option shuffling)
* short answers are queued, never auto-graded
* only enrolled students in the window may attempt; only the assigned lecturer
  (or admins in scope) may author; tenant isolation holds
"""

import threading
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
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
from cbt.grading import grade_answer, normalize_text
from cbt.models import (
    Answer,
    AttemptStatus,
    Exam,
    ExamAttempt,
    Question,
    QuestionBank,
    QuestionType,
)
from cbt.services import (
    create_exam,
    create_question,
    create_question_bank,
    finalize_expired_attempts,
    save_answer,
    save_answers_batch,
    start_attempt,
    submit_attempt,
)
from tenancy.models import Institution
from tenancy.scoping import set_current_institution


def answer_all_objective_correct(student, attempt):
    """Save the correct answer for every objective question in a frozen paper,
    mapping through each question's shuffled option order."""
    for aq in attempt.attempt_questions.select_related("question"):
        q = aq.question
        if q.type == QuestionType.MCQ:
            raw = aq.option_order.index(q.correct_answer)
        elif q.type == QuestionType.MULTI:
            raw = [aq.option_order.index(i) for i in q.correct_answer]
        elif q.type == QuestionType.TRUE_FALSE:
            raw = q.correct_answer
        elif q.type == QuestionType.FILL_BLANK:
            raw = q.correct_answer[0]
        else:
            continue
        save_answer(student=student, attempt=attempt, question_id=q.id, raw_response=raw)


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class CbtTestBase(APITestCase):
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
        self.outsider = _member(self.inst, "nope@veritas.edu", Role.STUDENT, department=self.dept)

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

        self.now = timezone.now()
        self.bank = QuestionBank.all_objects.create(
            institution=self.inst, course=self.course, title="Pool", created_by=self.lecturer
        )
        # Bind the tenant to the thread, exactly as a request would, so scoped
        # (``objects``) reads and reverse accessors resolve in direct service tests.
        set_current_institution(self.inst)

    # -- builders ----------------------------------------------------------- #

    def add_mcq(self, correct_index=0, options=None, marks="1", bank=None):
        return Question.all_objects.create(
            institution=self.inst,
            bank=bank or self.bank,
            type=QuestionType.MCQ,
            prompt="Pick one",
            options=options or ["A", "B", "C", "D"],
            correct_answer=correct_index,
            marks=Decimal(marks),
            created_by=self.lecturer,
        )

    def add_question(
        self, qtype, *, options=None, correct=None, marks="1", manual=False, bank=None
    ):
        return Question.all_objects.create(
            institution=self.inst,
            bank=bank or self.bank,
            type=qtype,
            prompt="Q",
            options=options or [],
            correct_answer=correct,
            marks=Decimal(marks),
            requires_manual_grading=manual,
            created_by=self.lecturer,
        )

    def make_exam(
        self,
        *,
        num_questions=4,
        shuffle_questions=True,
        shuffle_options=True,
        opens_in=-60,
        closes_in=120,
        duration=60,
        banks=None,
        actor=None,
    ):
        return create_exam(
            actor=actor or self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            banks=banks or [self.bank],
            title="Midterm",
            exam_type=Exam.ExamType.MAIN,
            duration_minutes=duration,
            opens_at=self.now + timedelta(minutes=opens_in),
            closes_at=self.now + timedelta(minutes=closes_in),
            num_questions=num_questions,
            shuffle_questions=shuffle_questions,
            shuffle_options=shuffle_options,
            pass_mark=Decimal("50"),
        )

    def fill_pool(self, n=10):
        for _ in range(n):
            self.add_mcq(correct_index=0)

    def expire(self, attempt):
        """Move the stored server deadline into the past (simulate time passing)
        without touching anything the client controls."""
        ExamAttempt.all_objects.filter(pk=attempt.pk).update(
            deadline=timezone.now() - timedelta(minutes=1)
        )
        attempt.refresh_from_db()


class AssemblyTests(CbtTestBase):
    def test_assembly_draws_the_configured_number_from_the_pool(self):
        self.fill_pool(10)
        exam = self.make_exam(num_questions=6)
        attempt = start_attempt(student=self.student, exam=exam)
        rows = list(attempt.attempt_questions.all())
        self.assertEqual(len(rows), 6)
        pool_ids = set(Question.all_objects.filter(bank=self.bank).values_list("id", flat=True))
        self.assertTrue({r.question_id for r in rows} <= pool_ids)

    def test_paper_is_stable_across_reloads(self):
        self.fill_pool(10)
        exam = self.make_exam(num_questions=6)
        first = start_attempt(student=self.student, exam=exam)
        layout1 = [
            (r.question_id, r.option_order) for r in first.attempt_questions.order_by("position")
        ]
        # Resume: same attempt, same frozen paper.
        second = start_attempt(student=self.student, exam=exam)
        layout2 = [
            (r.question_id, r.option_order) for r in second.attempt_questions.order_by("position")
        ]
        self.assertEqual(first.id, second.id)
        self.assertEqual(layout1, layout2)

    def test_paper_differs_across_students(self):
        self.fill_pool(10)
        exam = self.make_exam(num_questions=6)
        orderings = set()
        for i in range(6):
            student = _member(self.inst, f"s{i}@veritas.edu", Role.STUDENT)
            Enrolment.all_objects.create(
                institution=self.inst,
                student=student,
                course=self.course,
                session=self.session,
                semester=self.semester,
            )
            attempt = start_attempt(student=student, exam=exam)
            ordering = tuple(
                attempt.attempt_questions.order_by("position").values_list("question_id", flat=True)
            )
            orderings.add(ordering)
        # Randomized per student — vanishingly unlikely all six coincide.
        self.assertGreater(len(orderings), 1)

    def test_option_order_is_a_permutation_of_all_options(self):
        self.add_mcq(correct_index=2, options=["W", "X", "Y", "Z"])
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        row = attempt.attempt_questions.get()
        self.assertEqual(sorted(row.option_order), [0, 1, 2, 3])


class AnswerLeakTests(CbtTestBase):
    STUDENT_KEYS = {"question", "type", "prompt", "marks", "position", "options"}

    def test_student_payload_carries_no_correct_answer(self):
        self.fill_pool(5)
        exam = self.make_exam(num_questions=5)
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse("cbt-exam-start", args=[exam.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        questions = response.data["data"]["questions"]
        self.assertEqual(len(questions), 5)
        for q in questions:
            self.assertEqual(set(q.keys()), self.STUDENT_KEYS)
        # Belt and braces: the serialized bytes never mention the answer field.
        self.assertNotIn(b"correct_answer", response.content)

    def test_resume_payload_also_hides_answers(self):
        self.fill_pool(3)
        exam = self.make_exam(num_questions=3)
        attempt = start_attempt(student=self.student, exam=exam)
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("cbt-attempt-detail", args=[attempt.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(b"correct_answer", response.content)
        for q in response.data["data"]["questions"]:
            self.assertEqual(set(q.keys()), self.STUDENT_KEYS)


class TimingTests(CbtTestBase):
    def test_deadline_is_server_computed_from_duration(self):
        self.fill_pool(2)
        exam = self.make_exam(num_questions=2, duration=30, closes_in=600)
        attempt = start_attempt(student=self.student, exam=exam)
        expected = attempt.started_at + timedelta(minutes=30)
        self.assertAlmostEqual(attempt.deadline, expected, delta=timedelta(seconds=2))

    def test_deadline_is_capped_by_exam_close_time(self):
        self.fill_pool(2)
        # Duration would run past close; the close time wins.
        exam = self.make_exam(num_questions=2, duration=600, closes_in=10)
        attempt = start_attempt(student=self.student, exam=exam)
        self.assertEqual(attempt.deadline, exam.closes_at)

    def test_saves_are_rejected_after_the_deadline(self):
        self.fill_pool(2)
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        question_id = attempt.attempt_questions.first().question_id
        # Simulate the clock passing the server deadline.
        ExamAttempt.all_objects.filter(pk=attempt.pk).update(
            deadline=self.now - timedelta(minutes=1)
        )
        attempt.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            save_answer(
                student=self.student, attempt=attempt, question_id=question_id, raw_response=0
            )
        attempt.refresh_from_db()
        # The lapsed attempt is finalized by the server, not left open.
        self.assertIn(attempt.status, {AttemptStatus.AUTO_SUBMITTED, AttemptStatus.GRADED})

    def test_client_cannot_extend_time_via_the_api(self):
        self.fill_pool(2)
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        server_deadline = attempt.deadline
        question_id = attempt.attempt_questions.first().question_id
        ExamAttempt.all_objects.filter(pk=attempt.pk).update(
            deadline=self.now - timedelta(minutes=1)
        )
        self.client.force_authenticate(self.student)
        response = self.client.post(
            reverse("cbt-attempt-answer", args=[attempt.id]),
            {"question": str(question_id), "response": 0},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        attempt.refresh_from_db()
        # The deadline the client saw is not the server's, and cannot be pushed out.
        self.assertLess(attempt.deadline, server_deadline)


class AutoSaveTests(CbtTestBase):
    def test_saving_the_same_answer_twice_stores_one_row(self):
        self.add_mcq(correct_index=1)
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        aq = attempt.attempt_questions.get()
        save_answer(
            student=self.student, attempt=attempt, question_id=aq.question_id, raw_response=0
        )
        save_answer(
            student=self.student, attempt=attempt, question_id=aq.question_id, raw_response=0
        )
        self.assertEqual(
            Answer.all_objects.filter(attempt=attempt, question_id=aq.question_id).count(), 1
        )

    def test_resaving_updates_the_stored_response(self):
        self.add_mcq(correct_index=1, options=["A", "B", "C"])
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        aq = attempt.attempt_questions.get()
        save_answer(
            student=self.student, attempt=attempt, question_id=aq.question_id, raw_response=0
        )
        save_answer(
            student=self.student, attempt=attempt, question_id=aq.question_id, raw_response=1
        )
        answer = Answer.all_objects.get(attempt=attempt, question_id=aq.question_id)
        # Stored as the ORIGINAL option index (display position 1 -> its original).
        self.assertEqual(answer.response, aq.option_order[1])

    def test_answer_cannot_target_a_question_outside_the_paper(self):
        self.fill_pool(2)
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        # A pool question that was not drawn into this attempt.
        drawn = set(attempt.attempt_questions.values_list("question_id", flat=True))
        stray = Question.all_objects.filter(bank=self.bank).exclude(id__in=drawn).first()
        with self.assertRaises(NotFound):
            save_answer(student=self.student, attempt=attempt, question_id=stray.id, raw_response=0)


class GradingTests(CbtTestBase):
    def _answer_correctly(self, attempt):
        for aq in attempt.attempt_questions.select_related("question"):
            q = aq.question
            if q.type == QuestionType.MCQ:
                pos = aq.option_order.index(q.correct_answer)
                save_answer(
                    student=self.student, attempt=attempt, question_id=q.id, raw_response=pos
                )
            elif q.type == QuestionType.MULTI:
                positions = [aq.option_order.index(i) for i in q.correct_answer]
                save_answer(
                    student=self.student, attempt=attempt, question_id=q.id, raw_response=positions
                )
            elif q.type == QuestionType.TRUE_FALSE:
                save_answer(
                    student=self.student,
                    attempt=attempt,
                    question_id=q.id,
                    raw_response=q.correct_answer,
                )
            elif q.type == QuestionType.FILL_BLANK:
                save_answer(
                    student=self.student,
                    attempt=attempt,
                    question_id=q.id,
                    raw_response=q.correct_answer[0].upper(),  # exercise normalization
                )

    def test_objective_auto_grading_is_correct_and_shuffle_independent(self):
        self.add_mcq(correct_index=2, options=["A", "B", "C", "D"], marks="2")
        self.add_question(
            QuestionType.MULTI, options=["a", "b", "c", "d"], correct=[0, 2], marks="3"
        )
        self.add_question(QuestionType.TRUE_FALSE, correct=True, marks="1")
        self.add_question(QuestionType.FILL_BLANK, correct=["Paris"], marks="2")
        exam = self.make_exam(num_questions=4)
        attempt = start_attempt(student=self.student, exam=exam)
        self._answer_correctly(attempt)
        submit_attempt(student=self.student, attempt=attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AttemptStatus.GRADED)
        self.assertEqual(attempt.score, Decimal("8.00"))
        self.assertEqual(attempt.max_score, Decimal("8.00"))
        for answer in Answer.all_objects.filter(attempt=attempt):
            self.assertTrue(answer.is_correct)

    def test_wrong_and_blank_answers_lose_marks(self):
        mcq = self.add_mcq(correct_index=0, marks="2")
        self.add_question(QuestionType.TRUE_FALSE, correct=True, marks="1")  # left blank
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        aq = attempt.attempt_questions.get(question=mcq)
        wrong_pos = aq.option_order.index(1)  # not the correct original index 0
        save_answer(
            student=self.student, attempt=attempt, question_id=mcq.id, raw_response=wrong_pos
        )
        submit_attempt(student=self.student, attempt=attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, Decimal("0.00"))
        self.assertEqual(attempt.max_score, Decimal("3.00"))

    def test_multi_select_requires_exact_match(self):
        q = self.add_question(
            QuestionType.MULTI, options=["a", "b", "c"], correct=[0, 1], marks="4"
        )
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        aq = attempt.attempt_questions.get()
        # Only one of the two correct options selected — no partial credit.
        partial = [aq.option_order.index(0)]
        save_answer(student=self.student, attempt=attempt, question_id=q.id, raw_response=partial)
        submit_attempt(student=self.student, attempt=attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, Decimal("0.00"))

    def test_pure_objective_grades_to_pass_flag(self):
        self.add_mcq(correct_index=0, marks="1")
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        aq = attempt.attempt_questions.get()
        save_answer(
            student=self.student,
            attempt=attempt,
            question_id=aq.question_id,
            raw_response=aq.option_order.index(0),
        )
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse("cbt-attempt-submit", args=[attempt.id]))
        self.assertEqual(response.data["data"]["status"], AttemptStatus.GRADED)
        self.assertTrue(response.data["data"]["passed"])


class ShortAnswerTests(CbtTestBase):
    def test_short_answer_is_queued_not_auto_graded(self):
        mcq = self.add_mcq(correct_index=0, marks="1")
        short = self.add_question(QuestionType.SHORT_ANSWER, marks="5", manual=True)
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        mcq_aq = attempt.attempt_questions.get(question=mcq)
        save_answer(
            student=self.student,
            attempt=attempt,
            question_id=mcq.id,
            raw_response=mcq_aq.option_order.index(0),
        )
        save_answer(
            student=self.student,
            attempt=attempt,
            question_id=short.id,
            raw_response="A thoughtful essay.",
        )
        submit_attempt(student=self.student, attempt=attempt)
        attempt.refresh_from_db()

        self.assertEqual(attempt.status, AttemptStatus.SUBMITTED)  # not GRADED
        self.assertTrue(attempt.requires_manual_grading)
        self.assertEqual(attempt.score, Decimal("1.00"))  # objective only
        self.assertEqual(attempt.max_score, Decimal("6.00"))
        short_answer = Answer.all_objects.get(attempt=attempt, question=short)
        self.assertIsNone(short_answer.awarded_marks)
        self.assertIsNone(short_answer.is_correct)

    def test_grade_answer_returns_none_for_short_answer(self):
        short = self.add_question(QuestionType.SHORT_ANSWER, marks="5", manual=True)
        self.assertIsNone(grade_answer(short, "anything"))

    def test_normalize_text_is_case_and_space_insensitive(self):
        self.assertEqual(normalize_text("  The   Answer "), normalize_text("the answer"))


class AttemptGuardTests(CbtTestBase):
    def test_non_enrolled_student_cannot_attempt(self):
        self.fill_pool(1)
        exam = self.make_exam(num_questions=1)
        with self.assertRaises(PermissionDenied):
            start_attempt(student=self.outsider, exam=exam)

    def test_cannot_attempt_before_the_window_opens(self):
        self.fill_pool(1)
        exam = self.make_exam(num_questions=1, opens_in=60, closes_in=120)
        with self.assertRaises(PermissionDenied):
            start_attempt(student=self.student, exam=exam)

    def test_cannot_attempt_after_the_window_closes(self):
        self.fill_pool(1)
        exam = self.make_exam(num_questions=1, opens_in=-120, closes_in=-60)
        with self.assertRaises(PermissionDenied):
            start_attempt(student=self.student, exam=exam)

    def test_a_student_gets_a_single_attempt(self):
        self.fill_pool(2)
        exam = self.make_exam(num_questions=2)
        first = start_attempt(student=self.student, exam=exam)
        second = start_attempt(student=self.student, exam=exam)
        self.assertEqual(first.id, second.id)
        self.assertEqual(ExamAttempt.all_objects.filter(exam=exam, student=self.student).count(), 1)


class AuthoringAccessTests(CbtTestBase):
    def test_only_assigned_lecturer_can_create_an_exam(self):
        self.fill_pool(2)
        with self.assertRaises(PermissionDenied):
            self.make_exam(num_questions=1, actor=self.other_lecturer)

    def test_unassigned_lecturer_cannot_create_a_bank(self):
        with self.assertRaises(PermissionDenied):
            create_question_bank(actor=self.other_lecturer, course=self.course, title="Sneaky")

    def test_unassigned_lecturer_cannot_add_questions(self):
        with self.assertRaises(PermissionDenied):
            create_question(
                actor=self.other_lecturer,
                bank=self.bank,
                type=QuestionType.MCQ,
                prompt="Q",
                options=["A", "B"],
                correct_answer=0,
                marks=Decimal("1"),
            )

    def test_assigned_lecturer_can_author_end_to_end(self):
        bank = create_question_bank(actor=self.lecturer, course=self.course, title="Authored")
        question = create_question(
            actor=self.lecturer,
            bank=bank,
            type=QuestionType.MCQ,
            prompt="2+2?",
            options=["3", "4", "5"],
            correct_answer=1,
            marks=Decimal("1"),
        )
        self.assertFalse(question.requires_manual_grading)
        exam = self.make_exam(num_questions=1, banks=[bank])
        self.assertEqual(exam.banks.count(), 1)

    def test_student_cannot_reach_manager_endpoints(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("cbt-bank-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_short_answer_authoring_flags_manual_grading(self):
        bank = create_question_bank(actor=self.lecturer, course=self.course, title="Essays")
        question = create_question(
            actor=self.lecturer,
            bank=bank,
            type=QuestionType.SHORT_ANSWER,
            prompt="Discuss.",
            marks=Decimal("10"),
        )
        self.assertTrue(question.requires_manual_grading)
        self.assertIsNone(question.correct_answer)


class TenantIsolationTests(CbtTestBase):
    def setUp(self):
        super().setUp()
        # A second, fully separate tenant with its own exam.
        self.inst2 = Institution.objects.create(name="Bells University", code="bells")
        fac2 = Faculty.all_objects.create(institution=self.inst2, name="Eng", code="ENG")
        dept2 = Department.all_objects.create(
            institution=self.inst2, faculty=fac2, name="EEE", code="EEE"
        )
        sess2 = Session.all_objects.create(
            institution=self.inst2, name="2025/2026", start_date="2025-10-01", end_date="2026-07-31"
        )
        sem2 = Semester.all_objects.create(
            institution=self.inst2,
            session=sess2,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        course2 = Course.all_objects.create(
            institution=self.inst2,
            department=dept2,
            code="EEE 101",
            title="Circuits",
            credit_units=3,
        )
        lect2 = _member(self.inst2, "l@bells.edu", Role.LECTURER, department=dept2)
        CourseAssignment.all_objects.create(
            institution=self.inst2, lecturer=lect2, course=course2, session=sess2, semester=sem2
        )
        bank2 = QuestionBank.all_objects.create(
            institution=self.inst2, course=course2, title="B2", created_by=lect2
        )
        Question.all_objects.create(
            institution=self.inst2,
            bank=bank2,
            type=QuestionType.MCQ,
            prompt="Q",
            options=["A", "B"],
            correct_answer=0,
            marks=Decimal("1"),
            created_by=lect2,
        )
        self.exam2 = create_exam(
            actor=lect2,
            course=course2,
            session=sess2,
            semester=sem2,
            banks=[bank2],
            title="Other Tenant Exam",
            exam_type=Exam.ExamType.MAIN,
            duration_minutes=60,
            opens_at=self.now - timedelta(minutes=60),
            closes_at=self.now + timedelta(minutes=60),
            num_questions=1,
        )

    def test_other_tenants_exam_is_invisible_in_listing(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.get(reverse("cbt-exam-list"))
        ids = {row["id"] for row in response.data["data"]["results"]}
        self.assertNotIn(str(self.exam2.id), ids)

    def test_other_tenants_exam_detail_is_404(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.get(reverse("cbt-exam-detail", args=[self.exam2.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_cannot_start_another_tenants_exam(self):
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse("cbt-exam-start", args=[self.exam2.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(ExamAttempt.all_objects.filter(exam=self.exam2).exists())


class ResumeTests(CbtTestBase):
    """Disconnection resilience: reconnect and resume exactly where you were."""

    def _layout(self, attempt):
        return [
            (str(r.question_id), list(r.option_order))
            for r in attempt.attempt_questions.order_by("position")
        ]

    def test_resume_returns_state_time_remaining_and_no_reshuffle_or_reset(self):
        self.fill_pool(5)
        exam = self.make_exam(num_questions=5, duration=60, closes_in=600)
        attempt = start_attempt(student=self.student, exam=exam)
        layout = self._layout(attempt)
        deadline = attempt.deadline
        first_aq = attempt.attempt_questions.order_by("position").first()
        save_answer(
            student=self.student, attempt=attempt, question_id=first_aq.question_id, raw_response=0
        )

        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("cbt-attempt-detail", args=[attempt.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]

        # Same frozen paper in the same order — never re-drawn on resume.
        resumed_layout = [(q["question"], q["options"]) for q in data["questions"]]
        self.assertEqual([qid for qid, _ in resumed_layout], [qid for qid, _ in layout])
        # The saved answer is still there.
        self.assertEqual(len(data["answers"]), 1)
        self.assertEqual(str(data["answers"][0]["question"]), str(first_aq.question_id))
        # Authoritative time remaining, computed from the stored deadline.
        remaining = data["attempt"]["time_remaining_seconds"]
        self.assertGreater(remaining, 3500)
        self.assertLessEqual(remaining, 3600)
        # The timer was not reset: the stored deadline is unchanged.
        attempt.refresh_from_db()
        self.assertEqual(attempt.deadline, deadline)

    def test_repeated_resumes_are_identical(self):
        self.fill_pool(4)
        exam = self.make_exam(num_questions=4)
        attempt = start_attempt(student=self.student, exam=exam)
        self.client.force_authenticate(self.student)
        first = self.client.get(reverse("cbt-attempt-detail", args=[attempt.id])).data["data"]
        second = self.client.get(reverse("cbt-attempt-detail", args=[attempt.id])).data["data"]
        self.assertEqual(
            [q["question"] for q in first["questions"]],
            [q["question"] for q in second["questions"]],
        )
        self.assertEqual(
            [q["options"] for q in first["questions"]],
            [q["options"] for q in second["questions"]],
        )

    def test_time_remaining_is_zero_once_finalized(self):
        self.fill_pool(2)
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        self.expire(attempt)
        self.client.force_authenticate(self.student)
        data = self.client.get(reverse("cbt-attempt-detail", args=[attempt.id])).data["data"]
        # Opportunistic finalize on resume (defense in depth) + zero time left.
        self.assertNotEqual(data["attempt"]["status"], AttemptStatus.IN_PROGRESS)
        self.assertEqual(data["attempt"]["time_remaining_seconds"], 0)


class FinalizerTests(CbtTestBase):
    """The periodic auto-submit safety net."""

    def _objective_attempt(self):
        self.add_mcq(correct_index=0, marks="2")
        self.add_mcq(correct_index=1, marks="2")
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        answer_all_objective_correct(self.student, attempt)
        return attempt

    def test_finalizer_auto_submits_and_grades_past_deadline(self):
        attempt = self._objective_attempt()
        self.expire(attempt)
        # Student never submitted; the sweep settles it.
        finalized = finalize_expired_attempts()
        self.assertEqual(finalized, 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AttemptStatus.GRADED)
        self.assertEqual(attempt.score, Decimal("4.00"))
        self.assertEqual(attempt.max_score, Decimal("4.00"))
        self.assertIsNotNone(attempt.submitted_at)

    def test_finalizer_uses_auto_submitted_when_manual_pending(self):
        mcq = self.add_mcq(correct_index=0, marks="1")
        short = self.add_question(QuestionType.SHORT_ANSWER, marks="5", manual=True)
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        mcq_aq = attempt.attempt_questions.get(question=mcq)
        save_answer(
            student=self.student,
            attempt=attempt,
            question_id=mcq.id,
            raw_response=mcq_aq.option_order.index(0),
        )
        save_answer(
            student=self.student, attempt=attempt, question_id=short.id, raw_response="Essay"
        )
        self.expire(attempt)
        finalize_expired_attempts()
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AttemptStatus.AUTO_SUBMITTED)
        self.assertTrue(attempt.requires_manual_grading)
        self.assertEqual(attempt.score, Decimal("1.00"))
        self.assertIsNone(Answer.all_objects.get(attempt=attempt, question=short).awarded_marks)

    def test_finalizer_is_idempotent(self):
        attempt = self._objective_attempt()
        self.expire(attempt)
        self.assertEqual(finalize_expired_attempts(), 1)
        attempt.refresh_from_db()
        first_submitted, first_score = attempt.submitted_at, attempt.score
        # A second sweep must not re-grade or re-timestamp.
        self.assertEqual(finalize_expired_attempts(), 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.submitted_at, first_submitted)
        self.assertEqual(attempt.score, first_score)

    def test_finalizer_ignores_attempts_within_deadline(self):
        attempt = self._objective_attempt()
        self.assertEqual(finalize_expired_attempts(), 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AttemptStatus.IN_PROGRESS)


class BatchSaveTests(CbtTestBase):
    def test_batch_is_idempotent_and_converges_to_last_value(self):
        q1 = self.add_mcq(correct_index=0, options=["A", "B", "C"])
        q2 = self.add_question(QuestionType.TRUE_FALSE, correct=True)
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        aq1 = attempt.attempt_questions.get(question=q1)

        items = [
            {"question": q1.id, "response": aq1.option_order.index(0)},
            {"question": q1.id, "response": aq1.option_order.index(1)},  # later wins
            {"question": q2.id, "response": True},
        ]
        save_answers_batch(student=self.student, attempt=attempt, items=items)
        self.assertEqual(Answer.all_objects.filter(attempt=attempt).count(), 2)
        self.assertEqual(Answer.all_objects.get(attempt=attempt, question=q1).response, 1)

        # Replaying the identical batch changes nothing (idempotent sync).
        save_answers_batch(student=self.student, attempt=attempt, items=items)
        self.assertEqual(Answer.all_objects.filter(attempt=attempt).count(), 2)
        self.assertEqual(Answer.all_objects.get(attempt=attempt, question=q1).response, 1)

    def test_batch_sync_via_api(self):
        self.add_mcq(correct_index=0, options=["A", "B"])
        self.add_mcq(correct_index=1, options=["A", "B"])
        exam = self.make_exam(num_questions=2)
        attempt = start_attempt(student=self.student, exam=exam)
        rows = list(attempt.attempt_questions.select_related("question"))
        payload = {"answers": [{"question": str(r.question_id), "response": 0} for r in rows]}
        self.client.force_authenticate(self.student)
        response = self.client.post(
            reverse("cbt-attempt-answers", args=[attempt.id]), payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Answer.all_objects.filter(attempt=attempt).count(), 2)

    def test_batch_is_rejected_after_the_deadline(self):
        q1 = self.add_mcq(correct_index=0)
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        self.expire(attempt)
        with self.assertRaises(PermissionDenied):
            save_answers_batch(
                student=self.student,
                attempt=attempt,
                items=[{"question": q1.id, "response": 0}],
            )
        # Nothing was written, and the lapsed attempt is finalized.
        self.assertEqual(Answer.all_objects.filter(attempt=attempt).count(), 0)
        attempt.refresh_from_db()
        self.assertIn(attempt.status, {AttemptStatus.AUTO_SUBMITTED, AttemptStatus.GRADED})

    def test_rapid_repeated_single_saves_store_one_row(self):
        q1 = self.add_mcq(correct_index=1, options=["A", "B", "C"])
        exam = self.make_exam(num_questions=1)
        attempt = start_attempt(student=self.student, exam=exam)
        for _ in range(5):
            save_answer(student=self.student, attempt=attempt, question_id=q1.id, raw_response=2)
        self.assertEqual(Answer.all_objects.filter(attempt=attempt, question=q1).count(), 1)


@skipUnless(
    connection.vendor == "postgresql",
    "FOR UPDATE SKIP LOCKED is a no-op on SQLite; real row locks need Postgres",
)
class ConcurrentFinalizeTests(TransactionTestCase):
    """Two finalizer runs racing on the same expired attempt must finalize it
    exactly once — the row lock + status guard serialize them."""

    def setUp(self):
        self.inst = Institution.objects.create(name="Loyola University", code="loyola")
        fac = Faculty.all_objects.create(institution=self.inst, name="Sci", code="SCI")
        dept = Department.all_objects.create(
            institution=self.inst, faculty=fac, name="CS", code="CS"
        )
        sess = Session.all_objects.create(
            institution=self.inst, name="2025/2026", start_date="2025-10-01", end_date="2026-07-31"
        )
        sem = Semester.all_objects.create(
            institution=self.inst,
            session=sess,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        course = Course.all_objects.create(
            institution=self.inst, department=dept, code="CS 101", title="X", credit_units=3
        )
        lecturer = _member(self.inst, "l@loyola.edu", Role.LECTURER, department=dept)
        self.student = _member(self.inst, "s@loyola.edu", Role.STUDENT, department=dept)
        CourseAssignment.all_objects.create(
            institution=self.inst, lecturer=lecturer, course=course, session=sess, semester=sem
        )
        Enrolment.all_objects.create(
            institution=self.inst, student=self.student, course=course, session=sess, semester=sem
        )
        set_current_institution(self.inst)
        bank = QuestionBank.all_objects.create(
            institution=self.inst, course=course, title="P", created_by=lecturer
        )
        for _ in range(3):
            Question.all_objects.create(
                institution=self.inst,
                bank=bank,
                type=QuestionType.MCQ,
                prompt="Q",
                options=["A", "B"],
                correct_answer=0,
                marks=Decimal("2"),
                created_by=lecturer,
            )
        now = timezone.now()
        self.exam = create_exam(
            actor=lecturer,
            course=course,
            session=sess,
            semester=sem,
            banks=[bank],
            title="E",
            exam_type=Exam.ExamType.MAIN,
            duration_minutes=60,
            opens_at=now - timedelta(minutes=30),
            closes_at=now + timedelta(minutes=60),
            num_questions=3,
        )
        self.attempt = start_attempt(student=self.student, exam=self.exam)
        answer_all_objective_correct(self.student, self.attempt)
        ExamAttempt.all_objects.filter(pk=self.attempt.pk).update(
            deadline=now - timedelta(minutes=1)
        )

    def tearDown(self):
        set_current_institution(None)

    def test_concurrent_finalizers_finalize_exactly_once(self):
        barrier = threading.Barrier(2, timeout=10)
        results = []
        results_lock = threading.Lock()

        def run():
            try:
                barrier.wait()
                outcome = ("ok", finalize_expired_attempts())
            except Exception as exc:  # noqa: BLE001 - surfaced in the assertion
                outcome = ("err", repr(exc))
            finally:
                connections.close_all()
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertTrue(all(kind == "ok" for kind, _ in results), results)
        # Between the two runs, the attempt is finalized exactly once.
        self.assertEqual(sum(count for _, count in results), 1)

        refreshed = ExamAttempt.all_objects.get(pk=self.attempt.pk)
        self.assertEqual(refreshed.status, AttemptStatus.GRADED)
        self.assertEqual(refreshed.score, Decimal("6.00"))
        awarded = sorted(
            str(a)
            for a in Answer.all_objects.filter(attempt=refreshed).values_list(
                "awarded_marks", flat=True
            )
        )
        self.assertEqual(awarded, ["2.00", "2.00", "2.00"])
