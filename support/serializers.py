from rest_framework import serializers
from .models import SupportMessage, SupportTicket

class SupportMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.full_name', read_only=True)
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    timestamp = serializers.SerializerMethodField()

    class Meta:
        model = SupportMessage
        fields = ['id', 'sender', 'sender_name', 'sender_username', 'message', 'timestamp', 'is_from_user']

    def get_timestamp(self, obj):
        return obj.created_at.isoformat()


class SupportTicketSerializer(serializers.ModelSerializer):
    messages = SupportMessageSerializer(many=True, read_only=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True, allow_null=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True, allow_null=True)
    created_at_iso = serializers.SerializerMethodField()
    updated_at_iso = serializers.SerializerMethodField()
    resolved_at_iso = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = ['id', 'ticket_id', 'subject', 'user', 'user_name', 'user_username', 'assigned_to', 
                  'assigned_to_name', 'assigned_to_username', 'status', 'created_at_iso', 'updated_at_iso', 
                  'resolved_at_iso', 'messages']

    def get_created_at_iso(self, obj):
        return obj.created_at.isoformat()
    
    def get_updated_at_iso(self, obj):
        return obj.updated_at.isoformat()
    
    def get_resolved_at_iso(self, obj):
        return obj.resolved_at.isoformat() if obj.resolved_at else None


class SupportTicketListSerializer(serializers.ModelSerializer):
    """Lighter serializer for ticket lists"""
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True, allow_null=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True, allow_null=True)
    message_count = serializers.SerializerMethodField()
    created_at_iso = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = ['id', 'ticket_id', 'subject', 'user', 'user_name', 'user_username', 'assigned_to', 
                  'assigned_to_name', 'assigned_to_username', 'status', 'created_at_iso', 'message_count']

    def get_message_count(self, obj):
        return obj.messages.count()
    
    def get_created_at_iso(self, obj):
        return obj.created_at.isoformat()
