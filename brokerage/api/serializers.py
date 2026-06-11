from rest_framework import serializers
from brokerage.models import Order


class PlaceOrderSerializer(serializers.Serializer):
    market_id = serializers.CharField(max_length=128)
    side = serializers.ChoiceField(choices=['BUY', 'SELL'])
    size = serializers.DecimalField(max_digits=20, decimal_places=8)
    price = serializers.DecimalField(max_digits=20, decimal_places=8)
    # Polymarket specific fields
    token_id = serializers.CharField(max_length=256, required=False, allow_blank=True)
    order_type = serializers.ChoiceField(choices=['market', 'limit'], required=False, default='market')
    # Optional client-side signature fields for non-custodial flows
    signature = serializers.CharField(required=False, allow_blank=True)
    signer_address = serializers.CharField(required=False, allow_blank=True)
    nonce = serializers.CharField(required=False, allow_blank=True)
    timestamp = serializers.IntegerField(required=False)


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ('id', 'user', 'market', 'side', 'size', 'price', 'status', 'external_order_id', 'created_at')

