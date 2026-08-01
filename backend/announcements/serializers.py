from rest_framework import serializers

from accounts.coursework import CourseTermSerializer
from announcements.models import Announcement


class AnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = Announcement
        fields = [
            "id",
            "institution",
            "course",
            "course_code",
            "course_title",
            "session",
            "semester",
            "author",
            "author_name",
            "title",
            "body",
            "is_pinned",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateAnnouncementSerializer(CourseTermSerializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField()
    is_pinned = serializers.BooleanField(required=False, default=False)
    notify = serializers.BooleanField(required=False, default=True)


class UpdateAnnouncementSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    body = serializers.CharField(required=False)
    is_pinned = serializers.BooleanField(required=False)
