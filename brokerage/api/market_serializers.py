from rest_framework import serializers
from brokerage.models import Market


class MarketChildSerializer(serializers.ModelSerializer):
    """Serializer for child markets (no nesting to prevent infinite recursion)"""
    class Meta:
        model = Market
        fields = ('id', 'external_id', 'title', 'question', 'description', 'category', 'source', 'is_approved', 'metadata', 'created_at', 'parent_market')


class MarketSerializer(serializers.ModelSerializer):
    """Serializer for markets with nested children"""
    children = MarketChildSerializer(many=True, read_only=True)
    
    class Meta:
        model = Market
        fields = ('id', 'external_id', 'title', 'question', 'description', 'category', 'source', 'is_approved', 'metadata', 'created_at', 'parent_market', 'children')
