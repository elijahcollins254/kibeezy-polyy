from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status

from brokerage.models import MarketCategory


class CategoryListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        categories = MarketCategory.objects.prefetch_related('subcategories').order_by('order', 'name')
        payload = []
        for category in categories:
            payload.append({
                'id': category.id,
                'name': category.name,
                'slug': category.slug,
                'order': category.order,
                'subcategories': [
                    {
                        'id': subcategory.id,
                        'name': subcategory.name,
                        'slug': subcategory.slug,
                        'order': subcategory.order,
                    }
                    for subcategory in category.subcategories.all().order_by('order', 'name')
                ],
            })

        return Response(payload, status=status.HTTP_200_OK)
