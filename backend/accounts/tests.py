import io

from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APITestCase

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Enrolment,
    Faculty,
    ImportJob,
    Role,
    Semester,
    Session,
    User,
)
from accounts.services import lecturer_can_access_course, validate_credit_load
from config.celery import app as celery_app
from tenancy.models import Institution
from tenancy.scoping import clear_current_institution, set_current_institution

PASSWORD = "SecurePass123!"
NEW_PASSWORD = "AnotherPass456!"


def _token_from_outbox(index=0):
    body = mail.outbox[index].body
    return body.split("token=")[1].strip()


class AuthAPITests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def setUp(self):
        self.register_url = reverse("auth-register")
        self.login_url = reverse("auth-login")
        self.logout_url = reverse("auth-logout")
        self.refresh_url = reverse("auth-token-refresh")
        self.verify_url = reverse("auth-verify-email")
        self.reset_url = reverse("auth-password-reset")
        self.reset_confirm_url = reverse("auth-password-reset-confirm")
        self.cookie_name = settings.AUTH_REFRESH_COOKIE_NAME

    def _register(self, email="user@example.com"):
        return self.client.post(
            self.register_url,
            {"email": email, "full_name": "Test User", "password": PASSWORD},
            format="json",
        )

    def _verify_latest(self):
        token = _token_from_outbox()
        return self.client.get(self.verify_url, {"token": token})

    def _login(self, email="user@example.com", password=PASSWORD):
        return self.client.post(
            self.login_url, {"email": email, "password": password}, format="json"
        )

    def test_register_creates_unverified_user_and_sends_email(self):
        response = self._register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["data"]["email"], "user@example.com")

        user = User.objects.get(email="user@example.com")
        self.assertFalse(user.is_verified)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Verify", mail.outbox[0].subject)

    def test_verify_email_marks_user_verified(self):
        self._register()

        response = self._verify_latest()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertTrue(User.objects.get(email="user@example.com").is_verified)

    def test_login_blocked_until_verified_then_returns_access_in_body(self):
        self._register()

        blocked = self._login()
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.data["status"], "error")

        self._verify_latest()
        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = response.data["data"]["access"]
        self.assertTrue(access)

        cookie = response.cookies[self.cookie_name]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "None")
        self.assertNotEqual(cookie.value, access)

    def test_token_refresh_reads_cookie_and_returns_new_access(self):
        self._register()
        self._verify_latest()
        self._login()

        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["access"])
        self.assertTrue(response.cookies[self.cookie_name].value)

    def test_logout_clears_cookie_and_blacklists_refresh(self):
        self._register()
        self._verify_latest()
        access = self._login().data["data"]["access"]
        old_refresh = self.client.cookies[self.cookie_name].value

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.post(self.logout_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.cookies[self.cookie_name].value, "")

        self.client.credentials()
        self.client.cookies[self.cookie_name] = old_refresh
        replay = self.client.post(self.refresh_url)
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_password_reset_request_and_confirm(self):
        self._register()
        self._verify_latest()
        mail.outbox.clear()

        request_response = self.client.post(
            self.reset_url, {"email": "user@example.com"}, format="json"
        )
        self.assertEqual(request_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

        token = _token_from_outbox()
        confirm_response = self.client.post(
            self.reset_confirm_url,
            {"token": token, "password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)

        self.assertEqual(self._login(password=PASSWORD).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self._login(password=NEW_PASSWORD).status_code, status.HTTP_200_OK)


def _member(institution, email, role):
    return User.objects.create_user(
        email=email,
        full_name=email.split("@")[0],
        role=role,
        institution=institution,
        is_verified=True,
    )


class AcademicHierarchyTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(self.admin)

    def _post(self, name, payload):
        return self.client.post(reverse(name), payload, format="json")

    def _build_chain(self):
        faculty = self._post("faculty-list", {"name": "Engineering", "code": "ENG"}).data["data"][
            "id"
        ]
        dept = self._post(
            "department-list", {"faculty": faculty, "name": "Computer Science", "code": "CSC"}
        ).data["data"]["id"]
        session = self._post(
            "session-list",
            {"name": "2024/2025", "start_date": "2024-09-01", "end_date": "2025-07-31"},
        ).data["data"]["id"]
        semester = self._post(
            "semester-list",
            {
                "session": session,
                "name": "First",
                "start_date": "2024-09-01",
                "end_date": "2024-12-20",
            },
        ).data["data"]["id"]
        course = self._post(
            "course-list",
            {
                "department": dept,
                "code": "CSC 101",
                "title": "Intro to CS",
                "credit_units": 3,
                "level": 100,
            },
        ).data["data"]["id"]
        return {
            "faculty": faculty,
            "dept": dept,
            "session": session,
            "semester": semester,
            "course": course,
        }

    def test_creates_full_hierarchy_and_stamps_institution(self):
        chain = self._build_chain()

        faculty = self.client.get(reverse("faculty-detail", args=[chain["faculty"]]))
        self.assertEqual(faculty.data["status"], "success")
        self.assertEqual(str(faculty.data["data"]["institution"]), str(self.inst.id))

        programme = self._post(
            "programme-list",
            {
                "department": chain["dept"],
                "name": "B.Sc Computer Science",
                "code": "CSC-BSC",
                "degree_type": "B.Sc",
            },
        )
        self.assertEqual(programme.status_code, status.HTTP_201_CREATED)

        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        enrolment = self._post(
            "enrolment-list",
            {
                "student": str(student.id),
                "course": chain["course"],
                "session": chain["session"],
                "semester": chain["semester"],
            },
        )
        self.assertEqual(enrolment.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Enrolment.all_objects.count(), 1)

    def test_course_inherits_weighting_and_override_must_sum_to_100(self):
        chain = self._build_chain()
        course = self.client.get(reverse("course-detail", args=[chain["course"]]))
        self.assertEqual(course.data["data"]["effective_ca_weight"], 40)
        self.assertEqual(course.data["data"]["effective_exam_weight"], 60)

        bad = self._post(
            "course-list",
            {
                "department": chain["dept"],
                "code": "CSC 102",
                "title": "X",
                "credit_units": 3,
                "level": 100,
                "ca_weight": 30,
                "exam_weight": 60,
            },
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        good = self._post(
            "course-list",
            {
                "department": chain["dept"],
                "code": "CSC 103",
                "title": "Y",
                "credit_units": 3,
                "level": 100,
                "ca_weight": 30,
                "exam_weight": 70,
            },
        )
        self.assertEqual(good.status_code, status.HTTP_201_CREATED)
        self.assertEqual(good.data["data"]["effective_ca_weight"], 30)

    def test_duplicate_faculty_code_rejected(self):
        self._post("faculty-list", {"name": "Engineering", "code": "ENG"})
        dup = self._post("faculty-list", {"name": "Engineering II", "code": "ENG"})
        self.assertEqual(dup.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_enrolment_rejected(self):
        chain = self._build_chain()
        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        payload = {
            "student": str(student.id),
            "course": chain["course"],
            "session": chain["session"],
            "semester": chain["semester"],
        }
        self.assertEqual(self._post("enrolment-list", payload).status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self._post("enrolment-list", payload).status_code, status.HTTP_400_BAD_REQUEST
        )

    def test_enrolment_rejects_semester_from_another_session(self):
        chain = self._build_chain()
        other_session = self._post(
            "session-list",
            {"name": "2025/2026", "start_date": "2025-09-01", "end_date": "2026-07-31"},
        ).data["data"]["id"]
        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        response = self._post(
            "enrolment-list",
            {
                "student": str(student.id),
                "course": chain["course"],
                "session": other_session,
                "semester": chain["semester"],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AcademicPermissionTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.student = _member(self.inst, "stud@futo.edu", Role.STUDENT)

    def test_unauthenticated_request_is_rejected(self):
        self.assertEqual(
            self.client.get(reverse("faculty-list")).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_student_cannot_make_structural_changes(self):
        self.client.force_authenticate(self.student)
        response = self.client.post(
            reverse("faculty-list"), {"name": "X", "code": "X"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tenant_member_can_read_catalog(self):
        self.client.force_authenticate(self.admin)
        self.client.post(reverse("faculty-list"), {"name": "Eng", "code": "ENG"}, format="json")

        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("faculty-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)

    def test_student_cannot_access_enrolments(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(
            self.client.get(reverse("enrolment-list")).status_code, status.HTTP_403_FORBIDDEN
        )


class AcademicIsolationTests(APITestCase):
    def setUp(self):
        self.futo = Institution.objects.create(name="FUTO", code="futo")
        self.topfaith = Institution.objects.create(name="Topfaith", code="topfaith")
        self.futo_admin = _member(self.futo, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.tf_admin = _member(self.topfaith, "admin@tf.edu", Role.SCHOOL_ADMIN)

    def _as(self, user):
        self.client.force_authenticate(user)

    def _build_chain(self):
        faculty = self.client.post(
            reverse("faculty-list"), {"name": "Eng", "code": "ENG"}, format="json"
        ).data["data"]["id"]
        dept = self.client.post(
            reverse("department-list"),
            {"faculty": faculty, "name": "CS", "code": "CSC"},
            format="json",
        ).data["data"]["id"]
        session = self.client.post(
            reverse("session-list"),
            {"name": "2024/2025", "start_date": "2024-09-01", "end_date": "2025-07-31"},
            format="json",
        ).data["data"]["id"]
        semester = self.client.post(
            reverse("semester-list"),
            {
                "session": session,
                "name": "First",
                "start_date": "2024-09-01",
                "end_date": "2024-12-20",
            },
            format="json",
        ).data["data"]["id"]
        course = self.client.post(
            reverse("course-list"),
            {
                "department": dept,
                "code": "CSC 101",
                "title": "Intro",
                "credit_units": 3,
                "level": 100,
            },
            format="json",
        ).data["data"]["id"]
        return {"session": session, "semester": semester, "course": course}

    def test_faculties_are_tenant_isolated(self):
        self._as(self.futo_admin)
        faculty_id = self.client.post(
            reverse("faculty-list"), {"name": "Eng", "code": "ENG"}, format="json"
        ).data["data"]["id"]

        self._as(self.tf_admin)
        self.assertEqual(self.client.get(reverse("faculty-list")).data["data"], [])
        self.assertEqual(
            self.client.get(reverse("faculty-detail", args=[faculty_id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(reverse("faculty-detail", args=[faculty_id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self._as(self.futo_admin)
        self.assertEqual(len(self.client.get(reverse("faculty-list")).data["data"]), 1)

    def test_courses_and_enrolments_are_tenant_isolated(self):
        self._as(self.futo_admin)
        chain = self._build_chain()
        student = _member(self.futo, "stud@futo.edu", Role.STUDENT)
        enrolment = self.client.post(
            reverse("enrolment-list"),
            {
                "student": str(student.id),
                "course": chain["course"],
                "session": chain["session"],
                "semester": chain["semester"],
            },
            format="json",
        )
        self.assertEqual(enrolment.status_code, status.HTTP_201_CREATED)

        self._as(self.tf_admin)
        self.assertEqual(self.client.get(reverse("course-list")).data["data"]["results"], [])
        self.assertEqual(self.client.get(reverse("enrolment-list")).data["data"], [])

    def test_cannot_enrol_a_student_from_another_institution(self):
        self._as(self.tf_admin)
        chain = self._build_chain()
        foreign_student = _member(self.futo, "stud@futo.edu", Role.STUDENT)
        response = self.client.post(
            reverse("enrolment-list"),
            {
                "student": str(foreign_student.id),
                "course": chain["course"],
                "session": chain["session"],
                "semester": chain["semester"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_link_department_to_another_institutions_faculty(self):
        self._as(self.futo_admin)
        foreign_faculty = self.client.post(
            reverse("faculty-list"), {"name": "Eng", "code": "ENG"}, format="json"
        ).data["data"]["id"]

        self._as(self.tf_admin)
        response = self.client.post(
            reverse("department-list"),
            {"faculty": foreign_faculty, "name": "CS", "code": "CSC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AcademicModelScopingTests(TestCase):
    def setUp(self):
        self.futo = Institution.objects.create(name="FUTO", code="futo")
        self.topfaith = Institution.objects.create(name="Topfaith", code="topfaith")

    def tearDown(self):
        clear_current_institution()

    def test_faculty_is_auto_scoped_and_stamped(self):
        set_current_institution(self.futo)
        faculty = Faculty.objects.create(name="Engineering", code="ENG")

        set_current_institution(self.topfaith)
        Faculty.objects.create(name="Sciences", code="SCI")

        set_current_institution(self.futo)
        self.assertEqual(list(Faculty.objects.values_list("name", flat=True)), ["Engineering"])
        self.assertEqual(faculty.institution, self.futo)

        clear_current_institution()
        self.assertEqual(Faculty.objects.count(), 0)
        self.assertEqual(Faculty.all_objects.count(), 2)


class AcademicExtensionTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(self.admin)

    def _chain(self):
        faculty = self.client.post(
            reverse("faculty-list"), {"name": "Eng", "code": "ENG"}, format="json"
        ).data["data"]["id"]
        dept = self.client.post(
            reverse("department-list"),
            {"faculty": faculty, "name": "CS", "code": "CSC"},
            format="json",
        ).data["data"]["id"]
        session = self.client.post(
            reverse("session-list"),
            {"name": "2024/2025", "start_date": "2024-09-01", "end_date": "2025-07-31"},
            format="json",
        ).data["data"]["id"]
        semester = self.client.post(
            reverse("semester-list"),
            {
                "session": session,
                "name": "First",
                "start_date": "2024-09-01",
                "end_date": "2024-12-20",
            },
            format="json",
        ).data["data"]["id"]
        return {"dept": dept, "session": session, "semester": semester}

    def _course(self, dept, code, units, level=100):
        return self.client.post(
            reverse("course-list"),
            {
                "department": dept,
                "code": code,
                "title": code,
                "credit_units": units,
                "level": level,
            },
            format="json",
        )

    def test_course_requires_and_stores_level(self):
        chain = self._chain()
        missing = self.client.post(
            reverse("course-list"),
            {"department": chain["dept"], "code": "X 100", "title": "X", "credit_units": 3},
            format="json",
        )
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)

        created = self._course(chain["dept"], "MTH 101", 3, level=200)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["data"]["level"], 200)

    def test_enrolment_is_not_constrained_by_level(self):
        chain = self._chain()
        course = self._course(chain["dept"], "GST 101", 3, level=100).data["data"]["id"]
        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        student.current_level = 300
        student.save(update_fields=["current_level"])

        response = self.client.post(
            reverse("enrolment-list"),
            {
                "student": str(student.id),
                "course": course,
                "session": chain["session"],
                "semester": chain["semester"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_enrolment_rejected_when_over_max_credit_load(self):
        chain = self._chain()
        big = self._course(chain["dept"], "ENG 101", 20, level=100).data["data"]["id"]
        more = self._course(chain["dept"], "ENG 102", 10, level=100).data["data"]["id"]
        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)

        ok = self.client.post(
            reverse("enrolment-list"),
            {
                "student": str(student.id),
                "course": big,
                "session": chain["session"],
                "semester": chain["semester"],
            },
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)

        over = self.client.post(
            reverse("enrolment-list"),
            {
                "student": str(student.id),
                "course": more,
                "session": chain["session"],
                "semester": chain["semester"],
            },
            format="json",
        )
        self.assertEqual(over.status_code, status.HTTP_400_BAD_REQUEST)

    def test_institution_credit_and_carryover_config_defaults(self):
        self.assertEqual(self.inst.min_credit_units_per_semester, 15)
        self.assertEqual(self.inst.max_credit_units_per_semester, 24)
        self.assertEqual(self.inst.carryover_cgpa_method, "ALL_ATTEMPTS")
        self.assertEqual(int(self.inst.carryover_pass_mark), 40)


class CreditLoadServiceTests(TestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")

    def test_validate_credit_load_enforces_bounds(self):
        with self.assertRaises(DRFValidationError):
            validate_credit_load(self.inst, 10)
        with self.assertRaises(DRFValidationError):
            validate_credit_load(self.inst, 30)
        validate_credit_load(self.inst, 18)


def _csv_upload(content, name="data.csv"):
    return SimpleUploadedFile(name, content.encode("utf-8"), content_type="text/csv")


def _xlsx_upload(rows, name="data.xlsx"):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _make_department(institution, dept_code="CSC"):
    set_current_institution(institution)
    faculty = Faculty.objects.create(name="Engineering", code="ENG")
    department = Department.objects.create(faculty=faculty, name="Computer Science", code=dept_code)
    clear_current_institution()
    return department


STUDENT_HEADER = "full_name,email,matric_number,department_code,current_level\n"
VALID_STUDENTS = STUDENT_HEADER + (
    "Ada Lovelace,ada@futo.edu,FUTO/2024/001,CSC,100\n"
    "Bola Ade,bola@futo.edu,FUTO/2024/002,CSC,200\n"
)


class BulkImportTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.dept = _make_department(self.inst)
        self.client.force_authenticate(self.admin)

    def _import(self, name, content):
        return self.client.post(reverse(name), {"file": _csv_upload(content)}, format="multipart")

    def test_student_import_creates_scoped_records(self):
        response = self._import("import-students", VALID_STUDENTS)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["data"]["created"], 2)
        self.assertEqual(response.data["data"]["skipped"], 0)
        self.assertIsNone(response.data["errors"])

        students = User.objects.filter(institution=self.inst, role=Role.STUDENT)
        self.assertEqual(students.count(), 2)
        ada = students.get(email="ada@futo.edu")
        self.assertEqual(ada.identifier, "FUTO/2024/001")
        self.assertEqual(ada.department, self.dept)
        self.assertEqual(ada.current_level, 100)
        self.assertFalse(ada.is_verified)
        self.assertFalse(ada.has_usable_password())

    def test_student_import_reports_row_errors(self):
        content = STUDENT_HEADER + (
            "Good Student,good@futo.edu,M1,CSC,100\n"
            "No Email,,M2,CSC,200\n"
            "Bad Dept,bad@futo.edu,M3,MEC,300\n"
            "Bad Level,lvl@futo.edu,M4,CSC,seven\n"
        )
        response = self._import("import-students", content)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["created"], 1)
        self.assertEqual(response.data["data"]["skipped"], 3)

        rows = {entry["row"]: entry["errors"] for entry in response.data["errors"]}
        self.assertEqual(set(rows), {3, 4, 5})
        self.assertTrue(any("email" in m for m in rows[3]))
        self.assertTrue(any("MEC" in m for m in rows[4]))
        self.assertTrue(any("number" in m for m in rows[5]))
        self.assertEqual(User.objects.filter(institution=self.inst, role=Role.STUDENT).count(), 1)

    def test_student_import_handles_duplicates(self):
        User.objects.create_user(
            email="dup@futo.edu",
            full_name="Existing",
            role=Role.STUDENT,
            institution=self.inst,
            identifier="M1",
        )
        content = STUDENT_HEADER + (
            "New One,new1@futo.edu,M1,CSC,100\n"
            "New Two,new2@futo.edu,M9,CSC,100\n"
            "New Three,new3@futo.edu,M9,CSC,100\n"
        )
        response = self._import("import-students", content)

        self.assertEqual(response.data["data"]["created"], 1)
        self.assertEqual(response.data["data"]["skipped"], 2)

    def test_course_import_weight_fallback_and_override(self):
        content = (
            "code,title,credit_units,level,department_code,ca_weight,exam_weight\n"
            "MTH 101,Calculus,3,100,CSC,,\n"
            "CSC 201,Algorithms,4,200,CSC,30,70\n"
        )
        response = self._import("import-courses", content)

        self.assertEqual(response.data["data"]["created"], 2)
        courses = Course.all_objects.filter(institution=self.inst)
        mth = courses.get(code="MTH 101")
        self.assertIsNone(mth.ca_weight)
        self.assertEqual(mth.effective_ca_weight, 40)
        csc = courses.get(code="CSC 201")
        self.assertEqual(csc.ca_weight, 30)
        self.assertEqual(csc.level, 200)

    def test_course_import_reports_bad_credit_units(self):
        content = "code,title,credit_units,level,department_code\nMTH 101,Calculus,three,100,CSC\n"
        response = self._import("import-courses", content)

        self.assertEqual(response.data["data"]["created"], 0)
        self.assertEqual(response.data["data"]["skipped"], 1)
        self.assertTrue(any("credit_units" in m for m in response.data["errors"][0]["errors"]))

    def test_course_code_duplicate_detected_case_insensitively(self):
        set_current_institution(self.inst)
        Course.objects.create(
            department=self.dept, code="CSC 101", title="Intro", credit_units=3, level=100
        )
        clear_current_institution()
        content = "code,title,credit_units,level,department_code\ncsc 101,Intro Again,3,100,csc\n"
        response = self._import("import-courses", content)

        self.assertEqual(response.data["data"]["created"], 0)
        self.assertEqual(response.data["data"]["skipped"], 1)
        self.assertTrue(any("already exists" in m for m in response.data["errors"][0]["errors"]))

    def test_import_is_tenant_isolated(self):
        self._import("import-students", VALID_STUDENTS)
        futo_count = User.objects.filter(institution=self.inst, role=Role.STUDENT).count()
        self.assertEqual(futo_count, 2)

        topfaith = Institution.objects.create(name="Topfaith", code="topfaith")
        tf_admin = _member(topfaith, "admin@tf.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(tf_admin)
        response = self._import("import-students", VALID_STUDENTS)

        self.assertEqual(response.data["data"]["created"], 0)
        self.assertTrue(
            all(any("not found" in m for m in entry["errors"]) for entry in response.data["errors"])
        )
        self.assertEqual(
            User.objects.filter(institution=self.inst, role=Role.STUDENT).count(), futo_count
        )
        self.assertEqual(User.objects.filter(institution=topfaith, role=Role.STUDENT).count(), 0)

    def test_cannot_poll_another_institutions_job(self):
        job = ImportJob.all_objects.create(
            institution=self.inst,
            kind=ImportJob.Kind.STUDENT,
            status=ImportJob.Status.COMPLETED,
        )
        topfaith = Institution.objects.create(name="Topfaith", code="topfaith")
        tf_admin = _member(topfaith, "admin@tf.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(tf_admin)

        response = self.client.get(reverse("import-job-detail", args=[job.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_role_cannot_import(self):
        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        self.client.force_authenticate(student)
        response = self._import("import-students", VALID_STUDENTS)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_xlsx_student_import_creates_records(self):
        upload = _xlsx_upload(
            [
                ["full_name", "email", "matric_number", "department_code", "current_level"],
                ["Ada Lovelace", "ada@futo.edu", "FUTO/2024/001", "CSC", 100],
                ["Bola Ade", "bola@futo.edu", "FUTO/2024/002", "CSC", 200],
            ]
        )
        response = self.client.post(
            reverse("import-students"), {"file": upload}, format="multipart"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["created"], 2)
        self.assertIsNone(response.data["errors"])
        ada = User.objects.get(institution=self.inst, email="ada@futo.edu")
        self.assertEqual(ada.identifier, "FUTO/2024/001")
        self.assertEqual(ada.current_level, 100)
        self.assertEqual(ada.department, self.dept)

    def test_lowercase_department_code_resolves_case_insensitively(self):
        content = STUDENT_HEADER + "Ada Lovelace,ada@futo.edu,FUTO/2024/001,csc,100\n"
        response = self._import("import-students", content)

        self.assertEqual(response.data["data"]["created"], 1)
        self.assertEqual(response.data["data"]["skipped"], 0)
        ada = User.objects.get(institution=self.inst, email="ada@futo.edu")
        self.assertEqual(ada.department, self.dept)

    def test_rejects_non_csv_file(self):
        upload = SimpleUploadedFile("data.txt", b"x,y\n1,2\n", content_type="text/plain")
        response = self.client.post(
            reverse("import-students"), {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(IMPORT_MAX_FILE_BYTES=16)
    def test_rejects_oversized_file(self):
        response = self._import("import-students", VALID_STUDENTS)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class BulkImportAsyncTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        _make_department(self.inst)
        self.client.force_authenticate(self.admin)

    @override_settings(IMPORT_SYNC_MAX_ROWS=0)
    def test_large_file_is_queued_and_job_is_pollable(self):
        response = self.client.post(
            reverse("import-students"), {"file": _csv_upload(VALID_STUDENTS)}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job_id = response.data["data"]["job_id"]

        poll = self.client.get(reverse("import-job-detail", args=[job_id]))
        self.assertEqual(poll.status_code, status.HTTP_200_OK)
        self.assertEqual(poll.data["data"]["status"], "completed")
        self.assertEqual(poll.data["data"]["created_count"], 2)
        self.assertEqual(User.objects.filter(institution=self.inst, role=Role.STUDENT).count(), 2)


def _academic_chain(institution, dept_code="CSC", course_code="CSC 101", session_name="2024/2025"):
    set_current_institution(institution)
    faculty = Faculty.objects.create(name="Engineering", code=f"ENG-{dept_code}")
    dept = Department.objects.create(faculty=faculty, name="Computer Science", code=dept_code)
    session = Session.objects.create(
        name=session_name, start_date="2024-09-01", end_date="2025-07-31"
    )
    semester = Semester.objects.create(
        session=session, name="First", start_date="2024-09-01", end_date="2024-12-20"
    )
    course = Course.objects.create(
        department=dept, code=course_code, title="Intro to CS", credit_units=3, level=100
    )
    clear_current_institution()
    return {"dept": dept, "session": session, "semester": semester, "course": course}


def _lecturer(institution, email="lect@futo.edu", department=None):
    lecturer = _member(institution, email, Role.LECTURER)
    if department is not None:
        lecturer.department = department
        lecturer.save(update_fields=["department"])
    return lecturer


class CourseAssignmentTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.chain = _academic_chain(self.inst)
        self.lecturer = _lecturer(self.inst, department=self.chain["dept"])
        self.client.force_authenticate(self.admin)

    def _payload(self, **overrides):
        payload = {
            "lecturer": str(self.lecturer.id),
            "course": str(self.chain["course"].id),
            "session": str(self.chain["session"].id),
            "semester": str(self.chain["semester"].id),
        }
        payload.update(overrides)
        return payload

    def _create(self, **overrides):
        return self.client.post(
            reverse("assignment-list"), self._payload(**overrides), format="json"
        )

    def test_admin_can_assign_lecturer_and_it_is_scoped(self):
        response = self._create()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "success")
        assignment = CourseAssignment.all_objects.get(id=response.data["data"]["id"])
        self.assertEqual(assignment.institution, self.inst)
        self.assertEqual(assignment.lecturer, self.lecturer)
        self.assertEqual(assignment.course, self.chain["course"])

    def test_duplicate_assignment_rejected(self):
        self._create()
        response = self._create()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_lecturers_can_be_assigned(self):
        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        response = self._create(lecturer=str(student.id))
        # Student is not in the lecturer-scoped queryset -> field validation error.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lecturer", response.data["errors"])

    def test_access_helper_true_for_assigned_and_false_otherwise(self):
        self._create()
        course, session, semester = (
            self.chain["course"],
            self.chain["session"],
            self.chain["semester"],
        )
        self.assertTrue(lecturer_can_access_course(self.lecturer, course, session, semester))

        other_lecturer = _lecturer(self.inst, "other@futo.edu", department=self.chain["dept"])
        self.assertFalse(lecturer_can_access_course(other_lecturer, course, session, semester))

        student = _member(self.inst, "stud@futo.edu", Role.STUDENT)
        self.assertFalse(lecturer_can_access_course(student, course, session, semester))

    def test_can_list_and_remove_assignment(self):
        created = self._create().data["data"]["id"]
        listed = self.client.get(reverse("assignment-list"))
        self.assertEqual(len(listed.data["data"]), 1)

        removed = self.client.delete(reverse("assignment-detail", args=[created]))
        self.assertEqual(removed.status_code, status.HTTP_200_OK)
        self.assertFalse(CourseAssignment.all_objects.filter(id=created).exists())

    def test_non_admin_role_forbidden(self):
        self.client.force_authenticate(self.lecturer)
        response = self._create()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_hod_can_assign_within_department_only(self):
        hod = _member(self.inst, "hod@futo.edu", Role.HOD)
        hod.department = self.chain["dept"]
        hod.save(update_fields=["department"])
        self.client.force_authenticate(hod)

        ok = self._create()
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)

        # A course in a different department is out of the HOD's scope.
        other = _academic_chain(
            self.inst, dept_code="MEC", course_code="MEC 101", session_name="2025/2026"
        )
        other_lecturer = _lecturer(self.inst, "meclect@futo.edu", department=other["dept"])
        blocked = self.client.post(
            reverse("assignment-list"),
            {
                "lecturer": str(other_lecturer.id),
                "course": str(other["course"].id),
                "session": str(other["session"].id),
                "semester": str(other["semester"].id),
            },
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("course", blocked.data["errors"])

    def test_assignments_are_tenant_isolated(self):
        self._create()

        topfaith = Institution.objects.create(name="Topfaith", code="topfaith")
        tf_admin = _member(topfaith, "admin@tf.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(tf_admin)

        # Cannot see the first institution's assignments.
        listed = self.client.get(reverse("assignment-list"))
        self.assertEqual(len(listed.data["data"]), 0)

        # Cannot create against the first institution's course/lecturer.
        blocked = self._create()
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CourseAssignment.all_objects.filter(institution=self.inst).count(), 1)
        self.assertEqual(CourseAssignment.all_objects.filter(institution=topfaith).count(), 0)


class LecturerReadAccessTests(APITestCase):
    """Lecturers may read their own assignments and the rosters of courses
    they teach; writes stay with admins/HODs."""

    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.chain = _academic_chain(self.inst)
        self.other_chain = _academic_chain(
            self.inst, dept_code="MEC", course_code="MEC 101", session_name="2025/2026"
        )
        self.lecturer = _lecturer(self.inst, department=self.chain["dept"])
        self.other_lecturer = _lecturer(
            self.inst, "other@futo.edu", department=self.other_chain["dept"]
        )
        self.student = _member(self.inst, "stud@futo.edu", Role.STUDENT)

        set_current_institution(self.inst)
        self.assignment = CourseAssignment.objects.create(
            lecturer=self.lecturer,
            course=self.chain["course"],
            session=self.chain["session"],
            semester=self.chain["semester"],
        )
        CourseAssignment.objects.create(
            lecturer=self.other_lecturer,
            course=self.other_chain["course"],
            session=self.other_chain["session"],
            semester=self.other_chain["semester"],
        )
        Enrolment.objects.create(
            student=self.student,
            course=self.chain["course"],
            session=self.chain["session"],
            semester=self.chain["semester"],
        )
        other_student = _member(self.inst, "stud2@futo.edu", Role.STUDENT)
        Enrolment.objects.create(
            student=other_student,
            course=self.other_chain["course"],
            session=self.other_chain["session"],
            semester=self.other_chain["semester"],
        )
        clear_current_institution()

    def test_lecturer_lists_only_their_own_assignments(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.get(reverse("assignment-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], str(self.assignment.id))

    def test_lecturer_cannot_write_assignments(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(reverse("assignment-list"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_list_assignments(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse("assignment-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_lecturer_sees_only_rosters_of_assigned_courses(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.get(reverse("enrolment-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["student"]), str(self.student.id))
        self.assertEqual(rows[0]["student_name"], self.student.full_name)
        self.assertEqual(rows[0]["student_identifier"], self.student.identifier)

    def test_enrolment_list_filters_by_course_term(self):
        self.client.force_authenticate(self.admin)
        url = reverse("enrolment-list")
        both = self.client.get(url)
        self.assertEqual(len(both.data["data"]), 2)
        filtered = self.client.get(
            url,
            {
                "course": str(self.chain["course"].id),
                "session": str(self.chain["session"].id),
                "semester": str(self.chain["semester"].id),
            },
        )
        self.assertEqual(len(filtered.data["data"]), 1)
        self.assertEqual(str(filtered.data["data"][0]["student"]), str(self.student.id))

    def test_lecturer_cannot_write_enrolments(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(reverse("enrolment-list"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CourseAssignmentImportTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="FUTO", code="futo")
        self.admin = _member(self.inst, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.chain = _academic_chain(self.inst)
        self.lecturer = _lecturer(self.inst, department=self.chain["dept"])
        self.client.force_authenticate(self.admin)

    def test_bulk_assignment_import_creates_and_reports(self):
        content = (
            "lecturer_email,course_code,session,semester\n"
            "lect@futo.edu,csc 101,2024/2025,First\n"
            "missing@futo.edu,CSC 101,2024/2025,First\n"
        )
        response = self.client.post(
            reverse("import-assignments"),
            {"file": _csv_upload(content)},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["created"], 1)
        self.assertEqual(response.data["data"]["skipped"], 1)
        self.assertEqual(CourseAssignment.all_objects.filter(institution=self.inst).count(), 1)
