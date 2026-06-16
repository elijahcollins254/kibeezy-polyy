"""
Database migration to add Polymarket resolution and settlement fields
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brokerage', '0001_initial'),  # Adjust this to match your latest migration
    ]

    operations = [
        # Add fields to Market model
        migrations.AddField(
            model_name='market',
            name='polymarket_status',
            field=models.CharField(
                blank=True,
                choices=[('OPEN', 'Open'), ('CLOSED', 'Closed'), ('RESOLVED', 'Resolved'), ('INVALID', 'Invalid')],
                help_text='Market status on Polymarket (OPEN, CLOSED, RESOLVED)',
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='resolution_outcome',
            field=models.CharField(
                blank=True,
                choices=[('Yes', 'Yes'), ('No', 'No'), ('INVALID', 'Invalid')],
                help_text='Resolved outcome from Polymarket',
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='resolution_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=8,
                help_text='Final market price at resolution (0-1)',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='market',
            name='settlement_status',
            field=models.CharField(
                choices=[('PENDING', 'Pending'), ('PROCESSING', 'Processing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')],
                default='PENDING',
                help_text='Settlement status for user positions',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='settlement_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='market',
            name='settlement_completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        
        # Add fields to Order model
        migrations.AddField(
            model_name='order',
            name='payout',
            field=models.DecimalField(
                blank=True,
                decimal_places=8,
                help_text='Payout amount for resolved market',
                max_digits=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='settlement_result',
            field=models.CharField(
                choices=[('PENDING', 'Pending'), ('WON', 'Won'), ('LOST', 'Lost')],
                default='PENDING',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='settled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
