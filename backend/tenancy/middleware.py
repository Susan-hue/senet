from tenancy.scoping import clear_current_institution, set_current_institution


class CurrentInstitutionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        institution = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            institution = getattr(user, "institution", None)

        set_current_institution(institution)
        try:
            response = self.get_response(request)
        finally:
            clear_current_institution()
        return response
