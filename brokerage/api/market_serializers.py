from rest_framework import serializers
from brokerage.models import Market
from brokerage.utils.category import extract_category


class MarketChildSerializer(serializers.ModelSerializer):
    """Serializer for child markets (no nesting to prevent infinite recursion)"""
    class Meta:
        model = Market
        fields = ('id', 'external_id', 'title', 'question', 'description', 'category', 'source', 'is_approved', 'metadata', 'created_at', 'parent_market')


class MarketSerializer(serializers.ModelSerializer):
    """Serializer for markets with nested children"""
    children = MarketChildSerializer(many=True, read_only=True)
    
    def to_representation(self, instance):
        """Override to ensure category is properly categorized before serialization"""
        data = super().to_representation(instance)
        
        # If category is "Other" or missing, try to recategorize based on metadata
        if data.get('category') == 'Other' or not data.get('category'):
            if instance.metadata:
                inferred_category = extract_category(instance.metadata)
                data['category'] = inferred_category
        
        return data
    
    class Meta:
        model = Market
        fields = ('id', 'external_id', 'title', 'question', 'description', 'category', 'source', 'is_approved', 'metadata', 'created_at', 'parent_market', 'children')
