from rest_framework import serializers
from brokerage.models import Market


class MarketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Market
        fields = ('id', 'external_id', 'title', 'question', 'description', 'category', 'source', 'is_approved', 'metadata', 'created_at')
