from django.conf import settings
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from config.celery import app as celery_app

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
