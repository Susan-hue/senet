from rest_framework.views import APIView

from tenancy.scoping import set_current_institution


class TenantScopedViewMixin:
    """Activate tenant scoping from the DRF-authenticated user.

    CurrentInstitutionMiddleware runs before DRF resolves the JWT user, so the
    institution is set here (after authentication) so query scoping applies.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_current_institution(getattr(request.user, "institution", None))


class TenantAPIView(TenantScopedViewMixin, APIView):
    """Base view for endpoints that read or write tenant-scoped data."""
