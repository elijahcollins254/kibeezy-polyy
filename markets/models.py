from django.db import models
from django.conf import settings

class Market(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
        ('RESOLVED', 'Resolved'),
    ]
    
    CATEGORY_CHOICES = [
        ('Sports', 'Sports'),
        ('Politics', 'Politics'),
        ('Economy', 'Economy'),
        ('Crypto', 'Crypto'),
        ('Environment', 'Environment'),
        # Mentions
        # Live
    ]

    MARKET_TYPE_CHOICES = [
        ('BINARY', 'Binary'),
        ('OPTION_LIST', 'Option List'),
    ]

    question = models.CharField(max_length=500)
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES)
    description = models.TextField(blank=True, null=True)
    # aws s3
    image_url = models.URLField(max_length=1000, blank=True, null=True)
    market_type = models.CharField(max_length=20, choices=MARKET_TYPE_CHOICES, default='BINARY')
    yes_probability = models.IntegerField(default=50)  # For BINARY markets
    options = models.JSONField(null=True, blank=True)  # For OPTION_LIST markets: [{"id": 1, "label": "...", "yes_probability": 50}, ...]
    volume = models.CharField(max_length=100, default="KES 0")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    end_date = models.CharField(max_length=100)
    resolved_outcome = models.CharField(max_length=10, choices=[('Yes', 'Yes'), ('No', 'No')], null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_markets')
    is_live = models.BooleanField(default=True)  # Kept for backward compatibility
    
    # LMSR (Logarithmic Market Scoring Rule) fields
    q_yes = models.FloatField(default=0.0)  # YES quantity scalar
    q_no = models.FloatField(default=0.0)   # NO quantity scalar
    b = models.FloatField(default=100.0)    # Liquidity parameter (higher = more liquidity)
    
    # Market control fields
    trading_end_time = models.DateTimeField(null=True, blank=True)  # When trading closes

    def __str__(self):
        return self.question

class Bet(models.Model):
    RESULT_CHOICES = [
        ('PENDING', 'Pending'),
        ('WON', 'Won'),
        ('LOST', 'Lost'),
    ]
    
    ACTION_CHOICES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]
    
    ORDER_STATUS_CHOICES = [
        ('PENDING', 'Pending'),  # Limit order waiting to be filled
        ('FILLED', 'Filled'),    # Order has been executed
        ('CANCELLED', 'Cancelled'),  # User cancelled
        ('EXPIRED', 'Expired'),   # Market closed before order was filled
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bets')
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='bets')
    outcome = models.CharField(max_length=10, choices=[('Yes', 'Yes'), ('No', 'No')])
    amount = models.DecimalField(max_digits=15, decimal_places=8)
    entry_probability = models.IntegerField(default=50)
    option_id = models.IntegerField(null=True, blank=True)  # For OPTION_LIST markets: identifies which option was traded
    option_label = models.CharField(max_length=255, null=True, blank=True)  # Denormalized for quick lookup
    ORDER_TYPE_CHOICES = [
        ('MARKET', 'Market'),
        ('LIMIT', 'Limit'),
    ]
    order_type = models.CharField(max_length=10, choices=ORDER_TYPE_CHOICES, default='MARKET')
    limit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    order_status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='FILLED')  # FILLED for market orders, PENDING for limit orders
    quantity = models.DecimalField(max_digits=15, decimal_places=8, default=1)  # Support fractional shares
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, default='PENDING')
    payout = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, default='BUY')
    timestamp = models.DateTimeField(auto_now_add=True)
    filled_at = models.DateTimeField(null=True, blank=True)  # When limit order was filled
    trading_fee = models.DecimalField(max_digits=15, decimal_places=8, default=0)  # Trading fee charged
    total_cost = models.DecimalField(max_digits=15, decimal_places=8, null=True, blank=True)  # Amount + fee
    
    def __str__(self):
        return f"{self.user.phone_number} - {self.market.question} - {self.outcome}"


