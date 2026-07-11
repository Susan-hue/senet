"""Results pipeline tests: state machine guards, append-only history, and the
transactional audit log."""

import threading
from decimal import Decimal
from unittest import mock, skipUnless

from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
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
from results.models import (
    AmendmentStatus,
    AuditAction,
    CourseResult,
    ExternalExaminerReport,
    ImmutableRecordError,
    ResultAmendment,
    ResultAuditLog,
    ResultStatus,
    StudentScore,
)
from results.services import (
    compute_anomaly_stats,
    create_draft_result,
    record_score,
    submit_result,
    transition_result,
)
from tenancy.models import Institution


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class ResultsDataMixin:
    def setUp(self):
        super().setUp()
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        self.faculty = Faculty.all_objects.create(institution=self.inst, name="Science", code="SCI")
        self.other_faculty = Faculty.all_objects.create(
            institution=self.inst, name="Engineering", code="ENG"
        )
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="Computer Science", code="CSC"
        )
        self.other_dept = Department.all_objects.create(
            institution=self.inst,
            faculty=self.other_faculty,
            name="Electrical Engineering",
            code="EEE",
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
        self.unassigned_lecturer = _member(
            self.inst, "other-lect@veritas.edu", Role.LECTURER, department=self.dept
        )
        self.hod = _member(self.inst, "hod@veritas.edu", Role.HOD, department=self.dept)
        self.wrong_hod = _member(
            self.inst, "hod2@veritas.edu", Role.HOD, department=self.other_dept
        )
        self.dean = _member(self.inst, "dean@veritas.edu", Role.DEAN, faculty=self.faculty)
        self.wrong_dean = _member(
            self.inst, "dean2@veritas.edu", Role.DEAN, faculty=self.other_faculty
        )
        self.senate = _member(self.inst, "senate@veritas.edu", Role.SENATE_ADMIN)
        self.student = _member(self.inst, "stud@veritas.edu", Role.STUDENT, department=self.dept)

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

    def make_draft(self):
        return create_draft_result(
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
        )

    def make_submitted(self):
        result = self.make_draft()
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("30"),
            exam_score=Decimal("50"),
        )
        return submit_result(actor=self.lecturer, result_id=result.id)

    def audit_actions(self, result):
        return list(
            ResultAuditLog.all_objects.filter(result=result).values_list("action", flat=True)
        )


class ResultsTestBase(ResultsDataMixin, APITestCase):
    pass


