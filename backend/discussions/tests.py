"""Discussion tests: who may take part, who may moderate, and that a board
never leaks past its course or its tenant."""

from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.coursework_testing import CourseWorkTestBase
from discussions import services
from discussions.models import Reply, Thread


class DiscussionTestBase(CourseWorkTestBase):
    def start_thread(self, **overrides):
        payload = {
            "actor": self.student,
            "course": self.course,
            "session": self.session,
            "semester": self.semester,
            "title": "Question about pointers",
            "body": "Why does this segfault?",
        }
        payload.update(overrides)
        return services.create_thread(**payload)


class ThreadParticipationTests(DiscussionTestBase):
    def test_enrolled_student_starts_a_thread(self):
        self.as_(self.student)
        response = self.client.post(
            reverse("discussion-thread-list"),
            {**self.term_params(), "title": "Week 1 question", "body": "How do I start?"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.data(response)["author"], self.student.id)

    def test_assigned_lecturer_starts_a_thread(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("discussion-thread-list"),
            {**self.term_params(), "title": "Reading list", "body": "Chapters 1-3."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_non_enrolled_student_cannot_start_a_thread(self):
        self.as_(self.other_student)
        response = self.client.post(
            reverse("discussion-thread-list"),
            {**self.term_params(), "title": "Intruding", "body": "hello"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Thread.all_objects.filter(title="Intruding").exists())

    def test_unassigned_lecturer_cannot_start_a_thread(self):
        with self.assertRaises(PermissionDenied):
            self.start_thread(actor=self.other_lecturer)

    def test_a_student_cannot_pin_their_own_thread(self):
        thread = self.start_thread(is_pinned=True)
        self.assertFalse(thread.is_pinned)

    def test_a_lecturer_may_pin_on_creation(self):
        thread = self.start_thread(actor=self.lecturer, is_pinned=True)
        self.assertTrue(thread.is_pinned)

    def test_empty_body_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.start_thread(body="   ")

    def test_cross_tenant_course_is_rejected(self):
        self.as_(self.lecturer)
        response = self.client.post(
            reverse("discussion-thread-list"),
            {**self.term_params(self.foreign_chain), "title": "Reach", "body": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ThreadVisibilityTests(DiscussionTestBase):
    def test_enrolled_student_lists_the_board(self):
        thread = self.start_thread()
        self.as_(self.student)
        response = self.client.get(reverse("discussion-thread-list"), self.term_params())
        self.assertEqual(self.data(response)["count"], 1)
        self.assertEqual(self.data(response)["results"][0]["id"], str(thread.id))

    def test_non_enrolled_student_is_denied_the_board(self):
        self.start_thread()
        self.as_(self.other_student)
        response = self.client.get(reverse("discussion-thread-list"), self.term_params())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_student_sees_only_their_own_courses_unfiltered(self):
        mine = self.start_thread()
        services.create_thread(
            actor=self.other_student,
            course=self.other_chain["course"],
            session=self.other_chain["session"],
            semester=self.other_chain["semester"],
            title="Other course",
            body="x",
        )
        self.as_(self.student)
        response = self.client.get(reverse("discussion-thread-list"))
        self.assertEqual([row["id"] for row in self.data(response)["results"]], [str(mine.id)])

    def test_cross_tenant_thread_is_invisible(self):
        foreign = services.create_thread(
            actor=self.foreign_student,
            course=self.foreign_chain["course"],
            session=self.foreign_chain["session"],
            semester=self.foreign_chain["semester"],
            title="Foreign thread",
            body="x",
        )
        self.as_(self.student)
        response = self.client.get(reverse("discussion-thread-detail", args=[foreign.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pinned_threads_lead_the_board(self):
        self.start_thread(title="Ordinary")
        pinned = self.start_thread(actor=self.lecturer, title="Read me", is_pinned=True)
        self.as_(self.student)
        response = self.client.get(reverse("discussion-thread-list"), self.term_params())
        self.assertEqual(self.data(response)["results"][0]["id"], str(pinned.id))

    def test_detail_tells_the_caller_whether_they_moderate(self):
        thread = self.start_thread()
        url = reverse("discussion-thread-detail", args=[thread.id])

        self.as_(self.lecturer)
        self.assertTrue(self.data(self.client.get(url))["can_moderate"])

        self.as_(self.student)
        self.assertFalse(self.data(self.client.get(url))["can_moderate"])


class ReplyTests(DiscussionTestBase):
    def setUp(self):
        super().setUp()
        self.thread = self.start_thread()

    def test_enrolled_student_and_lecturer_may_reply(self):
        for actor in (self.student, self.lecturer):
            self.as_(actor)
            response = self.client.post(
                reverse("discussion-reply-list", args=[self.thread.id]),
                {"body": f"Reply from {actor.role}"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Reply.all_objects.filter(thread=self.thread).count(), 2)

    def test_non_enrolled_student_cannot_reply(self):
        self.as_(self.other_student)
        response = self.client.post(
            reverse("discussion-reply-list", args=[self.thread.id]),
            {"body": "Butting in"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_replies_come_back_oldest_first(self):
        first = services.create_reply(actor=self.student, thread=self.thread, body="One")
        second = services.create_reply(actor=self.lecturer, thread=self.thread, body="Two")
        self.as_(self.student)
        response = self.client.get(reverse("discussion-reply-list", args=[self.thread.id]))
        self.assertEqual(
            [row["id"] for row in self.data(response)["results"]],
            [str(first.id), str(second.id)],
        )

    def test_replying_bumps_the_thread(self):
        before = self.thread.last_activity_at
        services.create_reply(actor=self.student, thread=self.thread, body="Later")
        self.thread.refresh_from_db()
        self.assertGreater(self.thread.last_activity_at, before)

    def test_reply_count_is_reported_on_the_board(self):
        services.create_reply(actor=self.student, thread=self.thread, body="One")
        self.as_(self.student)
        response = self.client.get(reverse("discussion-thread-list"), self.term_params())
        self.assertEqual(self.data(response)["results"][0]["reply_count"], 1)

    def test_author_edits_their_own_reply_only(self):
        reply = services.create_reply(actor=self.student, thread=self.thread, body="Mine")
        self.as_(self.lecturer)
        response = self.client.patch(
            reverse("discussion-reply-detail", args=[reply.id]),
            {"body": "Rewritten by staff"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.as_(self.student)
        allowed = self.client.patch(
            reverse("discussion-reply-detail", args=[reply.id]),
            {"body": "Edited"},
            format="json",
        )
        self.assertEqual(self.data(allowed)["body"], "Edited")

    def test_empty_reply_is_rejected(self):
        with self.assertRaises(ValidationError):
            services.create_reply(actor=self.student, thread=self.thread, body="  ")


class ModerationTests(DiscussionTestBase):
    def setUp(self):
        super().setUp()
        self.thread = self.start_thread()

    def test_lecturer_pins_and_locks(self):
        self.as_(self.lecturer)
        response = self.client.patch(
            reverse("discussion-thread-detail", args=[self.thread.id]),
            {"is_pinned": True, "is_locked": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_pinned)
        self.assertTrue(self.thread.is_locked)

    def test_student_cannot_pin_or_lock(self):
        self.as_(self.student)
        response = self.client.patch(
            reverse("discussion-thread-detail", args=[self.thread.id]),
            {"is_pinned": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_locked_thread_takes_staff_replies_only(self):
        services.update_thread(actor=self.lecturer, thread=self.thread, is_locked=True)
        self.thread.refresh_from_db()

        with self.assertRaises(PermissionDenied):
            services.create_reply(actor=self.student, thread=self.thread, body="Still talking")

        staff_reply = services.create_reply(
            actor=self.lecturer, thread=self.thread, body="Closing note"
        )
        self.assertIsNotNone(staff_reply.pk)

    def test_lecturer_removes_a_students_thread(self):
        self.as_(self.lecturer)
        response = self.client.delete(reverse("discussion-thread-detail", args=[self.thread.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_removed)
        self.assertEqual(self.thread.removed_by_id, self.lecturer.id)
        self.assertIsNotNone(self.thread.removed_at)

    def test_a_removed_thread_leaves_the_board_for_everyone(self):
        services.remove_thread(actor=self.lecturer, thread=self.thread)
        for actor in (self.student, self.lecturer):
            self.as_(actor)
            listed = self.client.get(reverse("discussion-thread-list"), self.term_params())
            self.assertEqual(self.data(listed)["count"], 0)
            detail = self.client.get(reverse("discussion-thread-detail", args=[self.thread.id]))
            self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_removed_thread_takes_no_more_replies(self):
        services.remove_thread(actor=self.lecturer, thread=self.thread)
        self.thread.refresh_from_db()
        with self.assertRaises(ValidationError):
            services.create_reply(actor=self.student, thread=self.thread, body="Anyone there?")

    def test_author_may_remove_their_own_thread(self):
        services.remove_thread(actor=self.student, thread=self.thread)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_removed)

    def test_a_bystander_cannot_remove_someone_elses_thread(self):
        classmate = self.start_thread(actor=self.lecturer, title="Staff thread", body="x")
        with self.assertRaises(PermissionDenied):
            services.remove_thread(actor=self.student, thread=classmate)

    def test_removed_replies_drop_out_of_the_listing_and_the_count(self):
        kept = services.create_reply(actor=self.student, thread=self.thread, body="Kept")
        removed = services.create_reply(actor=self.student, thread=self.thread, body="Removed")
        services.remove_reply(actor=self.lecturer, reply=removed)

        self.as_(self.student)
        replies = self.client.get(reverse("discussion-reply-list", args=[self.thread.id]))
        self.assertEqual([row["id"] for row in self.data(replies)["results"]], [str(kept.id)])

        board = self.client.get(reverse("discussion-thread-list"), self.term_params())
        self.assertEqual(self.data(board)["results"][0]["reply_count"], 1)

    def test_unassigned_lecturer_cannot_moderate_another_course(self):
        with self.assertRaises(PermissionDenied):
            services.update_thread(actor=self.other_lecturer, thread=self.thread, is_pinned=True)
        with self.assertRaises(PermissionDenied):
            services.remove_thread(actor=self.other_lecturer, thread=self.thread)

    def test_school_admin_may_moderate(self):
        services.remove_thread(actor=self.admin, thread=self.thread)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_removed)