class PriceHistory(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='price_history')
    option_id = models.IntegerField(null=True, blank=True)  # For OPTION_LIST markets
    yes_probability = models.IntegerField()
    no_probability = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['market', 'option_id', 'timestamp']),
        ]
    
    def __str__(self):
        option_str = f" Option {self.option_id}" if self.option_id else ""
        return f"{self.market.id}{option_str} - Yes: {self.yes_probability}% at {self.timestamp}"


class ChatMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_messages')
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='chat_messages')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.parent:
            return f"{self.user.phone_number} replied to {self.parent.user.phone_number} on {self.market.id}: {self.message[:40]}"
        return f"{self.user.phone_number} on {self.market.id}: {self.message[:40]}"


class LiquidityPool(models.Model):
    """
    Tracks liquidity pool for a market.
    Simple fee-distribution model: all fees are split equally among LPs.
    """
    market = models.OneToOneField(Market, on_delete=models.CASCADE, related_name='liquidity_pool')
    
    # Pool parameters
    fee_percent = models.FloatField(default=0.5)  # Trading fee percentage (0.5% default)
    withdrawal_fee_percent = models.FloatField(default=0.1)  # Withdrawal fee (0.1%)
    early_withdrawal_penalty = models.FloatField(default=0.02)  # 2% penalty if withdrawn within 7 days
    
    # Pool composition (in share terms, not KES)
    total_yes_shares = models.FloatField(default=0.0)  # Total YES shares in pool
    total_no_shares = models.FloatField(default=0.0)   # Total NO shares in pool
    
    # Fee tracking
    total_fees_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_unclaimed_fees = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"LP Pool - {self.market.question[:50]}"
    
    @property
    def total_liquidity_value_kes(self):
        """Estimate of total liquidity in KES (simplified)"""
        from .lmsr import price_yes as calc_price_yes
        q_yes = self.total_yes_shares
        q_no = self.total_no_shares
        b = self.market.b
        
        price_y = calc_price_yes(q_yes, q_no, b)
        yes_value = q_yes * price_y * 100  # 100 KES per share payout
        no_value = q_no * (1 - price_y) * 100
        return yes_value + no_value


class LiquidityProvider(models.Model):
    """
    Tracks individual liquidity provider positions.
    Simple model: LPs get pro-rata share of all fees from the pool.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lp_positions')
    pool = models.ForeignKey(LiquidityPool, on_delete=models.CASCADE, related_name='providers')
    
    # LP position details
    capital_provided = models.DecimalField(max_digits=15, decimal_places=2)  # Initial KES deposited
    yes_shares_owned = models.FloatField(default=0.0)  # YES shares this LP owns
    no_shares_owned = models.FloatField(default=0.0)   # NO shares this LP owns
    
    # Fee tracking
    total_fees_earned = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fees_claimed = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # Fees already withdrawn
    
    # Store unclaimed fees for efficiency
    unclaimed_fees = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Timestamps
    entry_date = models.DateTimeField(auto_now_add=True)
    last_fee_update = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'pool']
    
    def __str__(self):
        return f"{self.user.phone_number} - LP in {self.pool.market.question[:30]}"
    
    @property
    def lp_share_percent(self):
        """What percentage of the pool does this LP own?"""
        total_shares = self.pool.total_yes_shares + self.pool.total_no_shares
        if total_shares == 0:
            return 0
        my_shares = self.yes_shares_owned + self.no_shares_owned
        return (my_shares / total_shares) * 100
    
    @property
    def total_available_claimable(self):
        """Total fees available to claim (earned but not yet claimed)"""
        return self.total_fees_earned - self.fees_claimed


class FeeDistribution(models.Model):
    """
    Audit trail for fee distributions to LPs.
    Records each fee transaction from trades.
    """
    pool = models.ForeignKey(LiquidityPool, on_delete=models.CASCADE, related_name='fee_distributions')
    provider = models.ForeignKey(LiquidityProvider, on_delete=models.CASCADE, related_name='fee_history')
    
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    source_bet = models.ForeignKey(Bet, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    is_claimed = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Fee {self.fee_amount} KES to {self.provider.user.phone_number}"
