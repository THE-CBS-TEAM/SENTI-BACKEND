from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardAdminPagination(PageNumberPagination):
    """
    Universal server-side pagination for all Admin CMS and Developer tables.
    Returns count, total_pages, current_page, page_size, and results.
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'results': data
        })
