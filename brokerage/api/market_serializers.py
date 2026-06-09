from rest_framework import serializers
from brokerage.models import Market


class MarketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Market
        fields = ('id', 'external_id', 'title', 'description', 'metadata', 'created_at')
