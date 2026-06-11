from django.contrib import admin
from django.utils import timezone
from . import models


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name')
    search_fields = ('code', 'name')


@admin.register(models.Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'user', 'reference', 'created_at')
    list_filter = ('type',)
    search_fields = ('reference',)


@admin.register(models.LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'debit_account', 'credit_account', 'amount', 'created_at')
    list_filter = ('debit_account', 'credit_account')


@admin.register(models.Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'currency', 'created_at')


@admin.register(models.Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ('get_status', 'source', 'title', 'external_id', 'created_at', 'is_approved')
    list_filter = ('is_approved', 'source', 'created_at')
    search_fields = ('title', 'external_id', 'description')
    readonly_fields = ('external_id', 'created_at', 'approved_at')
    fieldsets = (
        ('Market Info', {
            'fields': ('external_id', 'title', 'description', 'source')
        }),
        ('Approval', {
            'fields': ('is_approved', 'approved_at'),
            'description': 'Check "is_approved" to show this market on your frontend'
        }),
        ('Metadata', {
            'fields': ('resolution', 'metadata', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_status(self, obj):
        if obj.is_approved:
            return '✓ Approved'
        return '⊘ Pending'
    get_status.short_description = 'Status'
    
    def save_model(self, request, obj, form, change):
        # Set approved_at timestamp when approving
        if obj.is_approved and not obj.approved_at:
            obj.approved_at = timezone.now()
        elif not obj.is_approved:
            obj.approved_at = None
        super().save_model(request, obj, form, change)


@admin.register(models.Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('user', 'market', 'quantity', 'average_price', 'updated_at')
    list_filter = ('market', 'updated_at')
    search_fields = ('user__username', 'market__title')
    readonly_fields = ('updated_at',)


@admin.register(models.Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'market', 'side', 'size', 'price', 'status', 'created_at')
    list_filter = ('status', 'side', 'created_at')
    search_fields = ('user__username', 'market__title', 'external_order_id')
    readonly_fields = ('created_at', 'external_order_id')


@admin.register(models.Fill)
class FillAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'size', 'price', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('order__id', 'external_fill_id')
    readonly_fields = ('created_at',)
