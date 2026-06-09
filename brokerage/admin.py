from django.contrib import admin
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
