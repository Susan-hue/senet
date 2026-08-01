"""Announcement tests: who may post, who may read, ordering and pinning, and
the best-effort notification fan-out."""

from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from accounts.coursework_testing import CourseWorkTestBase
from announcements import services
from announcements.models import Announcement
from notifications.models import Notification, NotificationEvent


class AnnouncementTestBase(CourseWorkTestBase):
    def post_one(self, **overrides):
        payload = {
            "actor": self.lecturer,
            "course": self.course,
            "session": self.session,
            "semester": self.semester,
            "title": "Class moved",
            "body": "Thursday's class moves to LT2.",
            "notify": False,
        }
        payload.update(overrides)
        return services.create_announcement(**payload)


class PostingTests(AnnouncementTestBase):
    def test_assigned_lecturer_posts(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("announcement-list"),
            {
                **self.term_params(),
                "title": "Welcome",
                "body": "Read the outline.",
                "notify": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.data(response)["author"], self.lecturer.id)

    def test_unassigned_lecturer_cannot_post(self):
        self.as_(self.other_lecturer)
        response = self.client.post(
            reverse("announcement-list"),
            {**self.term_params(), "title": "Nope", "body": "x", "notify": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Announcement.all_objects.filter(title="Nope").exists())

    def test_student_cannot_post(self):
        self.as_(self.student)
        response = self.client.post(
            reverse("announcement-list"),
            {**self.term_params(), "title": "Student notice", "body": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_hod_of_the_department_may_post(self):
        announcement = self.post_one(actor=self.hod, title="Department notice")
        self.assertEqual(announcement.author_id, self.hod.id)

    def test_empty_body_is_rejected(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("announcement-list"),
            {**self.term_params(), "title": "Blank", "body": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lecturer_edits_and_deletes_own_announcement(self):
        announcement = self.post_one()
        self.as_(self.lecturer)
        url = reverse("announcement-detail", args=[announcement.id])

        patched = self.client.patch(url, {"title": "Class moved again"}, format="json")
        self.assertEqual(self.data(patched)["title"], "Class moved again")

        removed = self.client.delete(url)
        self.assertEqual(removed.status_code, status.HTTP_200_OK)
        self.assertFalse(Announcement.all_objects.filter(pk=announcement.pk).exists())

    def test_unassigned_lecturer_cannot_edit(self):
        announcement = self.post_one()
        self.as_(self.other_lecturer)
        response = self.client.patch(
            reverse("announcement-detail", args=[announcement.id]),
            {"title": "Mine"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ReadingTests(AnnouncementTestBase):
    def test_enrolled_student_reads_the_feed(self):
        self.post_one()
        self.as_(self.student)
        response = self.client.get(reverse("announcement-list"), self.term_params())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.data(response)["count"], 1)

    def test_non_enrolled_student_is_denied(self):
        self.post_one()
        self.as_(self.other_student)
        response = self.client.get(reverse("announcement-list"), self.term_params())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_student_without_a_course_filter_sees_only_their_own_courses(self):
        mine = self.post_one(title="For CSC 101")
        self.post_one(
            actor=self.other_lecturer,
            course=self.other_chain["course"],
            session=self.other_chain["session"],
            semester=self.other_chain["semester"],
            title="For MTH 101",
        )
        self.as_(self.student)
        response = self.client.get(reverse("announcement-list"))
        rows = self.data(response)["results"]
        self.assertEqual([row["id"] for row in rows], [str(mine.id)])

    def test_cross_tenant_announcement_is_invisible(self):
        foreign = services.create_announcement(
            actor=self.foreign_lecturer,
            course=self.foreign_chain["course"],
            session=self.foreign_chain["session"],
            semester=self.foreign_chain["semester"],
            title="Foreign notice",
            body="x",
            notify=False,
        )
        self.as_(self.lecturer)
        response = self.client.get(reverse("announcement-detail", args=[foreign.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.as_(self.student)
        listed = self.client.get(reverse("announcement-list"))
        ids = [row["id"] for row in self.data(listed)["results"]]
        self.assertNotIn(str(foreign.id), ids)


class OrderingTests(AnnouncementTestBase):
    def test_newest_first(self):
        first = self.post_one(title="First")
        second = self.post_one(title="Second")
        self.as_(self.student)
        response = self.client.get(reverse("announcement-list"), self.term_params())
        self.assertEqual(
            [row["id"] for row in self.data(response)["results"]],
            [str(second.id), str(first.id)],
        )

    def test_pinned_rows_come_first_however_old(self):
        pinned = self.post_one(title="Read this first", is_pinned=True)
        newer = self.post_one(title="Routine update")
        self.as_(self.student)
        response = self.client.get(reverse("announcement-list"), self.term_params())
        self.assertEqual(
            [row["id"] for row in self.data(response)["results"]],
            [str(pinned.id), str(newer.id)],
        )

    def test_pinning_an_existing_announcement_moves_it_up(self):
        older = self.post_one(title="Older")
        self.post_one(title="Newer")
        services.update_announcement(actor=self.lecturer, announcement=older, is_pinned=True)

        self.as_(self.student)
        response = self.client.get(reverse("announcement-list"), self.term_params())
        self.assertEqual(self.data(response)["results"][0]["id"], str(older.id))


class NotificationTests(AnnouncementTestBase):
    def test_posting_notifies_the_enrolled_class(self):
        self.post_one(notify=True)
        queued = Notification.all_objects.filter(
            event=NotificationEvent.ANNOUNCEMENT_POSTED, recipient=self.student
        )
        self.assertEqual(queued.count(), 1)
        # Only the class: a student on another course is not told.
        self.assertFalse(
            Notification.all_objects.filter(
                event=NotificationEvent.ANNOUNCEMENT_POSTED, recipient=self.other_student
            ).exists()
        )

    def test_notify_false_stays_quiet(self):
        self.post_one(notify=False)
        self.assertFalse(
            Notification.all_objects.filter(event=NotificationEvent.ANNOUNCEMENT_POSTED).exists()
        )

    def test_a_broken_notifier_does_not_cost_the_post(self):
        with patch(
            "notifications.services.notify_users", side_effect=RuntimeError("provider down")
        ):
            announcement = self.post_one(notify=True)
        self.assertTrue(Announcement.all_objects.filter(pk=announcement.pk).exists())

    def test_notification_permission_error_is_raised_before_any_post(self):
        with self.assertRaises(PermissionDenied):
            self.post_one(actor=self.other_lecturer, notify=True)
        self.assertEqual(Announcement.all_objects.count(), 0)
