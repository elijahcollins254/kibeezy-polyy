from rest_framework import serializers
from brokerage.models import Market
from brokerage.utils.category import extract_category, extract_subcategory


class MarketChildSerializer(serializers.ModelSerializer):
    """Serializer for child markets (no nesting to prevent infinite recursion)"""
    category_slug = serializers.CharField(read_only=True)
    subcategory_slug = serializers.CharField(read_only=True)
    class Meta:
        model = Market
        fields = (
            'id', 'external_id', 'title', 'question', 'description',
            'category', 'subcategory', 'category_slug', 'subcategory_slug',
            'source', 'is_approved', 'metadata', 'created_at', 'parent_market'
        )


class MarketSerializer(serializers.ModelSerializer):
    """Serializer for markets with nested children"""
    children = MarketChildSerializer(many=True, read_only=True)
    category_slug = serializers.CharField(read_only=True)
    subcategory_slug = serializers.CharField(read_only=True)
    
    def to_representation(self, instance):
        """Override to ensure category is properly categorized before serialization"""
        data = super().to_representation(instance)
        
        # If category is "Other" or missing, try to recategorize based on metadata
        if data.get('category') == 'Other' or not data.get('category'):
            if instance.metadata:
                inferred_category = extract_category(instance.metadata)
                data['category'] = inferred_category

        if not data.get('subcategory') and instance.metadata:
            data['subcategory'] = extract_subcategory(instance.metadata, data.get('category'))
        
        return data
    
    class Meta:
        model = Market
        fields = (
            'id', 'external_id', 'title', 'question', 'description',
            'category', 'subcategory', 'category_slug', 'subcategory_slug',
            'source', 'is_approved', 'metadata', 'created_at', 'parent_market', 'children'
        )