class DraftCreationTests(ResultsTestBase):
    def test_assigned_lecturer_creates_draft_with_audit_entry(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("result-list"),
            {
                "course": str(self.course.id),
                "session": str(self.session.id),
                "semester": str(self.semester.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data["data"]
        self.assertEqual(data["status"], ResultStatus.DRAFT)
        self.assertEqual(
            self.audit_actions(CourseResult.all_objects.get(pk=data["id"])),
            [AuditAction.RESULT_CREATED],
        )

    def test_unassigned_lecturer_cannot_create_draft(self):
        self.client.force_authenticate(self.unassigned_lecturer)
        response = self.client.post(
            reverse("result-list"),
            {
                "course": str(self.course.id),
                "session": str(self.session.id),
                "semester": str(self.semester.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(CourseResult.all_objects.count(), 0)

    def test_non_lecturer_cannot_create_draft(self):
        self.client.force_authenticate(self.hod)
        response = self.client.post(reverse("result-list"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_sheet_for_same_term_rejected(self):
        self.make_draft()
        with self.assertRaises(ValidationError):
            self.make_draft()

    def test_semester_must_belong_to_session(self):
        other_session = Session.all_objects.create(
            institution=self.inst,
            name="2026/2027",
            start_date="2026-10-01",
            end_date="2027-07-31",
        )
        with self.assertRaises(ValidationError):
            create_draft_result(
                lecturer=self.lecturer,
                course=self.course,
                session=other_session,
                semester=self.semester,
            )


class ScoreEntryTests(ResultsTestBase):
    def test_score_computes_total_and_grade(self):
        result = self.make_draft()
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("result-scores", args=[result.id]),
            {"student": str(self.student.id), "ca_score": "35", "exam_score": "40"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["total"], "75.00")
        self.assertEqual(data["grade"], "A")
        self.assertEqual(self.audit_actions(result)[-1], AuditAction.SCORE_ADDED)

    def test_grade_bands(self):
        result = self.make_draft()
        for ca, exam, grade in [
            ("30", "35", "B"),
            ("20", "30", "C"),
            ("20", "25", "D"),
            ("20", "22", "E"),
            ("10", "15", "F"),
        ]:
            row = record_score(
                actor=self.lecturer,
                result_id=result.id,
                student=self.student,
                ca_score=Decimal(ca),
                exam_score=Decimal(exam),
            )
            self.assertEqual(row.grade, grade)

    def test_score_update_logs_before_and_after(self):
        result = self.make_draft()
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("20"),
            exam_score=Decimal("30"),
        )
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("35"),
            exam_score=Decimal("40"),
        )
        entry = ResultAuditLog.all_objects.filter(
            result=result, action=AuditAction.SCORE_CHANGED
        ).get()
        self.assertEqual(entry.before["total"], "50.00")
        self.assertEqual(entry.after["total"], "75.00")
        self.assertEqual(StudentScore.all_objects.filter(result=result).count(), 1)

    def test_scores_above_component_weights_rejected(self):
        result = self.make_draft()
        with self.assertRaises(ValidationError):
            record_score(
                actor=self.lecturer,
                result_id=result.id,
                student=self.student,
                ca_score=Decimal("45"),  # institution CA weight is 40
                exam_score=Decimal("50"),
            )

    def test_unenrolled_student_rejected(self):
        outsider = _member(self.inst, "stud2@veritas.edu", Role.STUDENT)
        result = self.make_draft()
        with self.assertRaises(ValidationError):
            record_score(
                actor=self.lecturer,
                result_id=result.id,
                student=outsider,
                ca_score=Decimal("20"),
                exam_score=Decimal("30"),
            )

    def test_only_owner_can_enter_scores(self):
        result = self.make_draft()
        with self.assertRaises(PermissionDenied):
            record_score(
                actor=self.unassigned_lecturer,
                result_id=result.id,
                student=self.student,
                ca_score=Decimal("20"),
                exam_score=Decimal("30"),
            )


class SubmitTests(ResultsTestBase):
    def test_submit_transitions_and_logs(self):
        result = self.make_submitted()
        self.assertEqual(result.status, ResultStatus.SUBMITTED_TO_HOD)
        self.assertIn(AuditAction.STATUS_CHANGED, self.audit_actions(result))

    def test_submit_via_api(self):
        result = self.make_draft()
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("30"),
            exam_score=Decimal("50"),
        )
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(reverse("result-submit", args=[result.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], ResultStatus.SUBMITTED_TO_HOD)

    def test_submit_requires_at_least_one_score(self):
        result = self.make_draft()
        with self.assertRaises(ValidationError):
            submit_result(actor=self.lecturer, result_id=result.id)

    def test_submit_locks_the_lecturer_out(self):
        result = self.make_submitted()
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(
            reverse("result-scores", args=[result.id]),
            {"student": str(self.student.id), "ca_score": "10", "exam_score": "10"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_double_submit_rejected(self):
        result = self.make_submitted()
        # A stale client retrying the same transition must fail: the service
        # re-reads state under a row lock instead of trusting the caller.
        with self.assertRaises(ValidationError):
            submit_result(actor=self.lecturer, result_id=result.id)


class TransactionalAuditTests(ResultsTestBase):
    def test_score_change_rolls_back_if_audit_write_fails(self):
        result = self.make_draft()
        with mock.patch.object(ResultAuditLog, "save", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                record_score(
                    actor=self.lecturer,
                    result_id=result.id,
                    student=self.student,
                    ca_score=Decimal("20"),
                    exam_score=Decimal("30"),
                )
        self.assertEqual(StudentScore.all_objects.filter(result=result).count(), 0)

    def test_transition_rolls_back_if_audit_write_fails(self):
        result = self.make_draft()
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("20"),
            exam_score=Decimal("30"),
        )
        with mock.patch.object(ResultAuditLog, "save", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                submit_result(actor=self.lecturer, result_id=result.id)
        result.refresh_from_db()
        self.assertEqual(result.status, ResultStatus.DRAFT)

    def test_result_creation_rolls_back_if_audit_write_fails(self):
        with mock.patch.object(ResultAuditLog, "save", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                self.make_draft()
        self.assertEqual(CourseResult.all_objects.count(), 0)

    def test_audit_log_is_append_only(self):
        result = self.make_draft()
        entry = ResultAuditLog.all_objects.get(result=result)
        entry.reason = "tampered"
        with self.assertRaises(ImmutableRecordError):
            entry.save()
        with self.assertRaises(ImmutableRecordError):
            entry.delete()


class TransitionGuardTests(ResultsTestBase):
    def test_full_approval_chain(self):
        result = self.make_submitted()
        transition_result(
            actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        transition_result(
            actor=self.dean, result_id=result.id, to_status=ResultStatus.APPROVED_BY_DEAN
        )
        result = transition_result(
            actor=self.senate, result_id=result.id, to_status=ResultStatus.RATIFIED_BY_SENATE
        )
        self.assertEqual(result.status, ResultStatus.RATIFIED_BY_SENATE)
        self.assertEqual(
            ResultAuditLog.all_objects.filter(
                result=result, action=AuditAction.STATUS_CHANGED
            ).count(),
            4,
        )

    def test_hod_of_another_department_cannot_approve(self):
        result = self.make_submitted()
        with self.assertRaises(PermissionDenied):
            transition_result(
                actor=self.wrong_hod,
                result_id=result.id,
                to_status=ResultStatus.APPROVED_BY_HOD,
            )

    def test_dean_of_another_faculty_cannot_approve(self):
        result = self.make_submitted()
        transition_result(
            actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        with self.assertRaises(PermissionDenied):
            transition_result(
                actor=self.wrong_dean,
                result_id=result.id,
                to_status=ResultStatus.APPROVED_BY_DEAN,
            )

    def test_lecturer_cannot_approve_their_own_result(self):
        result = self.make_submitted()
        with self.assertRaises(PermissionDenied):
            transition_result(
                actor=self.lecturer,
                result_id=result.id,
                to_status=ResultStatus.APPROVED_BY_HOD,
            )

    def test_states_cannot_be_skipped(self):
        result = self.make_submitted()
        for target in (ResultStatus.APPROVED_BY_DEAN, ResultStatus.RATIFIED_BY_SENATE):
            with self.assertRaises(ValidationError):
                transition_result(actor=self.senate, result_id=result.id, to_status=target)

    def test_return_requires_a_reason(self):
        result = self.make_submitted()
        with self.assertRaises(ValidationError):
            transition_result(actor=self.hod, result_id=result.id, to_status=ResultStatus.RETURNED)

    def test_returned_result_is_editable_and_resubmittable(self):
        result = self.make_submitted()
        result = transition_result(
            actor=self.hod,
            result_id=result.id,
            to_status=ResultStatus.RETURNED,
            reason="CA column looks wrong.",
        )
        self.assertEqual(result.returned_reason, "CA column looks wrong.")
        row = record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("25"),
            exam_score=Decimal("50"),
        )
        self.assertEqual(row.total, Decimal("75"))
        result = submit_result(actor=self.lecturer, result_id=result.id)
        self.assertEqual(result.status, ResultStatus.SUBMITTED_TO_HOD)
        self.assertEqual(result.returned_reason, "")

    def test_lecturer_cannot_submit_a_sheet_they_do_not_own(self):
        result = self.make_draft()
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=self.student,
            ca_score=Decimal("30"),
            exam_score=Decimal("50"),
        )
        with self.assertRaises(PermissionDenied):
            submit_result(actor=self.unassigned_lecturer, result_id=result.id)
        result.refresh_from_db()
        self.assertEqual(result.status, ResultStatus.DRAFT)

    def test_concurrent_style_double_approval_rejected(self):
        result = self.make_submitted()
        transition_result(
            actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        # Second HOD action with a stale view of the state must not double-apply.
        with self.assertRaises(ValidationError):
            transition_result(
                actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
            )

    def test_lecturer_edit_after_hod_approval_rejected(self):
        result = self.make_submitted()
        transition_result(
            actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        with self.assertRaises(PermissionDenied):
            record_score(
                actor=self.lecturer,
                result_id=result.id,
                student=self.student,
                ca_score=Decimal("40"),
                exam_score=Decimal("60"),
            )


class RatifiedImmutabilityTests(ResultsTestBase):
    def ratify(self):
        result = self.make_submitted()
        transition_result(
            actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        transition_result(
            actor=self.dean, result_id=result.id, to_status=ResultStatus.APPROVED_BY_DEAN
        )
        return transition_result(
            actor=self.senate, result_id=result.id, to_status=ResultStatus.RATIFIED_BY_SENATE
        )

    def test_ratified_result_has_no_outgoing_transition(self):
        result = self.ratify()
        for target in ResultStatus.values:
            with self.assertRaises(ValidationError):
                transition_result(actor=self.senate, result_id=result.id, to_status=target)

    def test_ratified_result_row_is_immutable(self):
        result = self.ratify()
        result.returned_reason = "sneaky edit"
        with self.assertRaises(ImmutableRecordError):
            result.save()

    def test_ratified_score_rows_are_immutable_and_undeletable(self):
        result = self.ratify()
        row = StudentScore.all_objects.get(result=result)
        row.total = Decimal("1")
        with self.assertRaises(ImmutableRecordError):
            row.save()
        with self.assertRaises(ImmutableRecordError):
            row.delete()

    def test_superseding_currency_flip_stays_possible_for_amendments(self):
        result = self.ratify()
        row = StudentScore.all_objects.get(result=result)
        row.is_current = False
        row.save(update_fields=["is_current", "updated_at"])
        row.refresh_from_db()
        self.assertFalse(row.is_current)
        self.assertEqual(row.total, Decimal("80"))


class TenantIsolationTests(ResultsTestBase):
    def setUp(self):
        super().setUp()
        self.foreign = Institution.objects.create(name="FUTO", code="futo")
        self.foreign_admin = _member(self.foreign, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.foreign_senate = _member(self.foreign, "senate@futo.edu", Role.SENATE_ADMIN)
        self.result = self.make_submitted()

    def test_foreign_admin_sees_no_results(self):
        self.client.force_authenticate(self.foreign_admin)
        response = self.client.get(reverse("result-list"))
        self.assertEqual(response.data["data"]["count"], 0)

    def test_foreign_admin_cannot_read_detail(self):
        self.client.force_authenticate(self.foreign_admin)
        response = self.client.get(reverse("result-detail", args=[self.result.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_foreign_actor_cannot_transition(self):
        transition_result(
            actor=self.hod, result_id=self.result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        transition_result(
            actor=self.dean, result_id=self.result.id, to_status=ResultStatus.APPROVED_BY_DEAN
        )
        with self.assertRaises(NotFound):
            transition_result(
                actor=self.foreign_senate,
                result_id=self.result.id,
                to_status=ResultStatus.RATIFIED_BY_SENATE,
            )

    def test_scoped_visibility_per_role(self):
        for user, expected in [
            (self.lecturer, 1),
            (self.unassigned_lecturer, 0),
            (self.hod, 1),
            (self.wrong_hod, 0),
            (self.dean, 1),
            (self.wrong_dean, 0),
            (self.senate, 1),
        ]:
            self.client.force_authenticate(user)
            response = self.client.get(reverse("result-list"))
            self.assertEqual(response.data["data"]["count"], expected, user.email)

    def test_detail_includes_current_scores(self):
        self.client.force_authenticate(self.hod)
        response = self.client.get(reverse("result-detail", args=[self.result.id]))
        scores = response.data["data"]["scores"]
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]["grade"], "A")


class ApprovalTestBase(ResultsTestBase):
    def submitted_for(self, course, student=None):
        student = student or self.student
        result = create_draft_result(
            lecturer=self.lecturer, course=course, session=self.session, semester=self.semester
        )
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=student,
            ca_score=Decimal("30"),
            exam_score=Decimal("50"),
        )
        return submit_result(actor=self.lecturer, result_id=result.id)

    def advance_to(self, result, target):
        """Push a submitted result up the chain until it reaches ``target``."""
        chain = [
            (self.hod, ResultStatus.APPROVED_BY_HOD),
            (self.dean, ResultStatus.APPROVED_BY_DEAN),
            (self.senate, ResultStatus.RATIFIED_BY_SENATE),
        ]
        for actor, to_status in chain:
            if result.status == target:
                break
            transition_result(actor=actor, result_id=result.id, to_status=to_status)
            result = CourseResult.all_objects.get(pk=result.id)
        return result

    def enrol(self, email, course=None):
        course = course or self.course
        student = _member(self.inst, email, Role.STUDENT, department=self.dept)
        Enrolment.all_objects.create(
            institution=self.inst,
            student=student,
            course=course,
            session=self.session,
            semester=self.semester,
        )
        return student

    def second_course(self, code="CSC 102"):
        course = Course.all_objects.create(
            institution=self.inst,
            department=self.dept,
            code=code,
            title="Data Structures",
            credit_units=3,
        )
        CourseAssignment.all_objects.create(
            institution=self.inst,
            lecturer=self.lecturer,
            course=course,
            session=self.session,
            semester=self.semester,
        )
        return course


class ApprovalWorklistTests(ApprovalTestBase):
    def test_hod_worklist_is_department_scoped(self):
        self.make_submitted()
        self.client.force_authenticate(self.hod)
        self.assertEqual(self.client.get(reverse("result-worklist")).data["data"]["count"], 1)
        self.client.force_authenticate(self.wrong_hod)
        self.assertEqual(self.client.get(reverse("result-worklist")).data["data"]["count"], 0)

    def test_dean_worklist_shows_hod_approved_in_faculty_only(self):
        result = self.make_submitted()
        self.advance_to(result, ResultStatus.APPROVED_BY_HOD)
        self.client.force_authenticate(self.dean)
        self.assertEqual(self.client.get(reverse("result-worklist")).data["data"]["count"], 1)
        # It has left the HOD's queue.
        self.client.force_authenticate(self.hod)
        self.assertEqual(self.client.get(reverse("result-worklist")).data["data"]["count"], 0)
        # A dean in another faculty does not see it.
        self.client.force_authenticate(self.wrong_dean)
        self.assertEqual(self.client.get(reverse("result-worklist")).data["data"]["count"], 0)

    def test_senate_worklist_shows_dean_approved_institution_wide(self):
        result = self.make_submitted()
        self.advance_to(result, ResultStatus.APPROVED_BY_DEAN)
        self.client.force_authenticate(self.senate)
        self.assertEqual(self.client.get(reverse("result-worklist")).data["data"]["count"], 1)


class ApprovalActionApiTests(ApprovalTestBase):
    def test_hod_approves_via_api(self):
        result = self.make_submitted()
        self.client.force_authenticate(self.hod)
        response = self.client.post(reverse("result-approve", args=[result.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], ResultStatus.APPROVED_BY_HOD)

    def test_hod_of_another_department_denied_via_api(self):
        result = self.make_submitted()
        self.client.force_authenticate(self.wrong_hod)
        response = self.client.post(reverse("result-approve", args=[result.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            CourseResult.all_objects.get(pk=result.id).status, ResultStatus.SUBMITTED_TO_HOD
        )

    def test_dean_approves_via_api(self):
        result = self.make_submitted()
        self.advance_to(result, ResultStatus.APPROVED_BY_HOD)
        self.client.force_authenticate(self.dean)
        response = self.client.post(reverse("result-approve", args=[result.id]))
        self.assertEqual(response.data["data"]["status"], ResultStatus.APPROVED_BY_DEAN)

    def test_dean_of_another_faculty_denied_via_api(self):
        result = self.make_submitted()
        self.advance_to(result, ResultStatus.APPROVED_BY_HOD)
        self.client.force_authenticate(self.wrong_dean)
        response = self.client.post(reverse("result-approve", args=[result.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_return_requires_reason(self):
        result = self.make_submitted()
        self.client.force_authenticate(self.hod)
        response = self.client.post(reverse("result-return", args=[result.id]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(
            reverse("result-return", args=[result.id]),
            {"reason": "CA column looks wrong."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], ResultStatus.RETURNED)
        self.assertEqual(response.data["data"]["returned_reason"], "CA column looks wrong.")


class BatchRatifyTests(ApprovalTestBase):
    def _two_dean_approved(self):
        course2 = self.second_course()
        Enrolment.all_objects.create(
            institution=self.inst,
            student=self.student,
            course=course2,
            session=self.session,
            semester=self.semester,
        )
        r1 = self.advance_to(self.make_submitted(), ResultStatus.APPROVED_BY_DEAN)
        r2 = self.advance_to(self.submitted_for(course2), ResultStatus.APPROVED_BY_DEAN)
        return r1, r2

    def test_senate_batch_ratifies_and_audits_each(self):
        r1, r2 = self._two_dean_approved()
        self.client.force_authenticate(self.senate)
        response = self.client.post(
            reverse("result-batch-ratify"),
            {"result_ids": [str(r1.id), str(r2.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 2)
        for result in (r1, r2):
            self.assertEqual(
                CourseResult.all_objects.get(pk=result.id).status,
                ResultStatus.RATIFIED_BY_SENATE,
            )
            self.assertEqual(
                ResultAuditLog.all_objects.filter(
                    result_id=result.id,
                    action=AuditAction.STATUS_CHANGED,
                    after={"status": ResultStatus.RATIFIED_BY_SENATE.value},
                ).count(),
                1,
            )

    def test_batch_is_all_or_nothing(self):
        r1, _r2 = self._two_dean_approved()
        course3 = self.second_course("CSC 103")
        Enrolment.all_objects.create(
            institution=self.inst,
            student=self.student,
            course=course3,
            session=self.session,
            semester=self.semester,
        )
        not_ready = self.advance_to(self.submitted_for(course3), ResultStatus.APPROVED_BY_HOD)
        self.client.force_authenticate(self.senate)
        response = self.client.post(
            reverse("result-batch-ratify"),
            {"result_ids": [str(r1.id), str(not_ready.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # The whole batch rolled back: the ratifiable sheet is untouched.
        self.assertEqual(
            CourseResult.all_objects.get(pk=r1.id).status, ResultStatus.APPROVED_BY_DEAN
        )

    def test_non_senate_cannot_batch_ratify(self):
        r1, r2 = self._two_dean_approved()
        self.client.force_authenticate(self.dean)
        response = self.client.post(
            reverse("result-batch-ratify"),
            {"result_ids": [str(r1.id), str(r2.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AnomalyStatsTests(ApprovalTestBase):
    def _score(self, result, student, ca, exam):
        record_score(
            actor=self.lecturer,
            result_id=result.id,
            student=student,
            ca_score=Decimal(ca),
            exam_score=Decimal(exam),
        )

    def test_high_failure_rate_flagged(self):
        result = self.make_draft()
        self._score(result, self.student, "35", "40")  # 75 -> A
        self._score(result, self.enrol("f1@veritas.edu"), "10", "20")  # 30 -> F
        self._score(result, self.enrol("f2@veritas.edu"), "10", "15")  # 25 -> F
        self._score(result, self.enrol("f3@veritas.edu"), "10", "10")  # 20 -> F
        stats = compute_anomaly_stats(result)
        self.assertEqual(stats["total_students"], 4)
        self.assertEqual(stats["failure_count"], 3)
        self.assertEqual(stats["failure_rate"], "0.75")
        self.assertEqual(stats["class_average"], "37.50")
        self.assertEqual(stats["highest_score"], "75.00")
        self.assertEqual(stats["lowest_score"], "20.00")
        self.assertEqual(stats["grade_distribution"]["A"], 1)
        self.assertEqual(stats["grade_distribution"]["F"], 3)
        self.assertTrue(stats["flags"]["high_failure_rate"])
        self.assertFalse(stats["flags"]["abnormally_high_grades"])

    def test_abnormally_high_grades_flagged(self):
        course2 = self.second_course()
        result = create_draft_result(
            lecturer=self.lecturer, course=course2, session=self.session, semester=self.semester
        )
        Enrolment.all_objects.create(
            institution=self.inst,
            student=self.student,
            course=course2,
            session=self.session,
            semester=self.semester,
        )
        self._score(result, self.student, "35", "40")  # A
        self._score(result, self.enrol("a1@veritas.edu", course2), "35", "40")  # A
        self._score(result, self.enrol("a2@veritas.edu", course2), "35", "40")  # A
        self._score(result, self.enrol("b1@veritas.edu", course2), "30", "35")  # 65 -> B
        stats = compute_anomaly_stats(result)
        self.assertEqual(stats["grade_distribution"]["A"], 3)
        self.assertEqual(stats["grade_distribution"]["B"], 1)
        self.assertEqual(stats["failure_count"], 0)
        self.assertTrue(stats["flags"]["abnormally_high_grades"])
        self.assertFalse(stats["flags"]["high_failure_rate"])

    def test_empty_sheet_is_safe(self):
        stats = compute_anomaly_stats(self.make_draft())
        self.assertEqual(stats["total_students"], 0)
        self.assertIsNone(stats["class_average"])
        self.assertEqual(stats["failure_rate"], "0.00")

    def test_statistics_included_in_detail_for_board(self):
        result = self.make_submitted()
        self.client.force_authenticate(self.hod)
        response = self.client.get(reverse("result-detail", args=[result.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stats = response.data["data"]["statistics"]
        self.assertEqual(stats["total_students"], 1)
        self.assertIn("grade_distribution", stats)
        self.assertIn("high_failure_rate", stats["flags"])


class ExternalExaminerTests(ApprovalTestBase):
    def setUp(self):
        super().setUp()
        self.programme = Programme.all_objects.create(
            institution=self.inst,
            department=self.dept,
            name="Computer Science",
            code="CSC-BSC",
            degree_type="B.Sc",
        )

    def _payload(self):
        return {
            "programme": str(self.programme.id),
            "session": str(self.session.id),
            "semester": str(self.semester.id),
            "examiner_name": "Prof. Ada Okoro",
            "examiner_institution": "University of Lagos",
            "audit_date": "2026-06-15",
            "remarks": "Scripts marked to standard.",
        }

    def test_dean_captures_report(self):
        self.client.force_authenticate(self.dean)
        response = self.client.post(
            reverse("external-examiner-reports"), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["faculty"], self.faculty.id)
        self.assertEqual(response.data["data"]["examiner_name"], "Prof. Ada Okoro")

    def test_non_dean_cannot_capture(self):
        self.client.force_authenticate(self.hod)
        response = self.client.post(
            reverse("external-examiner-reports"), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dean_of_other_faculty_denied(self):
        self.client.force_authenticate(self.wrong_dean)
        response = self.client.post(
            reverse("external-examiner-reports"), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ExternalExaminerReport.all_objects.count(), 0)

    def test_list_is_faculty_scoped(self):
        self.client.force_authenticate(self.dean)
        self.client.post(reverse("external-examiner-reports"), self._payload(), format="json")
        self.assertEqual(
            self.client.get(reverse("external-examiner-reports")).data["data"]["count"], 1
        )
        self.client.force_authenticate(self.wrong_dean)
        self.assertEqual(
            self.client.get(reverse("external-examiner-reports")).data["data"]["count"], 0
        )

    def test_reports_are_tenant_isolated(self):
        self.client.force_authenticate(self.dean)
        self.client.post(reverse("external-examiner-reports"), self._payload(), format="json")

        foreign = Institution.objects.create(name="FUTO", code="futo")
        foreign_faculty = Faculty.all_objects.create(
            institution=foreign, name="Science", code="SCI"
        )
        foreign_dean = _member(foreign, "dean@futo.edu", Role.DEAN, faculty=foreign_faculty)
        self.client.force_authenticate(foreign_dean)
        # Sees none of our reports.
        self.assertEqual(
            self.client.get(reverse("external-examiner-reports")).data["data"]["count"], 0
        )
        # Cannot capture a report against our programme (not in their tenant).
        response = self.client.post(
            reverse("external-examiner-reports"), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AmendmentWorkflowTests(ApprovalTestBase):
    def ratified(self):
        return self.advance_to(self.make_submitted(), ResultStatus.RATIFIED_BY_SENATE)

    def raise_amendment_api(self, result, actor=None, **overrides):
        self.client.force_authenticate(actor or self.lecturer)
        payload = {
            "student": str(self.student.id),
            "proposed_ca_score": "35",
            "proposed_exam_score": "55",
            "justification": "Exam script re-marked; addition error corrected.",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("result-raise-amendment", args=[result.id]), payload, format="json"
        )

    def test_amendment_supersedes_without_destroying_original(self):
        result = self.ratified()
        original = StudentScore.all_objects.get(result=result, student=self.student)
        self.assertEqual(original.total, Decimal("80"))

        response = self.raise_amendment_api(result)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        amendment_id = response.data["data"]["id"]

        self.client.force_authenticate(self.hod)
        self.client.post(reverse("amendment-approve", args=[amendment_id]))
        self.client.force_authenticate(self.dean)
        self.client.post(reverse("amendment-approve", args=[amendment_id]))
        self.client.force_authenticate(self.senate)
        final = self.client.post(reverse("amendment-approve", args=[amendment_id]))
        self.assertEqual(final.data["data"]["status"], AmendmentStatus.APPLIED)

        # Original row survives untouched, only losing currency.
        original.refresh_from_db()
        self.assertFalse(original.is_current)
        self.assertEqual(original.total, Decimal("80"))

        current = StudentScore.all_objects.get(result=result, student=self.student, is_current=True)
        self.assertEqual(current.total, Decimal("90"))
        self.assertEqual(current.grade, "A")
        self.assertEqual(current.supersedes_id, original.id)
        self.assertEqual(
            StudentScore.all_objects.filter(
                result=result, student=self.student, is_current=True
            ).count(),
            1,
        )

    def test_amended_result_detail_shows_superseding_row_only(self):
        result = self.ratified()
        response = self.raise_amendment_api(result)
        amendment_id = response.data["data"]["id"]
        self.client.force_authenticate(self.hod)
        self.client.post(reverse("amendment-approve", args=[amendment_id]))
        self.client.force_authenticate(self.dean)
        self.client.post(reverse("amendment-approve", args=[amendment_id]))
        self.client.force_authenticate(self.senate)
        self.client.post(reverse("amendment-approve", args=[amendment_id]))

        self.client.force_authenticate(self.hod)
        detail = self.client.get(reverse("result-detail", args=[result.id]))
        scores = detail.data["data"]["scores"]
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]["total"], "90.00")

    def test_justification_is_mandatory(self):
        result = self.ratified()
        response = self.raise_amendment_api(result, justification="")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_ratified_results_can_be_amended(self):
        result = self.make_submitted()
        response = self.raise_amendment_api(result)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthorized_actor_cannot_raise(self):
        result = self.ratified()
        response = self.raise_amendment_api(result, actor=self.unassigned_lecturer)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_wrong_department_hod_cannot_approve_amendment(self):
        result = self.ratified()
        amendment_id = self.raise_amendment_api(result).data["data"]["id"]
        self.client.force_authenticate(self.wrong_hod)
        response = self.client.post(reverse("amendment-approve", args=[amendment_id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_amendment_return_requires_reason(self):
        result = self.ratified()
        amendment_id = self.raise_amendment_api(result).data["data"]["id"]
        self.client.force_authenticate(self.hod)
        response = self.client.post(
            reverse("amendment-return", args=[amendment_id]), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(
            reverse("amendment-return", args=[amendment_id]),
            {"reason": "Provide the re-marked script."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], AmendmentStatus.RETURNED)

    def test_foreign_actor_cannot_view_or_act_on_amendment(self):
        result = self.ratified()
        amendment_id = self.raise_amendment_api(result).data["data"]["id"]

        foreign = Institution.objects.create(name="FUTO", code="futo")
        foreign_senate = _member(foreign, "senate@futo.edu", Role.SENATE_ADMIN)
        self.client.force_authenticate(foreign_senate)
        self.assertEqual(
            self.client.get(reverse("amendment-detail", args=[amendment_id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(reverse("amendment-approve", args=[amendment_id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertFalse(
            ResultAmendment.all_objects.get(pk=amendment_id).status == AmendmentStatus.APPLIED
        )


@skipUnless(
    connection.vendor == "postgresql",
    "select_for_update is a no-op on SQLite; real row locks need Postgres",
)
class ConcurrentTransitionTests(ResultsDataMixin, TransactionTestCase):
    def test_racing_identical_transitions_serialize_on_the_row_lock(self):
        result = self.make_submitted()
        barrier = threading.Barrier(2, timeout=10)
        outcomes = []
        outcomes_lock = threading.Lock()

        def approve():
            try:
                barrier.wait()
                transition_result(
                    actor=self.hod,
                    result_id=result.id,
                    to_status=ResultStatus.APPROVED_BY_HOD,
                )
                outcome = "applied"
            except ValidationError:
                outcome = "rejected"
            except Exception as exc:
                outcome = f"unexpected: {exc!r}"
            finally:
                connections.close_all()
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=approve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))

        # The lock serializes the two transactions: the loser re-reads the
        # committed APPROVED_BY_HOD state and fails the rule lookup instead of
        # double-applying or overwriting the winner.
        self.assertEqual(sorted(outcomes), ["applied", "rejected"])
        refreshed = CourseResult.all_objects.get(pk=result.id)
        self.assertEqual(refreshed.status, ResultStatus.APPROVED_BY_HOD)
        self.assertEqual(
            ResultAuditLog.all_objects.filter(
                result_id=result.id,
                action=AuditAction.STATUS_CHANGED,
                after={"status": ResultStatus.APPROVED_BY_HOD.value},
            ).count(),
            1,
        )


@skipUnless(
    connection.vendor == "postgresql",
    "Immutability triggers are PostgreSQL DDL; they do not exist on SQLite.",
)
class DatabaseTriggerImmutabilityTests(ResultsTestBase):
    """The ORM save()/delete() guards stop model-level writes, but a bulk
    ``QuerySet.update()`` or raw SQL bypasses ``save()`` entirely. These tests
    prove the database triggers (migration 0004) hold the line where the Python
    guards cannot reach."""

    def ratify(self):
        result = self.make_submitted()
        transition_result(
            actor=self.hod, result_id=result.id, to_status=ResultStatus.APPROVED_BY_HOD
        )
        transition_result(
            actor=self.dean, result_id=result.id, to_status=ResultStatus.APPROVED_BY_DEAN
        )
        return transition_result(
            actor=self.senate, result_id=result.id, to_status=ResultStatus.RATIFIED_BY_SENATE
        )

    def test_trigger_blocks_bulk_update_bypassing_model_save(self):
        result = self.ratify()
        row = StudentScore.all_objects.get(result=result, is_current=True)
        # QuerySet.update() emits SQL directly, never calling StudentScore.save(),
        # so only the DB trigger can stop it.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StudentScore.all_objects.filter(pk=row.pk).update(total=Decimal("1"))
        row.refresh_from_db()
        self.assertEqual(row.total, Decimal("80"))

    def test_trigger_blocks_raw_sql_update_on_ratified_score(self):
        result = self.ratify()
        row = StudentScore.all_objects.get(result=result, is_current=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE results_student_score SET total = 1, grade = 'F' WHERE id = %s",
                        [row.pk],
                    )
        row.refresh_from_db()
        self.assertEqual(row.total, Decimal("80"))
        self.assertEqual(row.grade, "A")

    def test_trigger_blocks_raw_delete_on_ratified_score(self):
        result = self.ratify()
        row = StudentScore.all_objects.get(result=result, is_current=True)
        # Raw SQL DELETE bypasses both StudentScore.delete() and the ORM's
        # cascade collection, isolating the row-level DELETE trigger.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM results_student_score WHERE id = %s", [row.pk])
        self.assertTrue(StudentScore.all_objects.filter(pk=row.pk).exists())

    def test_trigger_still_allows_currency_flip_via_bulk_update(self):
        # The amendment supersession path retires a row with a bulk currency
        # flip; the trigger must let value-preserving updates through.
        result = self.ratify()
        row = StudentScore.all_objects.get(result=result, is_current=True)
        StudentScore.all_objects.filter(pk=row.pk).update(is_current=False)
        row.refresh_from_db()
        self.assertFalse(row.is_current)
        self.assertEqual(row.total, Decimal("80"))

    def test_trigger_blocks_bulk_update_on_audit_log(self):
        result = self.make_draft()
        entry = ResultAuditLog.all_objects.filter(result=result).first()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ResultAuditLog.all_objects.filter(pk=entry.pk).update(reason="tampered")
        entry.refresh_from_db()
        self.assertNotEqual(entry.reason, "tampered")

    def test_trigger_blocks_delete_on_audit_log(self):
        result = self.make_draft()
        entry = ResultAuditLog.all_objects.filter(result=result).first()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ResultAuditLog.all_objects.filter(pk=entry.pk).delete()
        self.assertTrue(ResultAuditLog.all_objects.filter(pk=entry.pk).exists())
