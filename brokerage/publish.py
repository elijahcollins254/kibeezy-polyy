from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def publish_market_event(market_id: str, event: dict):
    """Publish an event to market group (sync-friendly helper)."""
    channel_layer = get_channel_layer()
    group = f'market_{market_id}'
    async_to_sync(channel_layer.group_send)(
        group,
        {
            'type': 'market_event',
            'event': event,
        }
    )
