"""Contract tests for the admin-console additions the frontend depends on:
the /me profile endpoint and the users (People) list/create/update endpoints.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Department, Faculty, Role, User
from tenancy.models import Institution
from tenancy.scoping import clear_current_institution, set_current_institution

PASSWORD = "SecurePass123!"


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=email.split("@")[0],
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class MeEndpointTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas University", code="veritas")
        self.admin = _member(self.inst, "admin@veritas.edu", Role.SCHOOL_ADMIN)

    def test_me_requires_authentication(self):
        self.assertEqual(
            self.client.get(reverse("auth-me")).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_me_returns_role_and_institution(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        data = response.data["data"]
        self.assertEqual(data["role"], Role.SCHOOL_ADMIN)
        self.assertEqual(data["institution_name"], "Veritas University")
        self.assertEqual(data["email"], "admin@veritas.edu")

    def test_me_works_with_real_login_token(self):
        # Mirrors the frontend: login -> use the access token -> GET /me.
        self.admin.set_password(PASSWORD)
        self.admin.save()
        login = self.client.post(
            reverse("auth-login"),
            {"email": "admin@veritas.edu", "password": PASSWORD},
            format="json",
        )
        access = login.data["data"]["access"]
        response = self.client.get(reverse("auth-me"), HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["role"], Role.SCHOOL_ADMIN)


class UsersEndpointTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas", code="veritas")
        self.other = Institution.objects.create(name="Other Uni", code="other")
        self.admin = _member(self.inst, "admin@veritas.edu", Role.SCHOOL_ADMIN)
        self.student = _member(self.inst, "student@veritas.edu", Role.STUDENT)
        _member(self.other, "outsider@other.edu", Role.LECTURER)

        self.faculty = Faculty.all_objects.create(
            institution=self.inst, name="Engineering", code="ENG"
        )
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="Mechanical", code="MEE"
        )

    def tearDown(self):
        clear_current_institution()

    def test_list_scoped_to_institution(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("user-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {u["email"] for u in response.data["data"]["results"]}
        self.assertIn("admin@veritas.edu", emails)
        self.assertIn("student@veritas.edu", emails)
        self.assertNotIn("outsider@other.edu", emails)

    def test_list_requires_school_admin(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(
            self.client.get(reverse("user-list")).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_create_person_sets_institution_and_unusable_password(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse("user-list"),
            {
                "full_name": "Ada Lovelace",
                "email": "ada@veritas.edu",
                "role": Role.LECTURER,
                "department": str(self.dept.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["department_name"], "Mechanical")
        created = User.objects.get(email="ada@veritas.edu")
        self.assertEqual(created.institution_id, self.inst.id)
        self.assertEqual(created.role, Role.LECTURER)
        self.assertFalse(created.has_usable_password())
        self.assertFalse(created.is_verified)

    def test_create_rejects_foreign_department(self):
        set_current_institution(self.other)
        foreign_faculty = Faculty.all_objects.create(
            institution=self.other, name="Arts", code="ART"
        )
        foreign_dept = Department.all_objects.create(
            institution=self.other, faculty=foreign_faculty, name="History", code="HIS"
        )
        clear_current_institution()

        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse("user-list"),
            {
                "full_name": "Wrong Scope",
                "email": "wrong@veritas.edu",
                "role": Role.STUDENT,
                "department": str(foreign_dept.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_role_and_deactivate(self):
        self.client.force_authenticate(self.admin)
        person = _member(self.inst, "reassign@veritas.edu", Role.STUDENT)

        patched = self.client.patch(
            reverse("user-detail", args=[person.id]),
            {"role": Role.HOD},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        person.refresh_from_db()
        self.assertEqual(person.role, Role.HOD)

        deactivated = self.client.patch(
            reverse("user-detail", args=[person.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(deactivated.status_code, status.HTTP_200_OK)
        person.refresh_from_db()
        self.assertFalse(person.is_active)

    def test_detail_scoped_to_institution(self):
        outsider = User.objects.get(email="outsider@other.edu")
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("user-detail", args=[outsider.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
