"""Results pipeline tests: state machine guards, append-only history, and the
transactional audit log."""

from decimal import Decimal
from unittest import mock

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
    Role,
    Semester,
    Session,
    User,
)
from results.models import (
    AuditAction,
    CourseResult,
    ImmutableRecordError,
    ResultAuditLog,
    ResultStatus,
    StudentScore,
)
from results.services import (
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


class ResultsTestBase(APITestCase):
    def setUp(self):
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
