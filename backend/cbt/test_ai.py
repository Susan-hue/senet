"""AI question generation tests. The Grok provider is always mocked — no test
touches the real API."""

from unittest.mock import MagicMock, patch

from django.test import override_settings
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
from cbt.ai import AIProviderError
from cbt.models import Question, QuestionBank
from tenancy.models import Institution
from tenancy.scoping import set_current_institution

RAW_QUESTIONS = [
    {"type": "mcq", "prompt": "2+2?", "options": ["3", "4", "5"], "correct_answer": 1, "marks": 2},
    {"type": "true_false", "prompt": "Water is wet.", "correct_answer": True, "marks": 1},
]


def _member(institution, email, role, **extra):
    return User.objects.create_user(
        email=email,
        full_name=email.split("@")[0],
        role=role,
        institution=institution,
        is_verified=True,
        **extra,
    )


class AIGenerationTests(APITestCase):
    def setUp(self):
        self.inst = Institution.objects.create(name="Veritas", code="veritas")
        self.faculty = Faculty.all_objects.create(institution=self.inst, name="Sci", code="SCI")
        self.dept = Department.all_objects.create(
            institution=self.inst, faculty=self.faculty, name="CS", code="CSC"
        )
        self.course = Course.all_objects.create(
            institution=self.inst,
            department=self.dept,
            code="CSC 101",
            title="Intro",
            credit_units=3,
        )
        self.session = Session.all_objects.create(
            institution=self.inst, name="2025/2026", start_date="2025-10-01", end_date="2026-07-31"
        )
        self.semester = Semester.all_objects.create(
            institution=self.inst,
            session=self.session,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        self.lecturer = _member(self.inst, "lect@veritas.edu", Role.LECTURER, department=self.dept)
        self.other_lecturer = _member(self.inst, "lect2@veritas.edu", Role.LECTURER)
        self.admin = _member(self.inst, "admin@veritas.edu", Role.SCHOOL_ADMIN)
        self.student = _member(self.inst, "stud@veritas.edu", Role.STUDENT)
        CourseAssignment.all_objects.create(
            institution=self.inst,
            lecturer=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
        )
        set_current_institution(self.inst)
        self.bank = QuestionBank.all_objects.create(
            institution=self.inst, course=self.course, title="Pool", created_by=self.lecturer
        )
        self.url = reverse("cbt-bank-generate", args=[self.bank.id])

    def _post(self, actor, body=None):
        self.client.force_authenticate(actor)
        return self.client.post(
            self.url, body or {"notes": "Photosynthesis converts light to energy.", "count": 2}
        )

    def test_generates_drafts_without_persisting(self):
        provider = MagicMock()
        provider.generate.return_value = RAW_QUESTIONS
        with patch("cbt.ai.get_provider", return_value=provider):
            response = self._post(self.lecturer)
        self.assertEqual(response.status_code, 200)
        drafts = response.data["data"]["drafts"]
        self.assertEqual(len(drafts), 2)
        self.assertEqual(drafts[0]["type"], "mcq")
        self.assertEqual(drafts[0]["correct_answer"], 1)
        self.assertEqual(
            set(drafts[0]),
            {"type", "prompt", "options", "correct_answer", "marks", "requires_manual_grading"},
        )
        # Nothing was written to the bank.
        self.assertEqual(Question.all_objects.filter(bank=self.bank).count(), 0)

    def test_only_authorized_managers_can_call(self):
        provider = MagicMock()
        provider.generate.return_value = RAW_QUESTIONS
        with patch("cbt.ai.get_provider", return_value=provider):
            self.assertEqual(self._post(self.student).status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(self._post(self.other_lecturer).status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(self._post(self.lecturer).status_code, 200)
            self.assertEqual(self._post(self.admin).status_code, 200)

    def test_all_drafts_malformed_is_reported_not_returned_as_an_empty_preview(self):
        provider = MagicMock()
        provider.generate.return_value = [
            {"type": "mcq", "prompt": "", "options": [], "correct_answer": 0},
            {"type": "not_a_type", "prompt": "Anything?"},
        ]
        with patch("cbt.ai.get_provider", return_value=provider):
            response = self._post(self.lecturer)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("no usable questions", response.data["message"])

    def test_provider_error_returns_clean_error_not_500(self):
        provider = MagicMock()
        provider.generate.side_effect = AIProviderError("The AI provider is unavailable.")
        with patch("cbt.ai.get_provider", return_value=provider):
            response = self._post(self.lecturer)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("unavailable", response.data["message"])

    @override_settings(GROK_API_KEY="")
    def test_unconfigured_provider_fails_cleanly_without_network(self):
        # No mock and no key: the real provider must fail clean (502), never hit
        # the network, never 500.
        with patch("cbt.ai.urllib.request.urlopen", side_effect=AssertionError("network!")):
            response = self._post(self.lecturer)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_only_lecturer_notes_are_sent_to_the_provider(self):
        provider = MagicMock()
        provider.generate.return_value = RAW_QUESTIONS
        notes = "Cellular respiration overview."
        with patch("cbt.ai.get_provider", return_value=provider):
            self._post(self.lecturer, {"notes": notes, "count": 3, "question_types": ["mcq"]})
        provider.generate.assert_called_once()
        kwargs = provider.generate.call_args.kwargs
        self.assertEqual(set(kwargs), {"notes", "count", "question_types"})
        self.assertEqual(kwargs["notes"], notes)
        # No student identity ever reaches the provider.
        self.assertNotIn(self.student.email, str(kwargs))
