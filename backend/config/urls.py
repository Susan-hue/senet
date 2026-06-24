from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def healthz(_request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
]
