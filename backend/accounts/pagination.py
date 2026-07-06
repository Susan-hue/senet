from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class DirectoryPagination(PageNumberPagination):
    """Page-number pagination for large directory listings (users, courses).

    These endpoints never return the whole collection: a page is always
    applied, defaulting to ``page_size`` and hard-capped at ``max_page_size``.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "total_pages": self.page.paginator.num_pages,
                "results": data,
            }
        )
