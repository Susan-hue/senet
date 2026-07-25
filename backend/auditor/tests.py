"""NUC Auditor Vault tests: token lifecycle (time-boxed, revocable, scope-
limited), tenant isolation, the read-only guarantee, and access logging."""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import Course, Department, Faculty, Programme, Role, Semester, Session
from auditor.models import AuditorAccessLog, AuditorToken, hash_token
from auditor.services import create_auditor_token, revoke_auditor_token
from results.exports import XLSX_CONTENT_TYPE
from results.models import CourseResult, ResultStatus, StudentScore
from results.services import create_external_examiner_report
from results.tests import ApprovalTestBase, _member
from tenancy.models import Institution


class AuditorVaultTestBase(ApprovalTestBase):
    def setUp(self):
        super().setUp()
        self.school_admin = _member(self.inst, "sadmin@veritas.edu", Role.SCHOOL_ADMIN)
        self.programme = Programme.all_objects.create(
            institution=self.inst,
            department=self.dept,
            name="Computer Science",
            code="CSC-BSC",
            degree_type="B.Sc",
        )
        self.result = self.advance_to(self.make_submitted(), ResultStatus.RATIFIED_BY_SENATE)

    def make_token(self, programmes=None, sessions=None, days=7, actor=None):
        if programmes is None:
            programmes = [self.programme]
        if sessions is None:
            sessions = []
        return create_auditor_token(
            actor=actor or self.school_admin,
            label="NUC audit 2026",
            expires_at=timezone.now() + timedelta(days=days),
            programmes=programmes,
            sessions=sessions,
        )

    def auth(self, raw):
        self.client.credentials(HTTP_X_AUDITOR_TOKEN=raw)

    def _direct_result(
        self,
        *,
        department=None,
        session=None,
        semester=None,
        code="ZZZ 999",
        result_status=ResultStatus.RATIFIED_BY_SENATE,
    ):
        """Insert a result directly (bypassing the pipeline) to build out-of-scope
        or non-ratified fixtures the read-only auditor path should filter out."""
        department = department or self.dept
        session = session or self.session
        semester = semester or self.semester
        course = Course.all_objects.create(
            institution=self.inst, department=department, code=code, title="Other", credit_units=3
        )
        result = CourseResult.all_objects.create(
            institution=self.inst,
            course=course,
            session=session,
            semester=semester,
            lecturer=self.lecturer,
            status=result_status,
        )
        StudentScore.all_objects.create(
            institution=self.inst,
            result=result,
            student=self.student,
            ca_score=Decimal("20"),
            exam_score=Decimal("20"),
            total=Decimal("40"),
            grade="E",
        )
        return result

    def _foreign_ratified_result(self):
        foreign = Institution.objects.create(name="FUTO", code="futo")
        ffac = Faculty.all_objects.create(institution=foreign, name="Science", code="SCI")
        fdept = Department.all_objects.create(
            institution=foreign, faculty=ffac, name="Computer Science", code="CSC"
        )
        fsession = Session.all_objects.create(
            institution=foreign, name="2025/2026", start_date="2025-10-01", end_date="2026-07-31"
        )
        fsem = Semester.all_objects.create(
            institution=foreign,
            session=fsession,
            name="First",
            start_date="2025-10-01",
            end_date="2026-02-28",
        )
        fcourse = Course.all_objects.create(
            institution=foreign, department=fdept, code="CSC 101", title="x", credit_units=3
        )
        flect = _member(foreign, "lect@futo.edu", Role.LECTURER, department=fdept)
        fresult = CourseResult.all_objects.create(
            institution=foreign,
            course=fcourse,
            session=fsession,
            semester=fsem,
            lecturer=flect,
            status=ResultStatus.RATIFIED_BY_SENATE,
        )
        return foreign, fresult


