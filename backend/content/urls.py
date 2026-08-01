from django.urls import path

from content.views import (
    ItemDetailView,
    ItemListCreateView,
    ItemReorderView,
    ItemViewedView,
    ItemViewsView,
    ModuleDetailView,
    ModuleListCreateView,
    ModuleReorderView,
)

urlpatterns = [
    path("modules", ModuleListCreateView.as_view(), name="content-module-list"),
    path("modules/reorder", ModuleReorderView.as_view(), name="content-module-reorder"),
    path("modules/<uuid:pk>", ModuleDetailView.as_view(), name="content-module-detail"),
    path("modules/<uuid:pk>/items", ItemListCreateView.as_view(), name="content-item-list"),
    path(
        "modules/<uuid:pk>/items/reorder",
        ItemReorderView.as_view(),
        name="content-item-reorder",
    ),
    path("items/<uuid:pk>", ItemDetailView.as_view(), name="content-item-detail"),
    path("items/<uuid:pk>/view", ItemViewedView.as_view(), name="content-item-view"),
    path("items/<uuid:pk>/views", ItemViewsView.as_view(), name="content-item-views"),
]
