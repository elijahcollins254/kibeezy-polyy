from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status

from brokerage.api.serializers import PlaceOrderSerializer, OrderSerializer
from brokerage.services.trading import TradingService
from brokerage.tasks import execute_order_task
from brokerage.utils.signature import verify_signature
import time


class PlaceOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        svc = TradingService()
        data = serializer.validated_data
        user = request.user
        # Optional signature verification for non-custodial flows.
        sig = data.get('signature')
        signer = data.get('signer_address')
        if sig:
            # Build canonical payload that the client should have signed
            payload = {
                'market_id': data['market_id'],
                'side': data['side'],
                'size': str(data['size']),
                'price': str(data['price']),
            }
            # include optional nonce/timestamp if present
            if data.get('nonce'):
                payload['nonce'] = data.get('nonce')
            if data.get('timestamp'):
                payload['timestamp'] = data.get('timestamp')

            # If timestamp present, reject if too old to mitigate replay (2 minutes)
            ts = data.get('timestamp')
            if ts and abs(int(time.time()) - int(ts)) > 120:
                return Response({'error': 'signature timestamp out of window'}, status=status.HTTP_400_BAD_REQUEST)

            # Determine expected address: prefer explicit signer_address, else attempt user profile
            expected_addr = signer or getattr(user, 'eth_address', None) or getattr(user, 'wallet_address', None)
            if not expected_addr:
                return Response({'error': 'no expected signer address available; register an address or omit signature'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                ok = verify_signature(payload, sig, expected_addr)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

            if not ok:
                return Response({'error': 'invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            order = svc.place_user_order(user, data['market_id'], data['side'], data['size'], data['price'])
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Enqueue background task for extra processing (idempotent)
        try:
            execute_order_task.delay(order.id)
        except Exception:
            # Don't block user flow if Celery unavailable; it's best-effort
            pass

        out = OrderSerializer(order)
        return Response(out.data, status=status.HTTP_201_CREATED)
