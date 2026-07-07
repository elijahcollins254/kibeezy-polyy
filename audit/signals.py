"""
Audit Signals - Automatically log changes to important models

This module uses Django signals to intercept saves and deletes
and log them to the AuditLog for complete traceability.
"""

import json
import logging
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django.apps import apps

from .models import AuditLog, AuditAlert, AuditSummary
from payments.models import Transaction
from users.models import CustomUser
from brokerage.models import Market

logger = logging.getLogger(__name__)

# Models to track (and field changes worth noting)
TRACKED_MODELS = {
    'payments.Transaction': {
        'sensitive_fields': ['amount', 'status', 'user'],
        'critical_fields': ['status'],  # Changes to these don't need full snapshot
    },
    'users.CustomUser': {
        'sensitive_fields': ['balance', 'phone_locked', 'kyc_verified'],
        'critical_fields': ['balance'],
    },
    'markets.Market': {
        'sensitive_fields': ['status', 'resolved_outcome'],
        'critical_fields': ['status', 'resolved_outcome'],
    },
}


def get_request_context():
    """
    Get current request context (user, IP, user agent) for audit logging.
    
    This should be called from middleware and stored in thread-local storage.
    For now, returns None - in production, implement proper context tracking.
    """
    # TODO: Implement thread-local context tracking via middleware
    return None


def log_change(model_name, instance, action, before_values=None, after_values=None,
               user=None, changes=None, severity='MEDIUM', description=''):
    """
    Create an AuditLog entry for a model change.
    
    Args:
        model_name: String like 'payments.Transaction'
        instance: Model instance
        action: One of AuditLog.ACTION_CHOICES
        before_values: Dict of field values before change
        after_values: Dict of field values after change
        user: User who made the change (optional)
        changes: Dict of {field: {old: ..., new: ...}}
        severity: Severity level
        description: Human-readable description
    """
    
    try:
        # Get request context
        ctx = get_request_context()
        ip_address = ctx.get('ip_address') if ctx else None
        user_agent = ctx.get('user_agent') if ctx else ''
        request_user = user or (ctx.get('user') if ctx else None)
        
        # Create object representation
        try:
            object_repr = str(instance)[:255]
        except:
            object_repr = f"{model_name}:{instance.pk}"
        
        # Determine severity based on action
        if action in ['DELETE', 'BALANCE_ADJUSTED', 'PAYOUT_ISSUED']:
            severity = 'CRITICAL'
        elif action in ['WITHDRAWAL', 'DEPOSIT', 'MARKET_RESOLVED']:
            severity = 'HIGH'
        
        # Create audit log
        AuditLog.objects.create(
            action=action,
            severity=severity,
            content_type=model_name,
            object_id=str(instance.pk),
            object_repr=object_repr,
            user=request_user,
            ip_address=ip_address,
            user_agent=user_agent,
            changes=changes or {},
            before_values=before_values or {},
            after_values=after_values or {},
            description=description,
        )
        
        logger.info(f"✓ Audit logged: {action} on {model_name}:{instance.pk}")
        
    except Exception as e:
        logger.error(f"Failed to create audit log: {str(e)}", exc_info=True)


# ============================================================================
# Transaction Model Tracking
# ============================================================================

@receiver(post_save, sender=Transaction)
def log_transaction_change(sender, instance, created, **kwargs):
    """Log transaction changes"""
    
    if created:
        # New transaction created
        log_change(
            'payments.Transaction',
            instance,
            action='CREATE' if instance.type == 'DEPOSIT' else 'CREATE',
            after_values={
                'amount': str(instance.amount),
                'type': instance.type,
                'status': instance.status,
                'user': str(instance.user.phone_number),
            },
            severity='HIGH' if instance.type in ['DEPOSIT', 'WITHDRAWAL'] else 'MEDIUM',
            description=f"{instance.type} of {instance.amount} KES by {instance.user.phone_number}"
        )
    else:
        # Transaction updated - specifically look for status changes
        # Get the old instance from DB
        try:
            old = Transaction.objects.get(pk=instance.pk)
            changes = {}
            
            if old.status != instance.status:
                changes['status'] = {'old': old.status, 'new': instance.status}
                
                action = 'UPDATE'
                if instance.status == 'COMPLETED' and instance.type == 'DEPOSIT':
                    action = 'DEPOSIT'
                elif instance.status == 'COMPLETED' and instance.type == 'WITHDRAWAL':
                    action = 'WITHDRAWAL'
                elif instance.status == 'COMPLETED' and instance.type == 'PAYOUT':
                    action = 'PAYOUT_ISSUED'
                
                log_change(
                    'payments.Transaction',
                    instance,
                    action=action,
                    before_values={'status': old.status},
                    after_values={'status': instance.status},
                    changes=changes,
                    severity='HIGH',
                    description=f"Transaction {instance.id} status changed to {instance.status}"
                )
        except Transaction.DoesNotExist:
            pass


