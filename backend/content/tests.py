"""Content tests: authoring rights, enrolment-gated reads, draft and release
visibility, ordering, and read receipts."""

import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.coursework_testing import CourseWorkTestBase
from content import services
from content.models import ContentItem, ContentView, Module

TMP_MEDIA = tempfile.mkdtemp(prefix="senet-content-test-")


def _pdf(name="notes.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 senet", content_type="application/pdf")


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ContentTestBase(CourseWorkTestBase):
    def setUp(self):
        super().setUp()
        self.module = services.create_module(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title="Week 1 — Foundations",
            is_published=True,
        )

    def make_item(self, **overrides):
        payload = {
            "actor": self.lecturer,
            "module": self.module,
            "title": "Lecture notes",
            "kind": ContentItem.Kind.PAGE,
            "body": "Some content.",
            "is_published": True,
        }
        payload.update(overrides)
        return services.create_item(**payload)


class ModuleAuthoringTests(ContentTestBase):
    def test_assigned_lecturer_creates_a_module(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("content-module-list"),
            {**self.term_params(), "title": "Week 2", "is_published": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.data(response)["title"], "Week 2")

    def test_unassigned_lecturer_cannot_create_a_module(self):
        self.as_(self.other_lecturer)
        response = self.client.post(
            reverse("content-module-list"),
            {**self.term_params(), "title": "Hijack"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Module.all_objects.filter(title="Hijack").exists())

    def test_student_cannot_create_a_module(self):
        self.as_(self.student)
        response = self.client.post(
            reverse("content-module-list"),
            {**self.term_params(), "title": "Student module"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_hod_of_the_department_may_manage_content(self):
        module = services.create_module(
            actor=self.hod,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title="HOD module",
        )
        self.assertEqual(module.institution_id, self.inst.id)

    def test_duplicate_title_in_a_term_is_rejected(self):
        with self.assertRaises(ValidationError):
            services.create_module(
                actor=self.lecturer,
                course=self.course,
                session=self.session,
                semester=self.semester,
                title=self.module.title,
            )

    def test_lecturer_updates_and_deletes_own_module(self):
        self.as_(self.lecturer)
        url = reverse("content-module-detail", args=[self.module.id])
        patched = self.client.patch(url, {"title": "Week 1 — Renamed"}, format="json")
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(self.data(patched)["title"], "Week 1 — Renamed")

        removed = self.client.delete(url)
        self.assertEqual(removed.status_code, status.HTTP_200_OK)
        self.assertFalse(Module.all_objects.filter(pk=self.module.pk).exists())

    def test_deleting_a_module_takes_its_items(self):
        item = self.make_item()
        services.delete_module(actor=self.lecturer, module=self.module)
        self.assertFalse(ContentItem.all_objects.filter(pk=item.pk).exists())


class ModuleAccessTests(ContentTestBase):
    def test_enrolled_student_lists_published_modules(self):
        self.as_(self.student)
        response = self.client.get(reverse("content-module-list"), self.term_params())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.data(response)["count"], 1)

    def test_non_enrolled_student_is_denied(self):
        self.as_(self.other_student)
        response = self.client.get(reverse("content-module-list"), self.term_params())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_draft_module_is_hidden_from_students(self):
        services.update_module(actor=self.lecturer, module=self.module, is_published=False)

        self.as_(self.student)
        listed = self.client.get(reverse("content-module-list"), self.term_params())
        self.assertEqual(self.data(listed)["count"], 0)
        detail = self.client.get(reverse("content-module-detail", args=[self.module.id]))
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        # The lecturer still sees their own draft.
        self.as_(self.lecturer)
        listed = self.client.get(reverse("content-module-list"), self.term_params())
        self.assertEqual(self.data(listed)["count"], 1)

    def test_cross_tenant_module_is_not_visible(self):
        foreign_module = services.create_module(
            actor=self.foreign_lecturer,
            course=self.foreign_chain["course"],
            session=self.foreign_chain["session"],
            semester=self.foreign_chain["semester"],
            title="Foreign week 1",
            is_published=True,
        )
        self.as_(self.lecturer)
        response = self.client.get(reverse("content-module-detail", args=[foreign_module.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_tenant_course_id_is_rejected_on_create(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("content-module-list"),
            {**self.term_params(self.foreign_chain), "title": "Reach across"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_course_term_is_required_to_list(self):
        self.as_(self.lecturer)
        response = self.client.get(reverse("content-module-list"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ItemTests(ContentTestBase):
    def test_lecturer_uploads_a_file_item(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("content-item-list", args=[self.module.id]),
            {"title": "Slides", "kind": "file", "file": _pdf(), "is_published": True},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.data(response)["kind"], "file")
        self.assertTrue(self.data(response)["file_url"])

    def test_each_kind_demands_its_payload(self):
        for kind, missing in (("file", "file"), ("page", "body"), ("link", "url")):
            with self.assertRaises(ValidationError) as caught:
                services.create_item(
                    actor=self.lecturer, module=self.module, title=f"Empty {kind}", kind=kind
                )
            self.assertIn(missing, caught.exception.detail)

    def test_a_video_takes_either_an_upload_or_an_embed(self):
        embedded = self.make_item(
            title="Recorded lecture", kind="video", url="https://example.org/v/1", body=""
        )
        self.assertEqual(embedded.kind, "video")
        uploaded = self.make_item(
            title="Screen capture",
            kind="video",
            file=SimpleUploadedFile("clip.mp4", b"vid", content_type="video/mp4"),
            body="",
        )
        self.assertTrue(uploaded.file)
        with self.assertRaises(ValidationError):
            services.create_item(
                actor=self.lecturer, module=self.module, title="Empty video", kind="video"
            )

    def test_draft_item_is_hidden_from_students(self):
        self.make_item(title="Draft notes", is_published=False)
        published = self.make_item(title="Published notes", is_published=True)

        self.as_(self.student)
        response = self.client.get(reverse("content-item-list", args=[self.module.id]))
        ids = [row["id"] for row in self.data(response)["results"]]
        self.assertEqual(ids, [str(published.id)])

        self.as_(self.lecturer)
        response = self.client.get(reverse("content-item-list", args=[self.module.id]))
        self.assertEqual(self.data(response)["count"], 2)

    def test_unreleased_item_is_hidden_until_its_release_date(self):
        future = self.make_item(
            title="Next week", available_from=timezone.now() + timedelta(days=7)
        )
        past = self.make_item(title="Last week", available_from=timezone.now() - timedelta(days=1))

        self.as_(self.student)
        response = self.client.get(reverse("content-item-list", args=[self.module.id]))
        ids = [row["id"] for row in self.data(response)["results"]]
        self.assertIn(str(past.id), ids)
        self.assertNotIn(str(future.id), ids)

        detail = self.client.get(reverse("content-item-detail", args=[future.id]))
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_items_in_an_unpublished_module_stay_hidden(self):
        item = self.make_item(title="Ready but parked", is_published=True)
        services.update_module(actor=self.lecturer, module=self.module, is_published=False)

        self.as_(self.student)
        response = self.client.get(reverse("content-item-detail", args=[item.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_enrolled_student_cannot_read_items(self):
        item = self.make_item()
        self.as_(self.other_student)
        response = self.client.get(reverse("content-item-detail", args=[item.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unassigned_lecturer_cannot_edit_items(self):
        item = self.make_item()
        self.as_(self.other_lecturer)
        response = self.client.patch(
            reverse("content-item-detail", args=[item.id]), {"title": "Mine now"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_clearing_a_release_date_is_possible(self):
        item = self.make_item(available_from=timezone.now() + timedelta(days=3))
        self.as_(self.lecturer)
        response = self.client.patch(
            reverse("content-item-detail", args=[item.id]),
            {"available_from": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertIsNone(item.available_from)


class OrderingTests(ContentTestBase):
    def test_new_modules_land_at_the_end(self):
        second = services.create_module(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title="Week 2",
        )
        self.assertGreater(second.position, self.module.position)

    def test_reorder_rewrites_the_order(self):
        second = services.create_module(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title="Week 2",
            is_published=True,
        )
        self.as_(self.lecturer)
        response = self.client.post(
            f"{reverse('content-module-reorder')}?{self._qs()}",
            {"ids": [str(second.id), str(self.module.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order = [row["id"] for row in self.data(response)]
        self.assertEqual(order, [str(second.id), str(self.module.id)])

        listed = self.client.get(reverse("content-module-list"), self.term_params())
        self.assertEqual(
            [row["id"] for row in self.data(listed)["results"]],
            [str(second.id), str(self.module.id)],
        )

    def test_a_partial_reorder_is_rejected(self):
        services.create_module(
            actor=self.lecturer,
            course=self.course,
            session=self.session,
            semester=self.semester,
            title="Week 2",
        )
        with self.assertRaises(ValidationError):
            services.reorder_modules(
                actor=self.lecturer,
                course=self.course,
                session=self.session,
                semester=self.semester,
                module_ids=[str(self.module.id)],
            )

    def test_items_reorder_within_a_module(self):
        first = self.make_item(title="A")
        second = self.make_item(title="B")
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("content-item-reorder", args=[self.module.id]),
            {"ids": [str(second.id), str(first.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed = self.client.get(reverse("content-item-list", args=[self.module.id]))
        self.assertEqual(
            [row["id"] for row in self.data(listed)["results"]],
            [str(second.id), str(first.id)],
        )

    def _qs(self):
        params = self.term_params()
        return "&".join(f"{k}={v}" for k, v in params.items())


class ReadReceiptTests(ContentTestBase):
    def test_student_view_is_recorded_and_counted(self):
        item = self.make_item()
        self.as_(self.student)
        url = reverse("content-item-view", args=[item.id])

        first = self.client.post(url)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(self.data(first)["view_count"], 1)

        second = self.client.post(url)
        self.assertEqual(self.data(second)["view_count"], 2)
        self.assertEqual(ContentView.all_objects.filter(item=item).count(), 1)

    def test_viewed_flag_comes_back_on_the_listing(self):
        seen = self.make_item(title="Seen")
        self.make_item(title="Unseen")
        services.record_view(student=self.student, item=seen)

        self.as_(self.student)
        response = self.client.get(reverse("content-item-list", args=[self.module.id]))
        flags = {row["title"]: row["viewed"] for row in self.data(response)["results"]}
        self.assertTrue(flags["Seen"])
        self.assertFalse(flags["Unseen"])

    def test_a_student_cannot_leave_a_receipt_on_hidden_content(self):
        item = self.make_item(is_published=False)
        with self.assertRaises(PermissionDenied):
            services.record_view(student=self.student, item=item)

    def test_non_enrolled_student_cannot_record_a_view(self):
        item = self.make_item()
        self.as_(self.other_student)
        response = self.client.post(reverse("content-item-view", args=[item.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_reading_their_own_material_leaves_no_receipt(self):
        item = self.make_item()
        self.assertIsNone(services.record_view(student=self.lecturer, item=item))

    def test_lecturer_reads_who_has_opened_an_item(self):
        item = self.make_item()
        services.record_view(student=self.student, item=item)

        self.as_(self.lecturer)
        response = self.client.get(reverse("content-item-views", args=[item.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self.data(response)["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["student"]), str(self.student.id))

    def test_students_cannot_read_the_receipt_list(self):
        item = self.make_item()
        self.as_(self.student)
        response = self.client.get(reverse("content-item-views", args=[item.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
