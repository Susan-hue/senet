from django.contrib import admin

from tenancy.models import Institution


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "grading_scale_type", "is_active")
    search_fields = ("name", "code")
