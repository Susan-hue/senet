from django.db.models import Count
from rest_framework import status
from rest_framework.exceptions import NotFound

from accounts.coursework import (
    IsCourseManager,
    IsCourseParticipant,
    TenantAPIView,
    get_scoped,
    paginated,
    require_access,
    require_manager,
    resolve_course_term,
)
from accounts.responses import error_response, success_response
from content import services
from content.models import ContentItem, ContentView, Module
from content.serializers import (
    ContentItemSerializer,
    ContentViewSerializer,
    CreateItemSerializer,
    CreateModuleSerializer,
    ModuleSerializer,
    ReorderSerializer,
    UpdateItemSerializer,
    UpdateModuleSerializer,
)

MODULE_RELATIONS = ("course", "course__department", "session", "semester")
ITEM_RELATIONS = (
    "module",
    "module__course",
    "module__course__department",
    "module__session",
    "module__semester",
)


def _get_module(pk, user):
    return get_scoped(
        Module, pk, user, select_related=MODULE_RELATIONS, message="Module not found."
    )


def _get_item(pk, user):
    return get_scoped(
        ContentItem, pk, user, select_related=ITEM_RELATIONS, message="Content item not found."
    )


class ModuleListCreateView(TenantAPIView):
    def get_permissions(self):
        return [IsCourseManager()] if self.request.method == "POST" else [IsCourseParticipant()]

    def get(self, request):
        course, session, semester = resolve_course_term(request)
        require_access(request.user, course, session, semester)
        qs = (
            services.visible_modules(
                request.user, course=course, session=session, semester=semester
            )
            .select_related("course")
            .annotate(item_count=Count("items"))
            .order_by("position", "created_at", "id")
        )
        return paginated(request, self, qs, ModuleSerializer)

    def post(self, request):
        serializer = CreateModuleSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the module.", serializer.errors)
        module = services.create_module(actor=request.user, **serializer.validated_data)
        return success_response(
            ModuleSerializer(module).data, "Module created.", status.HTTP_201_CREATED
        )


class ModuleDetailView(TenantAPIView):
    def get_permissions(self):
        return [IsCourseParticipant()] if self.request.method == "GET" else [IsCourseManager()]

    def get(self, request, pk):
        module = services.visible_modules(request.user).filter(pk=pk).first()
        if module is None:
            raise NotFound("Module not found.")
        return success_response(ModuleSerializer(module).data)

    def patch(self, request, pk):
        module = _get_module(pk, request.user)
        serializer = UpdateModuleSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Could not update the module.", serializer.errors)
        module = services.update_module(
            actor=request.user, module=module, **serializer.validated_data
        )
        return success_response(ModuleSerializer(module).data, "Module updated.")

    def delete(self, request, pk):
        module = _get_module(pk, request.user)
        services.delete_module(actor=request.user, module=module)
        return success_response(None, "Module deleted.")


class ModuleReorderView(TenantAPIView):
    permission_classes = [IsCourseManager]

    def post(self, request):
        course, session, semester = resolve_course_term(request)
        serializer = ReorderSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not reorder the modules.", serializer.errors)
        modules = services.reorder_modules(
            actor=request.user,
            course=course,
            session=session,
            semester=semester,
            module_ids=serializer.validated_data["ids"],
        )
        return success_response(ModuleSerializer(modules, many=True).data, "Modules reordered.")


class ItemListCreateView(TenantAPIView):
    def get_permissions(self):
        return [IsCourseManager()] if self.request.method == "POST" else [IsCourseParticipant()]

    def get(self, request, pk):
        module = _get_module(pk, request.user)
        require_access(request.user, module.course, module.session, module.semester)
        qs = services.annotate_viewed(
            services.visible_items(request.user, module=module).select_related("module"),
            request.user,
        ).order_by("position", "created_at", "id")
        return paginated(request, self, qs, ContentItemSerializer)

    def post(self, request, pk):
        module = _get_module(pk, request.user)
        serializer = CreateItemSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not create the content item.", serializer.errors)
        item = services.create_item(actor=request.user, module=module, **serializer.validated_data)
        return success_response(
            ContentItemSerializer(item).data, "Content item created.", status.HTTP_201_CREATED
        )


class ItemReorderView(TenantAPIView):
    permission_classes = [IsCourseManager]

    def post(self, request, pk):
        module = _get_module(pk, request.user)
        serializer = ReorderSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Could not reorder the items.", serializer.errors)
        items = services.reorder_items(
            actor=request.user, module=module, item_ids=serializer.validated_data["ids"]
        )
        return success_response(ContentItemSerializer(items, many=True).data, "Items reordered.")


class ItemDetailView(TenantAPIView):
    def get_permissions(self):
        return [IsCourseParticipant()] if self.request.method == "GET" else [IsCourseManager()]

    def get(self, request, pk):
        item = (
            services.annotate_viewed(
                services.visible_items(request.user).select_related("module"), request.user
            )
            .filter(pk=pk)
            .first()
        )
        if item is None:
            raise NotFound("Content item not found.")
        return success_response(ContentItemSerializer(item).data)

    def patch(self, request, pk):
        item = _get_item(pk, request.user)
        serializer = UpdateItemSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Could not update the content item.", serializer.errors)
        item = services.update_item(actor=request.user, item=item, **serializer.validated_data)
        return success_response(ContentItemSerializer(item).data, "Content item updated.")

    def delete(self, request, pk):
        item = _get_item(pk, request.user)
        services.delete_item(actor=request.user, item=item)
        return success_response(None, "Content item deleted.")


class ItemViewedView(TenantAPIView):
    """A student records that they opened an item."""

    permission_classes = [IsCourseParticipant]

    def post(self, request, pk):
        item = _get_item(pk, request.user)
        view = services.record_view(student=request.user, item=item)
        if view is None:
            return success_response(None, "No read receipt recorded for staff.")
        return success_response(ContentViewSerializer(view).data, "View recorded.")


class ItemViewsView(TenantAPIView):
    """Who has opened an item — the lecturer's side of the read receipts."""

    permission_classes = [IsCourseManager]

    def get(self, request, pk):
        item = _get_item(pk, request.user)
        module = item.module
        require_manager(request.user, module.course, module.session, module.semester)
        qs = (
            ContentView.all_objects.filter(item=item)
            .select_related("student")
            .order_by("student__full_name", "id")
        )
        return paginated(request, self, qs, ContentViewSerializer)
