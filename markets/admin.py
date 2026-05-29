from django.contrib import admin
from django.utils.safestring import mark_safe
from django import forms
from decimal import Decimal
from .models import Market, Bet, PriceHistory, ChatMessage
from .lmsr import price_yes, calculate_q_for_probability


class MarketAdminForm(forms.ModelForm):
    """Custom form for Market admin"""
    
    class Meta:
        model = Market
        fields = '__all__'
    
    def clean(self):
        """Validate market data before saving"""
        cleaned_data = super().clean()
        yes_prob = cleaned_data.get('yes_probability', 50)
        
        # Validate probability is between 1 and 99
        if yes_prob and (yes_prob < 1 or yes_prob > 99):
            self.add_error('yes_probability', 'YES probability must be between 1 and 99')
        
        return cleaned_data


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    form = MarketAdminForm
    
    list_display = ('question', 'category', 'status', 'market_type', 'yes_probability', 'q_display', 'volume', 'created_at')
    list_filter = ('status', 'category', 'market_type', 'created_at')
    search_fields = ('question', 'description')
    readonly_fields = ('created_at', 'q_yes', 'q_no', 'b', 'q_display')
    
    fieldsets = (
        ('Market Info', {
            'fields': ('question', 'description', 'category', 'image_url')
        }),
        ('Market Configuration', {
            'fields': ('market_type', 'yes_probability', 'options')
        }),
        ('Status & Dates', {
            'fields': ('status', 'end_date', 'created_at', 'resolved_at', 'resolved_outcome', 'trading_end_time')
        }),
        ('LMSR Parameters', {
            'fields': ('q_yes', 'q_no', 'b', 'q_display'),
            'description': 'These are automatically calculated from yes_probability and should not be modified directly.',
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('volume',)
        }),
    )
    
    date_hierarchy = 'created_at'
    
    def q_display(self, obj):
        """Show current q values and corresponding price"""
        if obj.q_yes is not None and obj.q_no is not None and obj.b:
            try:
                prob = price_yes(float(obj.q_yes), float(obj.q_no), float(obj.b)) * 100
                return f"q_yes={obj.q_yes:.2f}, q_no={obj.q_no:.2f} → {prob:.1f}% YES"
            except:
                return "Error calculating price"
        return "q values not set"
    q_display.short_description = "LMSR q values (read-only)"
    
    def save_model(self, request, obj, form, change):
        """Override save to calculate q_yes/q_no from yes_probability"""
        # If creating new market or yes_probability changed, recalculate q values
        if not change or form.cleaned_data.get('yes_probability') != obj.yes_probability:
            yes_prob = float(obj.yes_probability) / 100.0
            
            # Clamp to valid range to avoid log(0)
            yes_prob = max(0.01, min(0.99, yes_prob))
            
            b = float(obj.b) if obj.b else 100.0
            
            # Use the centralized formula function
            obj.q_yes = calculate_q_for_probability(yes_prob, b)
            obj.q_no = 0.0
        
        super().save_model(request, obj, form, change)
    



@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = ('user', 'market', 'outcome', 'amount', 'action', 'entry_probability', 'timestamp')
    list_filter = ('outcome', 'action', 'order_type', 'timestamp')
    search_fields = ('user__phone_number', 'market__question', 'id')
    readonly_fields = ('timestamp',)
    fieldsets = (
        ('Bet Details', {
            'fields': ('user', 'market', 'outcome', 'amount', 'action')
        }),
        ('Option Info', {
            'fields': ('option_id', 'option_label'),
            'classes': ('collapse',)
        }),
        ('Pricing', {
            'fields': ('entry_probability', 'order_type', 'limit_price', 'quantity')
        }),
        ('Dates', {
            'fields': ('timestamp',)
        }),
    )
    date_hierarchy = 'timestamp'


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('market', 'option_id', 'yes_probability', 'no_probability', 'timestamp')
    list_filter = ('market', 'option_id', 'timestamp')
    search_fields = ('market__question',)
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('user', 'market', 'message_preview', 'created_at')
    list_filter = ('market', 'created_at')
    search_fields = ('user__phone_number', 'market__question', 'message')
    readonly_fields = ('created_at',)
    
    def message_preview(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    message_preview.short_description = 'Message'
