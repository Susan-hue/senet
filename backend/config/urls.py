from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path


def healthz(_request):
    return HttpResponse("ok", content_type="text/plain")


def root(_request):
    return JsonResponse({"service": "senet-backend", "status": "ok"})


urlpatterns = [
    path("", root),
    path("healthz/", healthz),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/accounts/", include("accounts.academic_urls")),
]
