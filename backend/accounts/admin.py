from django.contrib import admin

from accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "role", "institution", "is_verified")
    list_filter = ("role", "institution", "is_verified")
    search_fields = ("full_name", "email", "identifier")