class TokenManagementTests(AuditorVaultTestBase):
    def test_school_admin_creates_token_and_receives_raw_once(self):
        self.client.force_authenticate(self.school_admin)
        response = self.client.post(
            reverse("auditor-token-list"),
            {
                "label": "NUC 2026",
                "expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
                "programmes": [str(self.programme.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        raw = response.data["data"]["token"]
        self.assertTrue(raw)
        token = AuditorToken.all_objects.get(pk=response.data["data"]["id"])
        # Only the hash is stored; the raw value never lands in the database.
        self.assertEqual(token.token_hash, hash_token(raw))
        self.assertNotEqual(token.token_hash, raw)

    def test_non_admin_cannot_create_token(self):
        self.client.force_authenticate(self.dean)
        response = self.client.post(
            reverse("auditor-token-list"),
            {
                "label": "x",
                "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
                "programmes": [str(self.programme.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_token_requires_a_scope(self):
        self.client.force_authenticate(self.school_admin)
        response = self.client.post(
            reverse("auditor-token-list"),
            {"label": "x", "expires_at": (timezone.now() + timedelta(days=1)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tokens_are_tenant_scoped_in_listing(self):
        self.make_token()
        foreign = Institution.objects.create(name="FUTO", code="futo")
        foreign_admin = _member(foreign, "admin@futo.edu", Role.SCHOOL_ADMIN)
        self.client.force_authenticate(foreign_admin)
        response = self.client.get(reverse("auditor-token-list"))
        self.assertEqual(response.data["data"]["count"], 0)


class AuditorAccessTests(AuditorVaultTestBase):
    def test_valid_token_lists_in_scope_ratified_results(self):
        _token, raw = self.make_token()
        self.auth(raw)
        response = self.client.get(reverse("auditor-result-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["count"], 1)

    def test_detail_exposes_scores_stats_approval_log_and_marking_scheme(self):
        _token, raw = self.make_token()
        self.auth(raw)
        response = self.client.get(reverse("auditor-result-detail", args=[self.result.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data["scores"]), 1)
        self.assertIn("grade_distribution", data["statistics"])
        self.assertTrue(
            any(
                entry["to_status"] == ResultStatus.RATIFIED_BY_SENATE
                for entry in data["approval_log"]
            )
        )
        self.assertIsInstance(data["marking_scheme"], list)

    def test_broadsheet_and_ogr_downloads(self):
        _token, raw = self.make_token()
        self.auth(raw)
        broadsheet = self.client.get(reverse("auditor-result-broadsheet", args=[self.result.id]))
        self.assertEqual(broadsheet.status_code, status.HTTP_200_OK)
        self.assertEqual(broadsheet["Content-Type"], XLSX_CONTENT_TYPE)
        ogr = self.client.get(reverse("auditor-result-ogr", args=[self.result.id]))
        self.assertEqual(ogr.status_code, status.HTTP_200_OK)
        self.assertTrue(ogr.content.startswith(b"%PDF"))

    def test_examiner_reports_are_visible_in_scope(self):
        create_external_examiner_report(
            actor=self.dean,
            programme=self.programme,
            session=self.session,
            semester=self.semester,
            examiner_name="Prof. Ada Okoro",
            examiner_institution="University of Lagos",
            audit_date="2026-06-15",
        )
        _token, raw = self.make_token()
        self.auth(raw)
        response = self.client.get(reverse("auditor-examiner-reports"))
        self.assertEqual(response.data["data"]["count"], 1)

    def test_only_ratified_results_are_visible(self):
        self._direct_result(code="CSC 102", result_status=ResultStatus.SUBMITTED_TO_HOD)
        _token, raw = self.make_token()
        self.auth(raw)
        response = self.client.get(reverse("auditor-result-list"))
        self.assertEqual(response.data["data"]["count"], 1)


class AuditorTokenValidityTests(AuditorVaultTestBase):
    def test_expired_token_is_rejected(self):
        token, raw = self.make_token()
        AuditorToken.all_objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        self.auth(raw)
        self.assertEqual(
            self.client.get(reverse("auditor-result-list")).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_revoked_token_is_rejected(self):
        token, raw = self.make_token()
        revoke_auditor_token(actor=self.school_admin, token=token)
        self.auth(raw)
        self.assertEqual(
            self.client.get(reverse("auditor-result-list")).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_invalid_token_is_rejected(self):
        self.auth("this-is-not-a-valid-token")
        self.assertEqual(
            self.client.get(reverse("auditor-result-list")).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_missing_token_is_rejected(self):
        self.assertEqual(
            self.client.get(reverse("auditor-result-list")).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class AuditorScopeIsolationTests(AuditorVaultTestBase):
    def test_programme_scope_limits_visible_results(self):
        out = self._direct_result(department=self.other_dept, code="EEE 101")
        _token, raw = self.make_token(programmes=[self.programme])
        self.auth(raw)
        response = self.client.get(reverse("auditor-result-list"))
        ids = [row["id"] for row in response.data["data"]["results"]]
        self.assertIn(str(self.result.id), ids)
        self.assertNotIn(str(out.id), ids)
        self.assertEqual(
            self.client.get(reverse("auditor-result-detail", args=[out.id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_session_scope_limits_visible_results(self):
        other_session = Session.all_objects.create(
            institution=self.inst, name="2024/2025", start_date="2024-10-01", end_date="2025-07-31"
        )
        other_semester = Semester.all_objects.create(
            institution=self.inst,
            session=other_session,
            name="First",
            start_date="2024-10-01",
            end_date="2025-02-28",
        )
        out = self._direct_result(session=other_session, semester=other_semester, code="CSC 201")
        _token, raw = self.make_token(programmes=[], sessions=[self.session])
        self.auth(raw)
        response = self.client.get(reverse("auditor-result-list"))
        ids = [row["id"] for row in response.data["data"]["results"]]
        self.assertIn(str(self.result.id), ids)
        self.assertNotIn(str(out.id), ids)

    def test_token_is_tenant_isolated(self):
        _foreign, fresult = self._foreign_ratified_result()
        _token, raw = self.make_token()
        self.auth(raw)
        response = self.client.get(reverse("auditor-result-list"))
        ids = [row["id"] for row in response.data["data"]["results"]]
        self.assertNotIn(str(fresult.id), ids)
        self.assertEqual(
            self.client.get(reverse("auditor-result-detail", args=[fresult.id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )


class AuditorReadOnlyTests(AuditorVaultTestBase):
    def test_write_methods_are_rejected_on_the_auditor_path(self):
        _token, raw = self.make_token()
        self.auth(raw)
        # Two independent backstops refuse every write: the IsValidAuditor
        # permission rejects any non-SAFE method (403), and the views expose only
        # GET/HEAD/OPTIONS (405). Either way, no write reaches a handler.
        refused = {status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED}
        for verb in ("post", "put", "patch", "delete"):
            request = getattr(self.client, verb)
            self.assertIn(request(reverse("auditor-result-list")).status_code, refused, verb)
            self.assertIn(
                request(reverse("auditor-result-detail", args=[self.result.id])).status_code,
                refused,
                verb,
            )

    def test_auditor_token_grants_no_write_power_on_the_pipeline(self):
        _token, raw = self.make_token()
        # Presenting the auditor token to a normal pipeline write endpoint: the
        # JWT authenticator ignores it, so the request is unauthenticated and the
        # write is refused. The token confers no write power anywhere.
        self.client.credentials(HTTP_X_AUDITOR_TOKEN=raw)
        response = self.client.post(reverse("result-raise-amendment", args=[self.result.id]))
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_every_auditor_access_is_logged(self):
        _token, raw = self.make_token()
        self.auth(raw)
        self.client.get(reverse("auditor-result-list"))
        self.client.get(reverse("auditor-result-detail", args=[self.result.id]))
        logs = AuditorAccessLog.all_objects.all()
        self.assertGreaterEqual(logs.count(), 2)
        self.assertEqual(set(logs.values_list("method", flat=True)), {"GET"})
        self.assertIn("results", set(logs.values_list("resource", flat=True)))
        self.assertIn("result_detail", set(logs.values_list("resource", flat=True)))

    def test_rejected_access_is_not_logged_as_a_read(self):
        self.auth("bogus-token")
        self.client.get(reverse("auditor-result-list"))
        self.assertEqual(AuditorAccessLog.all_objects.count(), 0)
