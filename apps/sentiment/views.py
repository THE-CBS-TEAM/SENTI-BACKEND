from rest_framework import viewsets, permissions, filters
from apps.sentiment.models import Comment
from apps.sentiment.serializers import CommentSerializer


class CommentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for comment lists, with support for searching comment text
    and filtering by tracked post, sentiment and brand mentions.
    """
    serializer_class = CommentSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_backends = (filters.SearchFilter,)
    search_fields = ('text', 'author_handle')

    def get_queryset(self):
        from django.db.models import Q
        qs = Comment.objects.filter(
            Q(tracked_post__campaign_inf__campaign__workspace__owner=self.request.user) |
            Q(tracked_post__campaign_inf__campaign__workspace__memberships__user=self.request.user)
        ).distinct()

        
        post_id = self.request.query_params.get('tracked_post_id')
        if post_id:
            qs = qs.filter(tracked_post_id=post_id)

        sentiment = self.request.query_params.get('sentiment')
        if sentiment:
            qs = qs.filter(sentiment=sentiment)

        brand_ment = self.request.query_params.get('brand_mentioned')
        if brand_ment:
            qs = qs.filter(brand_mentioned=brand_ment.lower() == 'true')

        return qs
