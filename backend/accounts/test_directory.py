"""Tests for the directory-scaling work: per-institution lecturer ranks, and
paginated + faculty/department-filtered users and courses listings.
"""

from datetime import date

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Faculty,
    Role,
    Semester,
    Session,
    User,
)
from tenancy.models import UNIVERSITY_LECTURER_RANKS, Institution

CONPCASS_RANKS = [
    "Lecturer III",
    "Lecturer II",
    "Lecturer I",
    "Senior Lecturer",
    "Principal Lecturer",
    "Chief Lecturer",
]


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0]),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class DirectoryTestBase(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        self.other = Institution.objects.create(name="Delta Poly", code="delta-poly")
        self.admin = _member(self.inst, "admin@veritas.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(self.admin)

        self.sci = Faculty.all_objects.create(institution=self.inst, name="Science", code="SCI")
        self.eng = Faculty.all_objects.create(institution=self.inst, name="Engineering", code="ENG")
        self.csc = Department.all_objects.create(
            institution=self.inst, faculty=self.sci, name="Computer Science", code="CSC"
        )
        self.mth = Department.all_objects.create(
            institution=self.inst, faculty=self.sci, name="Mathematics", code="MTH"
        )
        self.eee = Department.all_objects.create(
            institution=self.inst, faculty=self.eng, name="Electrical Engineering", code="EEE"
        )

        self.other_faculty = Faculty.all_objects.create(
            institution=self.other, name="Science", code="SCI"
        )
        self.other_dept = Department.all_objects.create(
            institution=self.other, faculty=self.other_faculty, name="Computer Science", code="CSC"
        )

    def page(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        return response.data["data"]


class LecturerRankTests(DirectoryTestBase):
    def test_institution_defaults_to_university_ladder(self):
        self.assertEqual(self.inst.lecturer_ranks, UNIVERSITY_LECTURER_RANKS)

    def test_config_endpoint_returns_ladder(self):
        response = self.client.get(reverse("institution-config"))
        self.assertEqual(self.page(response)["lecturer_ranks"], UNIVERSITY_LECTURER_RANKS)

    def test_create_lecturer_with_valid_rank(self):
        response = self.client.post(
            reverse("user-list"),
            {
                "email": "sl@veritas.edu",
                "full_name": "Senior Lecturer Person",
                "role": Role.LECTURER,
                "department": str(self.csc.id),
                "rank": "Senior Lecturer",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["rank"], "Senior Lecturer")

    def test_rank_outside_institution_ladder_rejected(self):
        response = self.client.post(
            reverse("user-list"),
            {
                "email": "cl@veritas.edu",
                "full_name": "Chief Lecturer Person",
                "role": Role.LECTURER,
                "rank": "Chief Lecturer",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rank", response.data["errors"])

    def test_conpcass_institution_accepts_its_own_ladder(self):
        self.other.lecturer_ranks = CONPCASS_RANKS
        self.other.save()
        poly_admin = _member(self.other, "admin@delta.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(poly_admin)

        response = self.client.post(
            reverse("user-list"),
            {
                "email": "cl@delta.edu",
                "full_name": "Chief Lecturer Person",
                "role": Role.LECTURER,
                "rank": "Chief Lecturer",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            reverse("user-list"),
            {
                "email": "prof@delta.edu",
                "full_name": "Professor Person",
                "role": Role.LECTURER,
                "rank": "Professor",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rank_rejected_for_non_lecturers(self):
        response = self.client.post(
            reverse("user-list"),
            {
                "email": "student@veritas.edu",
                "full_name": "Ranked Student",
                "role": Role.STUDENT,
                "rank": "Professor",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rank", response.data["errors"])

    def test_role_change_away_from_lecturer_clears_rank(self):
        lecturer = _member(self.inst, "prof@veritas.edu", Role.LECTURER, rank="Professor")
        response = self.client.patch(
            reverse("user-detail", args=[lecturer.id]),
            {"role": Role.EXAM_OFFICER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lecturer.refresh_from_db()
        self.assertEqual(lecturer.rank, "")

    def test_update_rank_validates_against_ladder(self):
        lecturer = _member(self.inst, "lect@veritas.edu", Role.LECTURER)
        url = reverse("user-detail", args=[lecturer.id])

        response = self.client.patch(url, {"rank": "Lecturer I"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["rank"], "Lecturer I")

        response = self.client.patch(url, {"rank": "Archchancellor"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserListScalingTests(DirectoryTestBase):
    def _seed(self, count, department, role=Role.STUDENT, prefix="user"):
        User.objects.bulk_create(
            User(
                email=f"{prefix}{i}@veritas.edu",
                full_name=f"{prefix.title()} {i:05d}",
                role=role,
                institution=self.inst,
                department=department,
                password="",
            )
            for i in range(count)
        )

    def test_list_is_always_paginated(self):
        self._seed(60, self.csc)
        data = self.page(self.client.get(reverse("user-list")))
        self.assertEqual(len(data["results"]), 25)
        self.assertEqual(data["count"], 61)  # 60 students + admin
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["total_pages"], 3)

    def test_page_and_page_size_params(self):
        self._seed(60, self.csc)
        data = self.page(self.client.get(reverse("user-list"), {"page": 3, "page_size": 10}))
        self.assertEqual(data["page"], 3)
        self.assertEqual(len(data["results"]), 10)
        self.assertEqual(data["total_pages"], 7)

    def test_page_size_is_capped(self):
        self._seed(120, self.csc)
        data = self.page(self.client.get(reverse("user-list"), {"page_size": 5000}))
        self.assertEqual(data["page_size"], 100)
        self.assertEqual(len(data["results"]), 100)

    def test_department_filter(self):
        self._seed(3, self.csc, prefix="csc")
        self._seed(2, self.mth, prefix="mth")
        data = self.page(self.client.get(reverse("user-list"), {"department": str(self.csc.id)}))
        self.assertEqual(data["count"], 3)
        self.assertTrue(all(row["department"] == self.csc.id for row in data["results"]))

    def test_faculty_filter_spans_departments_and_direct_scope(self):
        self._seed(3, self.csc, prefix="csc")
        self._seed(2, self.mth, prefix="mth")
        self._seed(4, self.eee, prefix="eee")
        _member(self.inst, "dean@veritas.edu", Role.DEAN, faculty=self.sci)

        data = self.page(self.client.get(reverse("user-list"), {"faculty": str(self.sci.id)}))
        self.assertEqual(data["count"], 6)  # 3 CSC + 2 MTH + the dean

    def test_filters_stay_tenant_isolated(self):
        self._seed(2, self.csc, prefix="ours")
        outsider = _member(self.other, "spy@delta.edu", Role.STUDENT, department=self.other_dept)
        data = self.page(self.client.get(reverse("user-list")))
        ids = {row["id"] for row in data["results"]}
        self.assertNotIn(str(outsider.id), ids)

        # Filtering by another tenant's department id must not leak its members.
        data = self.page(
            self.client.get(reverse("user-list"), {"department": str(self.other_dept.id)})
        )
        self.assertEqual(data["count"], 0)

    def test_role_search_and_active_filters(self):
        self._seed(2, self.csc, role=Role.LECTURER, prefix="lect")
        self._seed(2, self.csc, prefix="stud")
        User.objects.filter(email="stud0@veritas.edu").update(is_active=False)

        data = self.page(self.client.get(reverse("user-list"), {"role": Role.LECTURER}))
        self.assertEqual(data["count"], 2)

        data = self.page(self.client.get(reverse("user-list"), {"search": "lect1"}))
        self.assertEqual(data["count"], 1)

        data = self.page(self.client.get(reverse("user-list"), {"is_active": "false"}))
        self.assertEqual(data["count"], 1)

    def test_bad_filter_values_return_empty_not_error(self):
        self._seed(2, self.csc)
        for params in ({"department": "not-a-uuid"}, {"faculty": "nope"}, {"role": "wizard"}):
            data = self.page(self.client.get(reverse("user-list"), params))
            self.assertEqual(data["count"], 0)

    def test_large_directory_serves_single_pages(self):
        self._seed(1500, self.csc)
        data = self.page(self.client.get(reverse("user-list"), {"department": str(self.csc.id)}))
        self.assertEqual(data["count"], 1500)
        self.assertEqual(len(data["results"]), 25)
        self.assertEqual(data["total_pages"], 60)


class CourseListScalingTests(DirectoryTestBase):
    def _seed(self, count, department, level=100, prefix="CSC"):
        Course.all_objects.bulk_create(
            Course(
                institution=self.inst,
                department=department,
                code=f"{prefix} {level + i}",
                title=f"{prefix} Course {i}",
                credit_units=3,
                level=level,
            )
            for i in range(count)
        )

    def test_list_is_paginated_with_totals(self):
        self._seed(30, self.csc)
        data = self.page(self.client.get(reverse("course-list")))
        self.assertEqual(data["count"], 30)
        self.assertEqual(len(data["results"]), 25)
        self.assertEqual(data["total_pages"], 2)

    def test_faculty_department_and_level_filters(self):
        self._seed(3, self.csc, level=100, prefix="CSC")
        self._seed(2, self.mth, level=200, prefix="MTH")
        self._seed(4, self.eee, level=200, prefix="EEE")

        data = self.page(self.client.get(reverse("course-list"), {"faculty": str(self.sci.id)}))
        self.assertEqual(data["count"], 5)

        data = self.page(self.client.get(reverse("course-list"), {"department": str(self.mth.id)}))
        self.assertEqual(data["count"], 2)

        data = self.page(self.client.get(reverse("course-list"), {"level": "200"}))
        self.assertEqual(data["count"], 6)

        data = self.page(
            self.client.get(reverse("course-list"), {"faculty": str(self.sci.id), "level": "200"})
        )
        self.assertEqual(data["count"], 2)

    def test_search_matches_code_and_title(self):
        self._seed(3, self.csc, prefix="CSC")
        self._seed(2, self.mth, prefix="MTH")
        data = self.page(self.client.get(reverse("course-list"), {"search": "mth"}))
        self.assertEqual(data["count"], 2)

    def test_courses_stay_tenant_isolated(self):
        self._seed(2, self.csc)
        foreign = Course.all_objects.create(
            institution=self.other,
            department=self.other_dept,
            code="CSC 900",
            title="Foreign Course",
            credit_units=3,
        )
        data = self.page(self.client.get(reverse("course-list")))
        ids = {row["id"] for row in data["results"]}
        self.assertNotIn(str(foreign.id), ids)

        data = self.page(
            self.client.get(reverse("course-list"), {"department": str(self.other_dept.id)})
        )
        self.assertEqual(data["count"], 0)


class AssignmentListScalingTests(DirectoryTestBase):
    """The lecturer-assignment list is a directory too: an institution has one
    row per lecturer per course per term, so it paginates and drills down."""

    def setUp(self):
        super().setUp()
        self.session = Session.all_objects.create(
            institution=self.inst,
            name="2024/2025",
            start_date=date(2024, 9, 16),
            end_date=date(2025, 7, 31),
        )
        self.first = Semester.all_objects.create(
            institution=self.inst,
            session=self.session,
            name="First",
            start_date=date(2024, 9, 16),
            end_date=date(2025, 1, 31),
        )
        self.second = Semester.all_objects.create(
            institution=self.inst,
            session=self.session,
            name="Second",
            start_date=date(2025, 2, 10),
            end_date=date(2025, 6, 27),
        )
        self.csc_lecturer = _member(
            self.inst, "csc.lecturer@veritas.edu", Role.LECTURER, department=self.csc
        )
        self.eee_lecturer = _member(
            self.inst, "eee.lecturer@veritas.edu", Role.LECTURER, department=self.eee
        )

    def _course(self, department, code, level=100):
        return Course.all_objects.create(
            institution=self.inst,
            department=department,
            code=code,
            title=f"{code} Title",
            credit_units=3,
            level=level,
        )

    def _assign(self, lecturer, course, semester=None):
        return CourseAssignment.all_objects.create(
            institution=self.inst,
            lecturer=lecturer,
            course=course,
            session=self.session,
            semester=semester or self.first,
        )

    def test_list_is_paginated(self):
        for i in range(30):
            self._assign(self.csc_lecturer, self._course(self.csc, f"CSC {100 + i}"))
        data = self.page(self.client.get(reverse("assignment-list")))
        self.assertEqual(data["count"], 30)
        self.assertEqual(len(data["results"]), 25)
        self.assertEqual(data["total_pages"], 2)

    def test_faculty_department_and_level_filters(self):
        self._assign(self.csc_lecturer, self._course(self.csc, "CSC 101", level=100))
        self._assign(self.csc_lecturer, self._course(self.mth, "MTH 201", level=200))
        self._assign(self.eee_lecturer, self._course(self.eee, "EEE 201", level=200))

        data = self.page(self.client.get(reverse("assignment-list"), {"faculty": str(self.sci.id)}))
        self.assertEqual(data["count"], 2)

        data = self.page(
            self.client.get(reverse("assignment-list"), {"department": str(self.csc.id)})
        )
        self.assertEqual(data["count"], 1)

        data = self.page(self.client.get(reverse("assignment-list"), {"level": "200"}))
        self.assertEqual(data["count"], 2)

    def test_term_and_lecturer_filters(self):
        course = self._course(self.csc, "CSC 101")
        other = self._course(self.csc, "CSC 102")
        self._assign(self.csc_lecturer, course, semester=self.first)
        self._assign(self.eee_lecturer, other, semester=self.second)

        data = self.page(
            self.client.get(reverse("assignment-list"), {"semester": str(self.first.id)})
        )
        self.assertEqual(data["count"], 1)

        data = self.page(
            self.client.get(reverse("assignment-list"), {"session": str(self.session.id)})
        )
        self.assertEqual(data["count"], 2)

        data = self.page(
            self.client.get(reverse("assignment-list"), {"lecturer": str(self.eee_lecturer.id)})
        )
        self.assertEqual(data["count"], 1)

    def test_search_matches_course_and_lecturer(self):
        self._assign(self.csc_lecturer, self._course(self.csc, "CSC 101"))
        self._assign(self.eee_lecturer, self._course(self.eee, "EEE 201"))

        data = self.page(self.client.get(reverse("assignment-list"), {"search": "eee 2"}))
        self.assertEqual(data["count"], 1)

        data = self.page(
            self.client.get(reverse("assignment-list"), {"search": "csc.lecturer"[:3]})
        )
        self.assertGreaterEqual(data["count"], 1)

    def test_bad_filter_values_return_empty_not_error(self):
        self._assign(self.csc_lecturer, self._course(self.csc, "CSC 101"))
        for params in ({"faculty": "nonsense"}, {"semester": "nonsense"}, {"level": "abc"}):
            data = self.page(self.client.get(reverse("assignment-list"), params))
            self.assertEqual(data["count"], 0)

    def test_courses_filter_by_term_uses_assignments(self):
        taught = self._course(self.csc, "CSC 101")
        self._course(self.csc, "CSC 102")
        self._assign(self.csc_lecturer, taught, semester=self.first)

        data = self.page(self.client.get(reverse("course-list")))
        self.assertEqual(data["count"], 2)

        data = self.page(self.client.get(reverse("course-list"), {"semester": str(self.first.id)}))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["id"], str(taught.id))

        data = self.page(self.client.get(reverse("course-list"), {"semester": str(self.second.id)}))
        self.assertEqual(data["count"], 0)


class UserLevelFilterTests(DirectoryTestBase):
    def test_level_filter_narrows_students(self):
        for level in (100, 100, 200):
            User.objects.create_user(
                email=f"s{level}-{User.objects.count()}@veritas.edu",
                full_name="Student",
                role=Role.STUDENT,
                institution=self.inst,
                department=self.csc,
                current_level=level,
                is_verified=True,
            )
        data = self.page(
            self.client.get(reverse("user-list"), {"role": Role.STUDENT, "level": "100"})
        )
        self.assertEqual(data["count"], 2)

        data = self.page(self.client.get(reverse("user-list"), {"level": "abc"}))
        self.assertEqual(data["count"], 0)
