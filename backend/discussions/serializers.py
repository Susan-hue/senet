from rest_framework import serializers

from accounts.coursework import CourseTermSerializer
from discussions.models import Reply, Thread


class ThreadSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    author_role = serializers.CharField(source="author.role", read_only=True)
    course_code = serializers.CharField(source="course.code", read_only=True)
    reply_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Thread
        fields = [
            "id",
            "institution",
            "course",
            "course_code",
            "session",
            "semester",
            "author",
            "author_name",
            "author_role",
            "title",
            "body",
            "is_pinned",
            "is_locked",
            "reply_count",
            "last_activity_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateThreadSerializer(CourseTermSerializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField()
    is_pinned = serializers.BooleanField(required=False, default=False)


class UpdateThreadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    body = serializers.CharField(required=False)
    is_pinned = serializers.BooleanField(required=False)
    is_locked = serializers.BooleanField(required=False)


class ReplySerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    author_role = serializers.CharField(source="author.role", read_only=True)

    class Meta:
        model = Reply
        fields = [
            "id",
            "institution",
            "thread",
            "author",
            "author_name",
            "author_role",
            "body",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReplyInputSerializer(serializers.Serializer):
    body = serializers.CharField()
