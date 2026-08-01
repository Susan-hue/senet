from django.conf import settings
from rest_framework import serializers

from accounts.coursework import CourseTermSerializer
from content.models import ContentItem, ContentView, Module


class ModuleSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Module
        fields = [
            "id",
            "institution",
            "course",
            "course_code",
            "course_title",
            "session",
            "semester",
            "created_by",
            "title",
            "description",
            "position",
            "is_published",
            "item_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateModuleSerializer(CourseTermSerializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_published = serializers.BooleanField(required=False, default=False)


class UpdateModuleSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_published = serializers.BooleanField(required=False)
    position = serializers.IntegerField(required=False, min_value=0)


class ReorderSerializer(serializers.Serializer):
    """An explicit, complete ordering — the whole list, in the order wanted."""

    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)


def _validate_upload(upload):
    name = (upload.name or "").lower()
    if not name.endswith(settings.CONTENT_ALLOWED_EXTENSIONS):
        allowed = ", ".join(settings.CONTENT_ALLOWED_EXTENSIONS)
        raise serializers.ValidationError(f"Only {allowed} files are accepted.")
    if upload.size > settings.CONTENT_MAX_FILE_BYTES:
        limit_mb = settings.CONTENT_MAX_FILE_BYTES // (1024 * 1024)
        raise serializers.ValidationError(f"File exceeds the maximum size of {limit_mb} MB.")
    return upload


class ContentItemSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    module_title = serializers.CharField(source="module.title", read_only=True)
    course = serializers.PrimaryKeyRelatedField(source="module.course", read_only=True)
    viewed = serializers.BooleanField(read_only=True, required=False)

    class Meta:
        model = ContentItem
        fields = [
            "id",
            "institution",
            "module",
            "module_title",
            "course",
            "created_by",
            "title",
            "description",
            "kind",
            "position",
            "is_published",
            "available_from",
            "file_url",
            "original_filename",
            "url",
            "body",
            "viewed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_file_url(self, item):
        if not item.file:
            return None
        try:
            return item.file.url
        except (ValueError, NotImplementedError):
            return None


class CreateItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=ContentItem.Kind.choices)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    file = serializers.FileField(required=False, allow_null=True)
    url = serializers.URLField(max_length=500, required=False, allow_blank=True, default="")
    body = serializers.CharField(required=False, allow_blank=True, default="")
    is_published = serializers.BooleanField(required=False, default=False)
    available_from = serializers.DateTimeField(required=False, allow_null=True)

    def validate_file(self, upload):
        return _validate_upload(upload) if upload else upload


class UpdateItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    kind = serializers.ChoiceField(choices=ContentItem.Kind.choices, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    file = serializers.FileField(required=False, allow_null=True)
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    is_published = serializers.BooleanField(required=False)
    position = serializers.IntegerField(required=False, min_value=0)
    available_from = serializers.DateTimeField(required=False, allow_null=True)

    def validate_file(self, upload):
        return _validate_upload(upload) if upload else upload


class ContentViewSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_identifier = serializers.CharField(source="student.identifier", read_only=True)

    class Meta:
        model = ContentView
        fields = [
            "id",
            "item",
            "student",
            "student_name",
            "student_identifier",
            "first_viewed_at",
            "last_viewed_at",
            "view_count",
        ]
        read_only_fields = fields
