from django.db import models
from users.models import CustomUser
from django.utils import timezone

class SupportTicket(models.Model):
    """Model for support tickets with tracking and assignment"""
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]
    
    ticket_id = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='support_tickets')
    assigned_to = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, 
                                     related_name='assigned_tickets', limit_choices_to={'is_support_staff': True})
    CATEGORY_CHOICES = [
        ('GENERAL', 'General'),
        ('ACCOUNT', 'Account'),
        ('PAYMENT', 'Payment'),
        ('TECHNICAL', 'Technical'),
        ('FEATURE_REQUEST', 'Feature Request'),
    ]
    subject = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='GENERAL')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Support Ticket'
        verbose_name_plural = 'Support Tickets'
    
    def __str__(self):
        return f"{self.ticket_id} - {self.subject} ({self.status})"
    
    def save(self, *args, **kwargs):
        if not self.ticket_id:
            # Generate ticket ID like TK-001, TK-002, etc.
            last_ticket = SupportTicket.objects.exclude(ticket_id='').order_by('-id').first()
            if last_ticket:
                last_num = int(last_ticket.ticket_id.split('-')[1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.ticket_id = f'TK-{new_num:05d}'
        
        if self.status == 'RESOLVED' and not self.resolved_at:
            self.resolved_at = timezone.now()
        
        super().save(*args, **kwargs)


class SupportMessage(models.Model):
    """Model to store support messages between users and support team"""
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='support_messages_sent')
    message = models.TextField()
    is_from_user = models.BooleanField(default=True)  # True if from user, False if from support team
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Support Message'
        verbose_name_plural = 'Support Messages'

    def __str__(self):
        return f"Message in {self.ticket.ticket_id} - {self.created_at}"


from brokerage.models import ChatMessage as BrokerageChatMessage


class ChatMessage(BrokerageChatMessage):
    """Compatibility proxy for brokerage chat messages so support chat uses the brokerage app."""

    class Meta:
        proxy = True
        app_label = 'support'
        ordering = ['-created_at']
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'

    @property
    def parent_comment(self):
        return self.parent

    @parent_comment.setter
    def parent_comment(self, value):
        self.parent = value

    def __str__(self):
        market_info = f" on {self.market.title}" if self.market else ""
        reply_info = " (reply)" if self.parent_comment else ""
        return f"{self.user.full_name}{market_info}{reply_info} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