# ============================================================================
# User Model Tracking
# ============================================================================

@receiver(post_save, sender=CustomUser)
def log_user_change(sender, instance, created, **kwargs):
    """Log user changes - especially balance modifications"""
    
    if created:
        log_change(
            'users.CustomUser',
            instance,
            action='CREATE',
            after_values={
                'phone': instance.phone_number,
                'kyc_verified': instance.kyc_verified,
            },
            description=f"User created: {instance.phone_number}"
        )
    else:
        # User updated - check for important changes
        try:
            old = CustomUser.objects.get(pk=instance.pk)
            changes = {}
            
            # Track balance changes (CRITICAL)
            if old.balance != instance.balance:
                changes['balance'] = {
                    'old': str(old.balance),
                    'new': str(instance.balance),
                    'delta': str(instance.balance - old.balance)
                }
                
                log_change(
                    'users.CustomUser',
                    instance,
                    action='BALANCE_ADJUSTED',
                    before_values={'balance': str(old.balance)},
                    after_values={'balance': str(instance.balance)},
                    changes=changes,
                    severity='CRITICAL',
                    description=f"Balance changed from {old.balance} to {instance.balance}"
                )
            
            # Track KYC verification
            if old.kyc_verified != instance.kyc_verified and instance.kyc_verified:
                log_change(
                    'users.CustomUser',
                    instance,
                    action='KYC_VERIFIED',
                    user=instance,
                    description=f"User {instance.phone_number} KYC verified"
                )
            
            # Track phone locking
            if old.phone_locked != instance.phone_locked:
                log_change(
                    'users.CustomUser',
                    instance,
                    action='UPDATE',
                    changes={'phone_locked': {'old': old.phone_locked, 'new': instance.phone_locked}},
                    description=f"Phone lock status changed for {instance.phone_number}"
                )
                
        except CustomUser.DoesNotExist:
            pass


# ============================================================================
# Market Model Tracking
# ============================================================================

@receiver(post_save, sender=Market)
def log_market_change(sender, instance, created, **kwargs):
    """Log market status changes"""
    
    if created:
        question_text = instance.question or instance.title or ''
        log_change(
            'markets.Market',
            instance,
            action='CREATE',
            after_values={'status': getattr(instance, 'status', None), 'question': question_text[:100]},
            description=f"Market created: {question_text[:50]}"
        )
    else:
        # Market updated
        try:
            old = Market.objects.get(pk=instance.pk)
            changes = {}
            
            old_status = getattr(old, 'status', None)
            new_status = getattr(instance, 'status', None)

            # Track status changes
            if old_status != new_status:
                changes['status'] = {'old': old_status, 'new': new_status}
                
                action = 'UPDATE'
                if new_status == 'RESOLVED':
                    action = 'MARKET_RESOLVED'
                
                log_change(
                    'markets.Market',
                    instance,
                    action=action,
                    changes=changes,
                    severity='HIGH',
                    description=f"Market status changed to {new_status}"
                )
            
            old_resolved_outcome = getattr(old, 'resolved_outcome', None)
            new_resolved_outcome = getattr(instance, 'resolved_outcome', None)

            # Track outcome resolution
            if old_resolved_outcome != new_resolved_outcome and new_resolved_outcome:
                log_change(
                    'markets.Market',
                    instance,
                    action='MARKET_RESOLVED',
                    changes={'resolved_outcome': {'old': old_resolved_outcome, 'new': new_resolved_outcome}},
                    severity='CRITICAL',
                    description=f"Market resolved: {new_resolved_outcome}"
                )
                
        except Market.DoesNotExist:
            pass


# ============================================================================
# Deletion Tracking
# ============================================================================

# Note: We use pre_delete to log deletion since the object still has data

@receiver(pre_delete, sender=Transaction)
def log_transaction_deletion(sender, instance, **kwargs):
    """Log when transactions are deleted (should be rare!)"""
    log_change(
        'payments.Transaction',
        instance,
        action='DELETE',
        before_values={
            'amount': str(instance.amount),
            'type': instance.type,
            'status': instance.status,
        },
        severity='CRITICAL',
        description=f"DELETION: Transaction {instance.id} deleted"
    )


@receiver(pre_delete, sender=Market)
def log_market_deletion(sender, instance, **kwargs):
    """Log market deletion"""
    log_change(
        'markets.Market',
        instance,
        action='DELETE',
        severity='CRITICAL',
        description=f"DELETION: Market {instance.id} ({instance.question[:50]}) deleted"
    )
