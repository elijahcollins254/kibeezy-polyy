from django.db import models
from django.conf import settings
from django.db.models import Sum, Q


class Account(models.Model):
    """Represents a ledger account (e.g., Cash, User Liability, Market Escrow)."""
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    def balance(self):
        # Balance = sum(credits) - sum(debits)
        credits = LedgerEntry.objects.filter(credit_account=self).aggregate(total=Sum('amount'))['total'] or 0
        debits = LedgerEntry.objects.filter(debit_account=self).aggregate(total=Sum('amount'))['total'] or 0
        return credits - debits


class Transaction(models.Model):
    TYPE_CHOICES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('TRADE', 'Trade'),
        ('SETTLEMENT', 'Settlement'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='brokerage_transactions', null=True, blank=True)
    type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    reference = models.CharField(max_length=128, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} {self.reference or self.pk}"


class LedgerEntry(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='entries')
    debit_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='debits')
    credit_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='credits')
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    description = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.transaction} {self.debit_account.code}->{self.credit_account.code} {self.amount}"


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    currency = models.CharField(max_length=8, default='KES')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.currency}"

    def available_balance(self):
        # Available balance computed from ledger: user liability account credits - debits minus reserved
        liability_account_code = f"LIABILITY_USER_{self.user.id}"
        try:
            acc = Account.objects.get(code=liability_account_code)
        except Account.DoesNotExist:
            return 0
        return acc.balance()


class Market(models.Model):
    SOURCE_CHOICES = [
        ('polymarket', 'Polymarket'),
        ('local', 'Local'),
    ]
    
    external_id = models.CharField(max_length=128, unique=True)
    title = models.CharField(max_length=255)
    question = models.TextField(blank=True, null=True, help_text="The actual market question")
    description = models.TextField(blank=True, null=True)
    resolution = models.CharField(max_length=32, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='local')
    is_approved = models.BooleanField(default=False, help_text="Check to show this market on your frontend")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "✓ Approved" if self.is_approved else "⊘ Pending"
        market_label = self.question or self.title
        return f"{status} | {self.source.upper()} | {market_label}"


class Position(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='positions')
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='positions')
    quantity = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    average_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'market')

    def __str__(self):
        return f"{self.user} - {self.market} ({self.quantity})"


class Order(models.Model):
    STATUS_CHOICES = [('PENDING', 'Pending'), ('OPEN', 'Open'), ('FILLED', 'Filled'), ('CANCELLED', 'Cancelled'), ('REJECTED', 'Rejected')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='orders')
    side = models.CharField(max_length=4)  # 'BUY'|'SELL'
    size = models.DecimalField(max_digits=20, decimal_places=8)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    external_order_id = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} {self.side} {self.size}@{self.price} ({self.status})"


class Fill(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='fills')
    external_fill_id = models.CharField(max_length=128, null=True, blank=True)
    size = models.DecimalField(max_digits=20, decimal_places=8)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Fill {self.size}@{self.price} for {self.order}"
