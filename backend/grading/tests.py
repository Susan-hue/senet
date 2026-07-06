"""GPA engine tests built around hand-computed worked examples. Each example
prints its arithmetic so the numbers can be audited straight from the test
output."""

from decimal import Decimal
from unittest import mock

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Course, Department, Faculty, Role, Semester, Session, User
from grading.models import AcademicStanding
from grading.scales import grade_for_score
from grading.services import (
    classify,
    cumulative_summary,
    outstanding_carryovers,
    standing_for,
    term_summary,
)
from grading.tasks import compute_department_standing
from results.models import CourseResult, ResultStatus, StudentScore
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


class GradingTestBase(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        self.faculty = Faculty.all_objects.create(institution=self.inst, name="Science", code="SCI")
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="Mathematics", code="MTH"
        )
        self.session = Session.all_objects.create(
            institution=self.inst,
            name="2025/2026",
            start_date="2025-10-01",
            end_date="2026-07-31",
            is_current=True,
        )
        self.sem1 = Semester.all_objects.create(
            institution=self.inst,
            session=self.session,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        self.sem2 = Semester.all_objects.create(
            institution=self.inst,
            session=self.session,
            name="Second",
            start_date="2026-03-01",
            end_date="2026-07-31",
        )
        self.lecturer = _member(self.inst, "lect@veritas.edu", Role.LECTURER, department=self.dept)
        self.student = _member(self.inst, "stud@veritas.edu", Role.STUDENT, department=self.dept)

        self.courses = {}
        for code, units in [
            ("MTH101", 3),
            ("CHM101", 2),
            ("PHY101", 3),
            ("MTH102", 3),
            ("GST102", 2),
            ("PHY102", 3),
        ]:
            self.courses[code] = Course.all_objects.create(
                institution=self.inst,
                department=self.dept,
                code=code,
                title=code,
                credit_units=units,
            )

    def ratified_score(self, code, semester, total, student=None, status_=None):
        """Create (or reuse) a result sheet for the course-term in the given
        state and attach a score row whose letter follows the institution scale."""
        course = self.courses[code]
        sheet, _created = CourseResult.all_objects.get_or_create(
            course=course,
            session=self.session,
            semester=semester,
            defaults={
                "institution": self.inst,
                "lecturer": self.lecturer,
                "status": status_ or ResultStatus.RATIFIED_BY_SENATE,
            },
        )
        total = Decimal(total)
        letter, _points = grade_for_score(self.inst, total)
        return StudentScore.all_objects.create(
            institution=self.inst,
            result=sheet,
            student=student or self.student,
            ca_score=Decimal("0"),
            exam_score=total,
            total=total,
            grade=letter,
        )


class WorkedExampleTests(GradingTestBase):
    def test_simple_gpa_worked_example(self):
        # MTH101 3u × A(5) = 15 QP; CHM101 2u × B(4) = 8 QP; PHY101 3u × C(3) = 9 QP.
        self.ratified_score("MTH101", self.sem1, "75")
        self.ratified_score("CHM101", self.sem1, "65")
        self.ratified_score("PHY101", self.sem1, "55")

        summary = term_summary(self.student, self.session, self.sem1)

        print("\n--- Worked example: simple GPA ---")
        for line in summary["courses"]:
            print(
                f"{line['course_code']}: {line['credit_units']}u x "
                f"{line['grade']}({line['grade_points']}) = {line['quality_points']} QP"
            )
        print(
            f"Total QP = {summary['quality_points']}, total units = "
            f"{summary['credit_units']}, GPA = {summary['gpa']}"
        )

        self.assertEqual(summary["quality_points"], "32.00")
        self.assertEqual(summary["credit_units"], 8)
        self.assertEqual(summary["gpa"], Decimal("4.00"))

    def test_cgpa_across_two_semesters_worked_example(self):
        # Semester 1: 32 QP / 8u (as above). Semester 2: MTH102 3u x A(5) = 15,
        # GST102 2u x C(3) = 6 -> 21 QP / 5u, GPA 4.20.
        # CGPA = (32 + 21) / (8 + 5) = 53 / 13 = 4.0769... -> 4.08.
        self.ratified_score("MTH101", self.sem1, "75")
        self.ratified_score("CHM101", self.sem1, "65")
        self.ratified_score("PHY101", self.sem1, "55")
        self.ratified_score("MTH102", self.sem2, "80")
        self.ratified_score("GST102", self.sem2, "52")

        term1 = term_summary(self.student, self.session, self.sem1)
        term2 = term_summary(self.student, self.session, self.sem2)
        cumulative = cumulative_summary(self.student)

        print("\n--- Worked example: CGPA across two semesters ---")
        print(
            f"Semester 1: QP {term1['quality_points']}, units {term1['credit_units']}, GPA {term1['gpa']}"
        )
        print(
            f"Semester 2: QP {term2['quality_points']}, units {term2['credit_units']}, GPA {term2['gpa']}"
        )
        print(
            f"CGPA = ({term1['quality_points']} + {term2['quality_points']}) / "
            f"({term1['credit_units']} + {term2['credit_units']}) = "
            f"{cumulative['quality_points']} / {cumulative['credit_units']} = {cumulative['cgpa']}"
        )

        self.assertEqual(term1["gpa"], Decimal("4.00"))
        self.assertEqual(term2["quality_points"], "21.00")
        self.assertEqual(term2["gpa"], Decimal("4.20"))
        self.assertEqual(cumulative["quality_points"], "53.00")
        self.assertEqual(cumulative["credit_units"], 13)
        self.assertEqual(cumulative["cgpa"], Decimal("4.08"))

    def _carryover_fixture(self):
        # Semester 1: MTH101 3u scored 25 -> F(0), CHM101 2u scored 65 -> B(8 QP).
        # Semester 2: MTH101 retaken, scored 65 -> B(12 QP); PHY102 3u 75 -> A(15 QP).
        self.ratified_score("MTH101", self.sem1, "25")
        self.ratified_score("CHM101", self.sem1, "65")
        self.ratified_score("MTH102", self.sem2, "75")  # placeholder to keep sheets distinct
        # The retake needs its own sheet: same course, different term.
        course = self.courses["MTH101"]
        retake_sheet = CourseResult.all_objects.create(
            institution=self.inst,
            course=course,
            session=self.session,
            semester=self.sem2,
            lecturer=self.lecturer,
            status=ResultStatus.RATIFIED_BY_SENATE,
        )
        StudentScore.all_objects.create(
            institution=self.inst,
            result=retake_sheet,
            student=self.student,
            ca_score=Decimal("0"),
            exam_score=Decimal("65"),
            total=Decimal("65"),
            grade="B",
        )

    def test_carryover_both_methods_worked_example(self):
        # Attempts: MTH101 F(3u, 0 QP) then B(3u, 12 QP); CHM101 B(2u, 8 QP);
        # MTH102 A(3u, 15 QP).
        # ALL_ATTEMPTS: QP = 0+8+12+15 = 35; units = 3+2+3+3 = 11; CGPA = 35/11 = 3.18.
        # HIGHEST_ONLY: failed attempt excluded: QP = 8+12+15 = 35; units = 2+3+3 = 8;
        # CGPA = 35/8 = 4.375 -> 4.38 (half-up).
        self._carryover_fixture()

        self.inst.carryover_cgpa_method = "ALL_ATTEMPTS"
        self.inst.save()
        all_attempts = cumulative_summary(self.student)

        self.inst.carryover_cgpa_method = "HIGHEST_ONLY"
        self.inst.save()
        self.student.refresh_from_db()
        highest_only = cumulative_summary(self.student)

        print("\n--- Worked example: carryover methods ---")
        print(
            f"ALL_ATTEMPTS: QP {all_attempts['quality_points']} / units "
            f"{all_attempts['credit_units']} = CGPA {all_attempts['cgpa']}"
        )
        print(
            f"HIGHEST_ONLY: QP {highest_only['quality_points']} / units "
            f"{highest_only['credit_units']} = CGPA {highest_only['cgpa']}"
        )

        self.assertEqual(all_attempts["quality_points"], "35.00")
        self.assertEqual(all_attempts["credit_units"], 11)
        self.assertEqual(all_attempts["cgpa"], Decimal("3.18"))

        self.assertEqual(highest_only["quality_points"], "35.00")
        self.assertEqual(highest_only["credit_units"], 8)
        self.assertEqual(highest_only["cgpa"], Decimal("4.38"))

    def test_outstanding_carryovers_resolve_after_passing_retake(self):
        self.ratified_score("MTH101", self.sem1, "25")
        self.ratified_score("CHM101", self.sem1, "65")
        outstanding = outstanding_carryovers(self.student)
        self.assertEqual([c["code"] for c in outstanding], ["MTH101"])

        course = self.courses["MTH101"]
        retake_sheet = CourseResult.all_objects.create(
            institution=self.inst,
            course=course,
            session=self.session,
            semester=self.sem2,
            lecturer=self.lecturer,
            status=ResultStatus.RATIFIED_BY_SENATE,
        )
        StudentScore.all_objects.create(
            institution=self.inst,
            result=retake_sheet,
            student=self.student,
            ca_score=Decimal("0"),
            exam_score=Decimal("55"),
            total=Decimal("55"),
            grade="C",
        )
        self.assertEqual(outstanding_carryovers(self.student), [])

    def test_classification_band_boundaries(self):
        cases = [
            ("5.00", "First Class", False, None),
            ("4.50", "First Class", False, None),
            ("4.49", "Second Class Upper", True, "First Class"),
            ("4.45", "Second Class Upper", True, "First Class"),
            ("4.44", "Second Class Upper", False, None),
            ("3.50", "Second Class Upper", False, None),
            ("3.49", "Second Class Lower", True, "Second Class Upper"),
            ("2.40", "Second Class Lower", False, None),
            ("2.39", "Third Class", True, "Second Class Lower"),
            ("1.50", "Third Class", False, None),
            ("1.49", "Fail", True, "Third Class"),
            ("1.44", "Fail", False, None),
        ]
        print("\n--- Worked example: classification boundaries ---")
        for cgpa, expected_name, expected_flag, expected_band in cases:
            outcome = classify(self.inst, Decimal(cgpa))
            flag = (
                f" [borderline for {outcome['borderline_band']}]"
                if outcome["is_borderline"]
                else ""
            )
            print(f"CGPA {cgpa} -> {outcome['name']}{flag}")
            self.assertEqual(outcome["name"], expected_name, cgpa)
            self.assertEqual(outcome["is_borderline"], expected_flag, cgpa)
            self.assertEqual(outcome["borderline_band"], expected_band, cgpa)

    def test_standing_thresholds(self):
        # Defaults: probation below 1.50, withdrawal below 1.00.
        self.assertEqual(standing_for(self.inst, Decimal("1.50")), "good")
        self.assertEqual(standing_for(self.inst, Decimal("1.49")), "probation")
        self.assertEqual(standing_for(self.inst, Decimal("1.00")), "probation")
        self.assertEqual(standing_for(self.inst, Decimal("0.99")), "withdrawal")


class ConfigDrivenTests(GradingTestBase):
    def test_grade_points_follow_institution_scale(self):
        # Same scores on a 4-point scale (A=4, B=3, C=2, D=1, F=0):
        # MTH101 3u x A(4)=12; CHM101 2u x B(3)=6; PHY101 3u x C(2)=6.
        # GPA = 24 / 8 = 3.00.
        self.inst.grade_scale = [
            {"grade": "A", "min_score": 70, "points": 4},
            {"grade": "B", "min_score": 60, "points": 3},
            {"grade": "C", "min_score": 50, "points": 2},
            {"grade": "D", "min_score": 45, "points": 1},
            {"grade": "F", "min_score": 0, "points": 0},
        ]
        self.inst.save()
        self.student.refresh_from_db()
        self.ratified_score("MTH101", self.sem1, "75")
        self.ratified_score("CHM101", self.sem1, "65")
        self.ratified_score("PHY101", self.sem1, "55")

        summary = term_summary(self.student, self.session, self.sem1)
        print(
            "\n--- Config-driven: 4-point scale GPA = "
            f"{summary['quality_points']}/{summary['credit_units']} = {summary['gpa']} ---"
        )
        self.assertEqual(summary["quality_points"], "24.00")
        self.assertEqual(summary["gpa"], Decimal("3.00"))

    def test_carryover_pass_mark_is_config_driven(self):
        self.ratified_score("MTH101", self.sem1, "42")
        self.assertEqual(outstanding_carryovers(self.student), [])

        self.inst.carryover_pass_mark = Decimal("45")
        self.inst.save()
        self.student.refresh_from_db()
        self.assertEqual([c["code"] for c in outstanding_carryovers(self.student)], ["MTH101"])

    def test_only_configured_source_state_counts(self):
        self.ratified_score("MTH101", self.sem1, "75")
        self.ratified_score("CHM101", self.sem1, "65", status_=ResultStatus.APPROVED_BY_DEAN)

        summary = term_summary(self.student, self.session, self.sem1)
        self.assertEqual(summary["credit_units"], 3)  # ratified sheet only

        self.inst.gpa_source_status = ResultStatus.APPROVED_BY_DEAN
        self.inst.save()
        self.student.refresh_from_db()
        summary = term_summary(self.student, self.session, self.sem1)
        self.assertEqual(summary["credit_units"], 2)  # now the dean-approved sheet

    def test_classification_bands_are_config_driven(self):
        self.inst.classification_bands = [
            {"name": "Distinction", "min_cgpa": "4.00"},
            {"name": "Merit", "min_cgpa": "3.00"},
            {"name": "Pass", "min_cgpa": "2.00"},
        ]
        self.inst.save()
        self.assertEqual(classify(self.inst, Decimal("4.10"))["name"], "Distinction")
        self.assertEqual(classify(self.inst, Decimal("2.50"))["name"], "Pass")
        self.assertEqual(classify(self.inst, Decimal("1.99"))["name"], "Fail")


class ApiAndScopeTests(GradingTestBase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="Physics", code="PHY"
        )
        self.adviser = _member(
            self.inst, "adviser@veritas.edu", Role.COURSE_ADVISER, department=self.dept
        )
        self.wrong_adviser = _member(
            self.inst, "adviser2@veritas.edu", Role.COURSE_ADVISER, department=self.other_dept
        )
        self.hod = _member(self.inst, "hod@veritas.edu", Role.HOD, department=self.dept)
        self.wrong_hod = _member(
            self.inst, "hod2@veritas.edu", Role.HOD, department=self.other_dept
        )
        self.other_student = _member(
            self.inst, "stud2@veritas.edu", Role.STUDENT, department=self.dept
        )
        self.foreign = Institution.objects.create(name="FUTO", code="futo")
        self.foreign_admin = _member(self.foreign, "admin@futo.edu", Role.SCHOOL_ADMIN)

        self.ratified_score("MTH101", self.sem1, "75")
        self.ratified_score("CHM101", self.sem1, "65")
        self.ratified_score("PHY101", self.sem1, "55")

    def test_student_reads_own_standing(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse("grading-my-standing"),
            {"session": str(self.session.id), "semester": str(self.sem1.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["term"]["gpa"], "4.00")
        self.assertEqual(data["cumulative"]["cgpa"], "4.00")
        self.assertEqual(data["standing"], "good")

    def test_student_cannot_read_another_students_standing(self):
        self.client.force_authenticate(self.other_student)
        response = self.client.get(reverse("grading-student-standing", args=[self.student.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_adviser_and_hod_scope(self):
        url = reverse("grading-student-standing", args=[self.student.id])
        for user, expected in [
            (self.adviser, status.HTTP_200_OK),
            (self.hod, status.HTTP_200_OK),
            (self.wrong_adviser, status.HTTP_403_FORBIDDEN),
            (self.wrong_hod, status.HTTP_403_FORBIDDEN),
        ]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(url).status_code, expected, user.email)

    def test_foreign_admin_cannot_see_student(self):
        self.client.force_authenticate(self.foreign_admin)
        response = self.client.get(reverse("grading-student-standing", args=[self.student.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def _trigger(self, user, department):
        return self.client.post(
            reverse("grading-compute"),
            {
                "department": str(department.id),
                "session": str(self.session.id),
                "semester": str(self.sem1.id),
            },
            format="json",
        )

    def test_compute_trigger_runs_task_and_persists_standings(self):
        self.client.force_authenticate(self.hod)
        with mock.patch(
            "grading.views.compute_department_standing.delay",
            side_effect=lambda *args: compute_department_standing(*args),
        ):
            response = self._trigger(self.hod, self.dept)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        row = AcademicStanding.all_objects.get(student=self.student)
        self.assertEqual(row.gpa, Decimal("4.00"))
        self.assertEqual(row.cgpa, Decimal("4.00"))
        self.assertEqual(row.standing, "good")
        self.assertEqual(row.classification, "Second Class Upper")
        # 4.00 is not within 0.05 of the 4.50 boundary.
        self.assertFalse(row.is_borderline)
        # The other student has no ratified rows: totals zero, no standing.
        empty = AcademicStanding.all_objects.get(student=self.other_student)
        self.assertIsNone(empty.cgpa)
        self.assertEqual(empty.standing, "")

    def test_compute_trigger_scope_enforced(self):
        self.client.force_authenticate(self.wrong_hod)
        response = self._trigger(self.wrong_hod, self.dept)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.student)
        response = self._trigger(self.student, self.dept)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_standing_list_scoped_to_hod_department(self):
        self.client.force_authenticate(self.hod)
        with mock.patch(
            "grading.views.compute_department_standing.delay",
            side_effect=lambda *args: compute_department_standing(*args),
        ):
            self._trigger(self.hod, self.dept)

        response = self.client.get(reverse("grading-standing-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["count"], 2)

        self.client.force_authenticate(self.wrong_hod)
        response = self.client.get(reverse("grading-standing-list"))
        self.assertEqual(response.data["data"]["count"], 0)
