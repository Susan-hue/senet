"""Shared fixtures for the course-scoped teaching apps' tests.

Builds two institutions so every suite can assert tenant isolation without
rebuilding the academic hierarchy three times. The default tenant carries a
course with an assigned lecturer, one enrolled student, one student enrolled in
a *different* course, and a second lecturer assigned to nothing.
"""

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
from tenancy.models import Institution


def make_user(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=extra.pop("full_name", email.split("@")[0].replace(".", " ").title()),
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


def make_chain(institution, *, dept_code="CSC", course_code="CSC 101", session_name="2024/2025"):
    faculty = Faculty.all_objects.create(
        institution=institution, name="Science", code=f"SCI-{dept_code}"
    )
    dept = Department.all_objects.create(
        institution=institution, faculty=faculty, name="Computer Science", code=dept_code
    )
    # A term is shared: two courses in the same institution sit in the same
    # session and semester, and both are unique per institution anyway.
    session, _ = Session.all_objects.get_or_create(
        institution=institution,
        name=session_name,
        defaults={"start_date": "2024-09-01", "end_date": "2025-07-31"},
    )
    semester, _ = Semester.all_objects.get_or_create(
        institution=institution,
        session=session,
        name="First",
        defaults={"start_date": "2024-09-01", "end_date": "2024-12-20"},
    )
    course = Course.all_objects.create(
        institution=institution,
        department=dept,
        code=course_code,
        title="Intro to CS",
        credit_units=3,
        level=100,
    )
    return {
        "faculty": faculty,
        "dept": dept,
        "session": session,
        "semester": semester,
        "course": course,
    }


def assign(institution, lecturer, chain):
    return CourseAssignment.all_objects.create(
        institution=institution,
        lecturer=lecturer,
        course=chain["course"],
        session=chain["session"],
        semester=chain["semester"],
    )


def enrol(institution, student, chain):
    return Enrolment.all_objects.create(
        institution=institution,
        student=student,
        course=chain["course"],
        session=chain["session"],
        semester=chain["semester"],
    )


class CourseWorkTestBase(APITestCase):
    """One course with a lecturer and an enrolled student, plus the people who
    must *not* get in: an unenrolled student, an unassigned lecturer, and a
    whole second institution."""

    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        self.chain = make_chain(self.inst)
        self.course = self.chain["course"]
        self.session = self.chain["session"]
        self.semester = self.chain["semester"]

        self.lecturer = make_user(self.inst, "ada.obi@veritas.edu", Role.LECTURER)
        self.lecturer.department = self.chain["dept"]
        self.lecturer.faculty = self.chain["faculty"]
        self.lecturer.save(update_fields=["department", "faculty"])
        assign(self.inst, self.lecturer, self.chain)

        # Assigned to a course of their own, so "a lecturer" is never enough.
        self.other_chain = make_chain(self.inst, dept_code="MTH", course_code="MTH 101")
        self.other_lecturer = make_user(self.inst, "emeka@veritas.edu", Role.LECTURER)
        assign(self.inst, self.other_lecturer, self.other_chain)

        self.student = make_user(self.inst, "chidi@veritas.edu", Role.STUDENT)
        enrol(self.inst, self.student, self.chain)

        self.other_student = make_user(self.inst, "ngozi@veritas.edu", Role.STUDENT)
        enrol(self.inst, self.other_student, self.other_chain)

        self.hod = make_user(self.inst, "hod@veritas.edu", Role.HOD)
        self.hod.department = self.chain["dept"]
        self.hod.save(update_fields=["department"])

        self.admin = make_user(self.inst, "admin@veritas.edu", Role.SCHOOL_ADMIN)

        # A second tenant with its own everything.
        self.foreign = Institution.objects.create(name="Topfaith", code="topfaith")
        self.foreign_chain = make_chain(self.foreign)
        self.foreign_lecturer = make_user(self.foreign, "lect@topfaith.edu", Role.LECTURER)
        assign(self.foreign, self.foreign_lecturer, self.foreign_chain)
        self.foreign_student = make_user(self.foreign, "stud@topfaith.edu", Role.STUDENT)
        enrol(self.foreign, self.foreign_student, self.foreign_chain)

    def term_params(self, chain=None):
        chain = chain or self.chain
        return {
            "course": str(chain["course"].id),
            "session": str(chain["session"].id),
            "semester": str(chain["semester"].id),
        }

    def as_(self, user):
        self.client.force_authenticate(user)
        return user

    def data(self, response):
        return response.data["data"]
