from tenancy.scoping import get_current_institution


class TenantScopedSerializerMixin:
    """Bind related-field querysets to the request's institution.

    ``tenant_scoped_fields`` maps a related field name to the model it points
    at, or to a ``(model, extra_filters)`` pair when the choices are narrowed
    further (a role, say). Outside a tenant context every such field accepts
    nothing, so a serializer can never resolve a primary key from another
    university.
    """

    tenant_scoped_fields: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institution = get_current_institution()
        for name, spec in self.tenant_scoped_fields.items():
            model, extra = spec if isinstance(spec, tuple) else (spec, {})
            field = self.fields[name]
            # A many=True relation holds its queryset on the child field.
            relation = getattr(field, "child_relation", field)
            if institution is None:
                relation.queryset = model._default_manager.none()
            else:
                manager = getattr(model, "all_objects", model._default_manager)
                relation.queryset = manager.filter(institution=institution, **extra)
