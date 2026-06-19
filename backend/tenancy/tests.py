from django.db import models
from django.test import TransactionTestCase

from tenancy.models import Institution
from tenancy.scoping import (
    TenantScopedModel,
    clear_current_institution,
    set_current_institution,
)


class ScopeTestNote(TenantScopedModel):
    text = models.CharField(max_length=100)

    class Meta:
        app_label = "tenancy"


class TenantIsolationTests(TransactionTestCase):
    databases = {"default"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.db import connection

        with connection.constraint_checks_disabled():
            with connection.schema_editor(atomic=False) as schema_editor:
                schema_editor.create_model(ScopeTestNote)

    def setUp(self):
        self.futo = Institution.objects.create(name="FUTO", code="futo")
        self.topfaith = Institution.objects.create(name="Topfaith", code="topfaith")

    def tearDown(self):
        clear_current_institution()

    def test_writes_are_stamped_and_reads_are_scoped(self):
        set_current_institution(self.futo)
        ScopeTestNote.objects.create(text="FUTO broadsheet")

        set_current_institution(self.topfaith)
        ScopeTestNote.objects.create(text="Topfaith broadsheet")

        set_current_institution(self.futo)
        futo_notes = list(ScopeTestNote.objects.all())
        self.assertEqual(len(futo_notes), 1)
        self.assertEqual(futo_notes[0].text, "FUTO broadsheet")
        self.assertEqual(futo_notes[0].institution, self.futo)

        set_current_institution(self.topfaith)
        tf_notes = list(ScopeTestNote.objects.all())
        self.assertEqual(len(tf_notes), 1)
        self.assertEqual(tf_notes[0].text, "Topfaith broadsheet")

    def test_no_institution_context_returns_nothing(self):
        set_current_institution(self.futo)
        ScopeTestNote.objects.create(text="secret")
        clear_current_institution()
        self.assertEqual(ScopeTestNote.objects.count(), 0)
        self.assertEqual(ScopeTestNote.all_objects.count(), 1)
