from django.conf import settings
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APITestCase

from accounts.models import Enrolment, Faculty, Role, User
from accounts.services import validate_credit_load
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
        self.assertEqual(self.client.get(reverse("course-list")).data["data"], [])
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
